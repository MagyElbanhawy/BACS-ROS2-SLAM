import io
import math

import numpy as np
import pytest

from ros2_ws.src.bacs_scheduler.bacs_scheduler.candidate_generator import CandidateGenerator
from ros2_ws.src.bacs_scheduler.bacs_scheduler.place_recognition import Descriptor, compare, describe, icp, scan_to_points
from ros2_ws.src.bacs_scheduler.bacs_scheduler.sender_core import SENT, SenderCore
from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import DutyCycleBudget, Scheduler

# Asymmetric room (8 m x 6 m) with two boxes and a wall stub, as line segments.
SEGMENTS = np.array([
    [0, 0, 8, 0], [8, 0, 8, 6], [8, 6, 0, 6], [0, 6, 0, 0],
    [2, 1, 3, 1], [3, 1, 3, 2], [3, 2, 2, 2], [2, 2, 2, 1],
    [5.5, 4, 6.5, 4.5], [6.5, 4.5, 6, 5.5], [6, 5.5, 5.5, 4],
    [4, 6, 4, 4.8], [0, 3.5, 1.2, 3.5],
], dtype=float)


def raycast(x: float, y: float, theta: float, beams: int = 360, max_range: float = 12.0, noise: float = 0.005,
            seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    angles = -math.pi + 2 * math.pi * np.arange(beams) / beams
    ranges = np.full(beams, np.inf)
    for i, a in enumerate(angles):
        d = np.array([math.cos(theta + a), math.sin(theta + a)])
        for x1, y1, x2, y2 in SEGMENTS:
            e = np.array([x2 - x1, y2 - y1]); w = np.array([x1 - x, y1 - y])
            den = d[0] * (-e[1]) - d[1] * (-e[0])
            if abs(den) < 1e-12:
                continue
            t = (w[0] * (-e[1]) - w[1] * (-e[0])) / den
            u = (d[0] * w[1] - d[1] * w[0]) / den
            if t > 0 and 0 <= u <= 1:
                ranges[i] = min(ranges[i], t)
    ranges = ranges + rng.normal(0, noise, beams)
    return scan_to_points(ranges, -math.pi, 2 * math.pi / beams, 0.1, max_range)


def relative(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    """Pose of b expressed in a's frame."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    c, s = math.cos(a[2]), math.sin(a[2])
    return c * dx + s * dy, -s * dx + c * dy, math.atan2(math.sin(b[2] - a[2]), math.cos(b[2] - a[2]))


POSE_I, POSE_J, FAR = (4.5, 2.5, 0.3), (4.9, 2.9, 1.0), (1.2, 5.0, -2.0)


def test_place_recognition_shortlists_same_place_and_estimates_yaw() -> None:
    di, dj = describe(raycast(*POSE_I, seed=0)), describe(raycast(*POSE_J, seed=1))
    distance, yaw = compare(dj, di)
    assert distance < 0.12
    assert abs(math.atan2(math.sin(yaw - 0.7), math.cos(yaw - 0.7))) < math.radians(10)
    assert np.allclose(Descriptor.unpack(dj.pack()).profile, dj.profile, atol=1 / 255)


def test_far_keyframe_is_never_accepted() -> None:
    gen = CandidateGenerator("limo01", lambda: 0)
    other = CandidateGenerator("limo02", lambda: 0)
    message, _, _ = other.add_own_keyframe(3, 0, raycast(*FAR, seed=6))
    gen.add_remote_descriptor(message)
    _, requests, _ = gen.add_own_keyframe(0, 0, raycast(*POSE_I, seed=7))
    candidates = gen.add_remote_points(other.points_message(3)) if requests else []
    assert candidates == []


def test_icp_recovers_relative_pose() -> None:
    _, yaw = compare(describe(raycast(*POSE_J)), describe(raycast(*POSE_I)))
    result = icp(raycast(*POSE_J, seed=1), raycast(*POSE_I, seed=2), init=(0, 0, yaw))
    truth = relative(POSE_I, POSE_J)
    assert result.converged and result.inlier_ratio > 0.8
    assert result.x == pytest.approx(truth[0], abs=0.03) and result.y == pytest.approx(truth[1], abs=0.03)
    assert result.theta == pytest.approx(truth[2], abs=math.radians(1))
    assert np.all(np.isfinite(result.covariance)) and result.covariance[0, 0] < 1e-3


def test_two_generators_produce_a_sendable_candidate() -> None:
    clock = [10**18]
    tick = lambda: clock[0]  # noqa: E731
    log_i = io.StringIO()
    gen_i = CandidateGenerator("limo01", tick, attempts_log=log_i)
    gen_j = CandidateGenerator("limo02", tick)
    # robot j creates its keyframe first; robot i sees the descriptor, then creates its own keyframe nearby
    desc_j, requests, ready = gen_j.add_own_keyframe(7, clock[0], raycast(*POSE_J, seed=3))
    assert requests == [] and ready == []
    gen_i.add_remote_descriptor(desc_j)
    gen_i.add_own_keyframe(0, clock[0], raycast(*FAR, seed=4))           # elsewhere: no request
    _, requests, _ = gen_i.add_own_keyframe(1, clock[0], raycast(*POSE_I, seed=5))
    assert requests == [{"from": "limo01", "robot": "limo02", "kf": 7}]
    candidates = gen_i.add_remote_points(gen_j.points_message(7))
    assert len(candidates) == 1
    c = candidates[0]
    truth = relative(POSE_I, POSE_J)
    assert (c["robot_i"], c["robot_j"], c["kf_i"], c["kf_j"]) == ("limo01", "limo02", 1, 7)
    assert c["dx"] == pytest.approx(truth[0], abs=0.05) and c["dtheta"] == pytest.approx(truth[2], abs=0.03)
    assert 0.5 < c["predicted_trust"] <= 1 and 0 < c["information_score"] <= 1
    assert "candidate" in log_i.getvalue() and "shortlisted" in log_i.getvalue()

    class Radio:
        def command(self, line, timeout_s=2.0):
            return clock[0], clock[0] + 1, "+OK"
    log = io.StringIO()
    core = SenderCore(session="HWS-101-BACS+", run=1, policy="BACS+", robot="limo01", robots=["limo01", "limo02"],
                      radio=Radio(), destination=100, log=log, clock_ns=tick,
                      scheduler=Scheduler("BACS+", DutyCycleBudget()))
    core.enqueue(c)
    assert core.tick() == SENT
