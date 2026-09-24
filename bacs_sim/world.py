"""
Ground truth, odometry, and candidate constraint generation.

Robots sweep assigned partitions of a rectangular environment in a boustrophedon
pattern, mirroring the dynamic map partitioning of the parent framework.
Partitions overlap slightly so that inter-robot observations occur where the
sweeps meet, which is where the trust filter has work to do.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict

from .config import WorldConfig


def wrap(a):
    return (a + np.pi) % (2 * np.pi) - np.pi


@dataclass
class Constraint:
    """One candidate inter-robot constraint."""
    rid_from: int
    rid_to: int
    idx_from: int                 # pose index on the transmitting robot
    idx_to: int                   # pose index on the peer robot
    z: np.ndarray                 # measured relative transform (x, y, theta)
    t_created: float
    payload_bytes: int
    is_outlier: bool = False
    # --- filled during scheduling / transmission ---
    theta_hat: float = 0.0        # predicted trust, Eq. (9)
    info_hat: float = 0.0         # surrogate information gain, Eq. (12)
    utility: float = 0.0          # Eq. (13)
    dt_hat: float = 0.0           # predicted delay, Eq. (5)
    deferrals: int = 0            # k in the ageing term
    t_sent: float = 0.0
    t_recv: float = 0.0
    delivered: bool = False
    theta: float = 0.0            # server-side trust, Eq. (7)
    attempts: int = 0
    tampered: bool = False        # set by adversarial agents (Paper B)


@dataclass
class RobotTruth:
    rid: int
    gt: np.ndarray                # (T, 3) ground-truth poses
    odom: np.ndarray              # (T, 3) dead-reckoned poses
    t: np.ndarray                 # (T,) timestamps
    dist: np.ndarray              # (T,) cumulative distance travelled


def _boustrophedon(x0, x1, y0, y1, n, rng):
    """Lawnmower waypoints covering a rectangle."""
    lanes = max(int(np.ceil(np.sqrt(n / 2.5))), 2)
    ys = np.linspace(y0 + 0.6, y1 - 0.6, lanes)
    pts = []
    for i, y in enumerate(ys):
        xs = np.linspace(x0 + 0.6, x1 - 0.6, max(n // lanes, 2))
        if i % 2:
            xs = xs[::-1]
        for x in xs:
            pts.append((x, y))
    pts = np.array(pts)
    pts += rng.normal(0, 0.05, pts.shape)
    return pts


def build_world(cfg: WorldConfig, rng: np.random.Generator) -> List[RobotTruth]:
    """Generate ground-truth and dead-reckoned trajectories for every robot."""
    n_steps = int(cfg.session_s / cfg.dt)
    W, H = cfg.area
    N = cfg.n_robots

    # Overlapping vertical partitions: 15% overlap on each interior boundary.
    edges = np.linspace(0, W, N + 1)
    truths = []
    for rid in range(N):
        lo, hi = edges[rid], edges[rid + 1]
        pad = 0.15 * (hi - lo)
        lo = max(0.0, lo - pad)
        hi = min(W, hi + pad)

        way = _boustrophedon(lo, hi, 0.0, H, n_steps, rng)
        # Resample the waypoint polyline at constant speed.
        seg = np.linalg.norm(np.diff(way, axis=0), axis=1)
        s = np.concatenate([[0], np.cumsum(seg)])
        total = s[-1]
        want = np.minimum(np.arange(n_steps) * cfg.speed * cfg.dt, total)
        px = np.interp(want, s, way[:, 0])
        py = np.interp(want, s, way[:, 1])
        head = np.arctan2(np.gradient(py), np.gradient(px))

        gt = np.stack([px, py, head], axis=1)
        step = np.concatenate([[0.0], np.linalg.norm(np.diff(gt[:, :2], axis=0), axis=1)])
        dist = np.cumsum(step)

        # Dead reckoning: accumulate per-step error scaled by distance travelled.
        odom = np.zeros_like(gt)
        odom[0] = gt[0]
        ex = ey = eth = 0.0
        for k in range(1, n_steps):
            d = step[k]
            if cfg.drift_model == "random_walk":
                sc = cfg.drift_rate * np.sqrt(max(d, 1e-9))
            else:
                sc = cfg.drift_rate * d
            ex += rng.normal(0, sc)
            ey += rng.normal(0, sc)
            eth += rng.normal(0, cfg.heading_drift * d)
            odom[k, 0] = gt[k, 0] + ex
            odom[k, 1] = gt[k, 1] + ey
            odom[k, 2] = wrap(gt[k, 2] + eth)

        truths.append(RobotTruth(rid=rid, gt=gt, odom=odom,
                                 t=np.arange(n_steps) * cfg.dt, dist=dist))
    return truths


def relative(a, b):
    """Relative SE(2) transform of b expressed in the frame of a."""
    c, s = np.cos(a[2]), np.sin(a[2])
    d = b[:2] - a[:2]
    return np.array([c * d[0] + s * d[1],
                     -s * d[0] + c * d[1],
                     wrap(b[2] - a[2])])


def generate_candidates(truths: List[RobotTruth], cfg: WorldConfig,
                        rng: np.random.Generator) -> Dict[int, List[Constraint]]:
    """
    Produce candidate inter-robot constraints.

    A candidate exists whenever two robots occupy nearby ground-truth positions
    at any pair of times, i.e. one has entered territory the other observed.
    A configurable fraction are outliers with an injected displacement, standing
    in for wrong data association; these are what the geometric term of theta
    must reject.
    """
    N = len(truths)
    out = {r.rid: [] for r in truths}
    if N < 2:
        return out

    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            Pi = truths[i].gt[:, :2]
            Pj = truths[j].gt[:, :2]
            # Coarse spatial gate via broadcasting, subsampled for tractability.
            stride = max(len(Pj) // 220, 1)
            jdx = np.arange(0, len(Pj), stride)
            d = np.linalg.norm(Pi[:, None, :] - Pj[None, jdx, :], axis=2)
            ii, jj = np.where(d < cfg.obs_radius)
            for a, b in zip(ii, jj):
                if rng.random() > cfg.obs_prob:
                    continue
                bj = int(jdx[b])
                z = relative(truths[i].gt[a], truths[j].gt[bj])
                z = z + np.array([rng.normal(0, cfg.meas_sigma_xy),
                                  rng.normal(0, cfg.meas_sigma_xy),
                                  rng.normal(0, cfg.meas_sigma_theta)])
                bad = rng.random() < cfg.outlier_rate
                if bad:
                    ang = rng.uniform(0, 2 * np.pi)
                    z[0] += cfg.outlier_offset * np.cos(ang)
                    z[1] += cfg.outlier_offset * np.sin(ang)
                    z[2] = wrap(z[2] + rng.normal(0, 0.4))
                payload = (cfg.payload_base_bytes + cfg.payload_descriptor_bytes
                           + int(rng.integers(0, max(cfg.payload_jitter_bytes, 1))))
                out[i].append(Constraint(
                    rid_from=i, rid_to=j, idx_from=int(a), idx_to=bj,
                    z=z, t_created=float(truths[i].t[a]),
                    payload_bytes=int(payload), is_outlier=bool(bad)))
    for rid in out:
        out[rid].sort(key=lambda c: c.t_created)
    return out
