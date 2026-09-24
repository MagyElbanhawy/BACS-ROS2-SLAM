import io
import math

import pytest

from ros2_ws.src.bacs_scheduler.bacs_scheduler.fusion_core import (
    FusionCore, FusionParams, pose2, t_gen_from_payload, trust)

T0 = 1_790_000_000_000_000_000


def test_trust_matches_eq6() -> None:
    params = FusionParams()
    assert params.gamma == pytest.approx(0.00447, abs=1e-5)
    assert trust(0.0, 155.0, params)[2] == pytest.approx(0.5)
    assert trust(0.25, 0.0, params)[2] == pytest.approx(1 - 0.5 ** 3)
    assert trust(0.6, 0.0, params)[2] == params.floor


def test_generation_time_recovered_from_32_bit_field() -> None:
    t_gen = T0 - 154_000_000_000
    gen_low = (t_gen // 1_000_000) & 0xFFFFFFFF
    assert t_gen_from_payload(T0, gen_low) == (t_gen // 1_000_000) * 1_000_000


def trajectories():
    """Two robots on straight parallel lines 1 m apart; robot 2's local frame is rotated and offset."""
    truth = {"limo01": [(0.3 * k, 0.0, 0.0) for k in range(20)],
             "limo02": [(0.3 * k, 1.0, 0.0) for k in range(20)]}
    frame2 = pose2(5.0, -2.0, 0.7)            # arbitrary origin of robot 2's local frame
    local = {"limo01": truth["limo01"],
             "limo02": [(p.x(), p.y(), p.theta()) for p in
                        (frame2.compose(pose2(0, 0, 0)).compose(pose2(x, y - 1.0, t)) for x, y, t in truth["limo02"])]}
    return truth, local


def constraint(kf_i: int, kf_j: int, dx: float, dy: float, age_s: float = 10.0) -> dict:
    return {"robot_i": "limo01", "kf_i": kf_i, "robot_j": "limo02", "kf_j": kf_j, "seq": kf_i,
            "dx": dx, "dy": dy, "dtheta": 0.0, "var_x": 0.01 ** 2, "var_y": 0.01 ** 2, "var_theta": 0.005 ** 2,
            "t_rcv_ns": T0, "gen_ms": ((T0 - int(age_s * 1e9)) // 1_000_000) & 0xFFFFFFFF}


def build(start2):
    truth, local = trajectories()
    log = io.StringIO()
    core = FusionCore(["limo01", "limo02"], {"limo01": (0.0, 0.0, 0.0), "limo02": start2}, edge_log=log)
    for k in range(20):
        for robot in ("limo01", "limo02"):
            core.add_keyframe(robot, k, *local[robot][k])
    return core, truth, log


def error2(core, truth) -> float:
    return max(math.hypot(core.pose("limo02", k).x() - x, core.pose("limo02", k).y() - y)
               for k, (x, y, _) in enumerate(truth["limo02"]))


def test_constraints_align_a_misplaced_robot_and_outliers_are_suppressed() -> None:
    results = {}
    for with_outlier in (False, True):
        core, truth, log = build(start2=(0.25, 1.15, 0.0))   # robot 2 placed 0.29 m off its mark
        core.optimize()
        before = error2(core, truth)
        thetas = [core.add_constraint(constraint(k, k, 0.0, 1.0)) for k in (2, 8, 14)]
        if with_outlier:
            thetas.append(core.add_constraint(constraint(18, 18, 2.0, -1.0)))   # 2.8 m wrong
        core.optimize()
        results[with_outlier] = (before, error2(core, truth), thetas, log.getvalue(), core)
    before, clean, thetas, _, _ = results[False]
    _, dirty, dirty_thetas, log, core = results[True]
    assert before > 0.25 and clean < before / 2
    assert all(0.7 < t < 0.8 for t in thetas)            # residual 0.29 m -> spatial 0.80; 10 s old -> 0.96
    assert dirty_thetas[-1] == FusionParams().floor and dirty - clean < 0.08
    assert log.count("ADDED") == 4
    x, y, yaw = core.map_to_local("limo02")
    latest = pose2(x, y, yaw).compose(core.local["limo02"][19])
    assert latest.x() == pytest.approx(core.pose("limo02", 19).x()) and latest.y() == pytest.approx(core.pose("limo02", 19).y())


def test_icp_information_option_uses_packet_variances() -> None:
    core = FusionCore(["limo01", "limo02"], {"limo01": (0, 0, 0), "limo02": (0, 1, 0)},
                      FusionParams(constraint_information="icp"))
    core.add_keyframe("limo01", 0, 0, 0, 0); core.add_keyframe("limo02", 0, 0, 0, 0)
    core.add_constraint(constraint(0, 0, 0.0, 1.0))
    factor = core.graph.at(core.graph.size() - 1)
    assert factor.noiseModel().R()[0, 0] == pytest.approx(math.sqrt(core.thetas[0]) / 0.01, rel=1e-6)


def test_constraint_waits_for_its_keyframes() -> None:
    core = FusionCore(["limo01", "limo02"], {"limo01": (0, 0, 0), "limo02": (0, 1, 0)})
    core.add_keyframe("limo01", 0, 0, 0, 0)
    assert core.add_constraint(constraint(0, 0, 0.0, 1.0)) is None and len(core.pending) == 1
    core.add_keyframe("limo02", 0, 0, 0, 0)
    assert core.pending == [] and len(core.thetas) == 1
