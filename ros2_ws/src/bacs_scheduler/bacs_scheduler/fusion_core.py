"""Server-side trust-weighted SE(2) pose-graph fusion (paper Eq. 1 and Eq. 6), ROS-free.

    x* = argmin_x  sum_odometry e^T Omega e  +  sum_inter-robot theta_ij e_ij^T Omega_ij e_ij          (1)
    theta_ij = max(floor, max(0, 1 - (||e_ij|| / tau_e)^p) * exp(-gamma * dt_ij))                    (6)

As in bacs_sim: ``||e_ij||`` is the translational part of (z_ij - relative(x_i, x_j)) evaluated
against the current fused estimate when the constraint arrives; ``dt_ij`` is receive time minus
generation time; theta is fixed once assigned; odometry edges have unit weight; the problem is
solved by Gauss-Newton. Defaults: tau_e = 0.5 m, p = 3, floor = 0.01, gamma = ln 2 / 155 s.

Inter-robot information defaults to the same fixed Omega bacs_sim uses (sigma 0.04 m, 0.02 rad);
``constraint_information="icp"`` uses the packet's ICP variances instead.

Gauge: every robot's first keyframe gets a prior at its measured start pose (floor marks); the
anchor robot's prior is tight, the others' are weak (``start_sigma``), mirroring the simulator,
where all robots start in a common frame and only node 0 is fixed.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from typing import IO, Any

import gtsam
import numpy as np

EDGE_FIELDS = ["t_rcv_ns", "robot_i", "kf_i", "robot_j", "kf_j", "seq", "residual_m", "age_s", "spatial",
               "temporal", "theta", "status"]


@dataclass
class FusionParams:
    tau_e: float = 0.5
    p: float = 3.0
    floor: float = 0.01
    gamma: float = math.log(2) / 155.0
    odom_sigma: tuple[float, float, float] = (0.04, 0.04, 0.02)     # per keyframe step (m, m, rad), as bacs_sim
    # Inter-robot information: "fixed" uses constraint_sigma for every edge, exactly as bacs_sim does
    # (it reuses the odometry information); "icp" uses the variances carried in the packet. ICP
    # covariances are typically over-confident, which makes even floor-weighted outliers strong.
    constraint_information: str = "fixed"
    constraint_sigma: tuple[float, float, float] = (0.04, 0.04, 0.02)
    anchor_sigma: tuple[float, float, float] = (1e-4, 1e-4, 1e-5)
    start_sigma: tuple[float, float, float] = (0.10, 0.10, 0.05)   # floor-mark placement accuracy
    iterations: int = 10


def pose2(x: float, y: float, theta: float) -> gtsam.Pose2:
    return gtsam.Pose2(float(x), float(y), float(theta))


def trust(residual_m: float, age_s: float, params: FusionParams) -> tuple[float, float, float]:
    """Eq. (6): returns (spatial, temporal, theta)."""
    spatial = max(0.0, 1.0 - (residual_m / params.tau_e) ** params.p)
    temporal = math.exp(-params.gamma * max(age_s, 0.0))
    return spatial, temporal, max(params.floor, spatial * temporal)


def t_gen_from_payload(t_rcv_ns: int, gen_ms_low32: int) -> int:
    """Recover the full generation time from the 32-bit millisecond field carried in the packet."""
    rcv_ms = t_rcv_ns // 1_000_000
    gen_ms = (rcv_ms & ~0xFFFFFFFF) | (gen_ms_low32 & 0xFFFFFFFF)
    if gen_ms > rcv_ms:
        gen_ms -= 1 << 32
    return gen_ms * 1_000_000


@dataclass
class FusionCore:
    robots: list[str]
    start_poses: dict[str, tuple[float, float, float]]
    params: FusionParams = field(default_factory=FusionParams)
    edge_log: IO[str] | None = None

    def __post_init__(self) -> None:
        missing = [r for r in self.robots if r not in self.start_poses]
        if missing:
            raise ValueError(f"start pose required for {missing}")
        self.graph = gtsam.NonlinearFactorGraph()
        self.estimate = gtsam.Values()
        self.local: dict[str, dict[int, gtsam.Pose2]] = {r: {} for r in self.robots}
        self.last_kf: dict[str, int] = {}
        self.pending: list[dict[str, Any]] = []
        self.thetas: list[float] = []
        self.dirty = False
        self.odom_noise = gtsam.noiseModel.Diagonal.Sigmas(np.array(self.params.odom_sigma))
        self.writer = None
        if self.edge_log is not None:
            self.writer = csv.DictWriter(self.edge_log, fieldnames=EDGE_FIELDS, lineterminator="\n")
            self.writer.writeheader()

    def key(self, robot: str, kf: int) -> int:
        return gtsam.symbol(chr(ord("a") + self.robots.index(robot)), kf)

    def has(self, robot: str, kf: int) -> bool:
        return self.estimate.exists(self.key(robot, kf))

    def pose(self, robot: str, kf: int) -> gtsam.Pose2:
        return self.estimate.atPose2(self.key(robot, kf))

    # --- inputs --------------------------------------------------------------------------------------
    def add_keyframe(self, robot: str, kf: int, x: float, y: float, yaw: float) -> None:
        """A keyframe of ``robot`` at local pose (x, y, yaw) in its own local frame."""
        local = pose2(x, y, yaw)
        if kf in self.local[robot]:
            return
        self.local[robot][kf] = local
        key = self.key(robot, kf)
        previous = self.last_kf.get(robot)
        if previous is None:
            start = pose2(*self.start_poses[robot])
            sigma = self.params.anchor_sigma if robot == self.robots[0] else self.params.start_sigma
            self.graph.add(gtsam.PriorFactorPose2(key, start, gtsam.noiseModel.Diagonal.Sigmas(np.array(sigma))))
            self.estimate.insert(key, start)
        else:
            delta = self.local[robot][previous].between(local)
            self.graph.add(gtsam.BetweenFactorPose2(self.key(robot, previous), key, delta, self.odom_noise))
            self.estimate.insert(key, self.pose(robot, previous).compose(delta))
        self.last_kf[robot] = kf
        self.dirty = True
        self._flush_pending()

    def add_constraint(self, c: dict[str, Any]) -> float | None:
        """A LoRa-delivered inter-robot constraint (receiver JSON). Returns theta, or None if buffered."""
        if not (self.has(c["robot_i"], int(c["kf_i"])) and self.has(c["robot_j"], int(c["kf_j"]))):
            self.pending.append(c)
            return None
        z = pose2(c["dx"], c["dy"], c["dtheta"])
        predicted = self.pose(c["robot_i"], int(c["kf_i"])).between(self.pose(c["robot_j"], int(c["kf_j"])))
        residual = math.hypot(z.x() - predicted.x(), z.y() - predicted.y())
        t_rcv = int(c["t_rcv_ns"])
        age = (t_rcv - t_gen_from_payload(t_rcv, int(c["gen_ms"]))) / 1e9
        spatial, temporal, theta = trust(residual, age, self.params)
        if self.params.constraint_information == "icp":
            info = np.diag([1.0 / float(c["var_x"]), 1.0 / float(c["var_y"]), 1.0 / float(c["var_theta"])])
        else:
            info = np.diag([1.0 / s ** 2 for s in self.params.constraint_sigma])
        self.graph.add(gtsam.BetweenFactorPose2(self.key(c["robot_i"], int(c["kf_i"])),
                                                self.key(c["robot_j"], int(c["kf_j"])), z,
                                                gtsam.noiseModel.Gaussian.Information(theta * info)))
        self.thetas.append(theta)
        self.dirty = True
        if self.writer is not None:
            self.writer.writerow({"t_rcv_ns": t_rcv, "robot_i": c["robot_i"], "kf_i": c["kf_i"],
                                  "robot_j": c["robot_j"], "kf_j": c["kf_j"], "seq": c.get("seq", ""),
                                  "residual_m": residual, "age_s": age, "spatial": spatial, "temporal": temporal,
                                  "theta": theta, "status": "ADDED"})
            self.edge_log.flush()
        return theta

    def _flush_pending(self) -> None:
        waiting, self.pending = self.pending, []
        for c in waiting:
            self.add_constraint(c)

    # --- solve and outputs ----------------------------------------------------------------------------
    def optimize(self) -> float:
        """Gauss-Newton on Eq. (1); returns the final total weighted error."""
        params = gtsam.GaussNewtonParams()
        params.setMaxIterations(self.params.iterations)
        self.estimate = gtsam.GaussNewtonOptimizer(self.graph, self.estimate, params).optimize()
        self.dirty = False
        return float(self.graph.error(self.estimate))

    def map_to_local(self, robot: str) -> tuple[float, float, float] | None:
        """Transform map -> robot's local frame, from its latest keyframe."""
        kf = self.last_kf.get(robot)
        if kf is None:
            return None
        t = self.pose(robot, kf).compose(self.local[robot][kf].inverse())
        return t.x(), t.y(), t.theta()
