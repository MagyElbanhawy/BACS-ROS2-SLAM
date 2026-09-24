"""2-D LiDAR place recognition (range profile) and point-to-point ICP.

Used only on sensor data: scans and the robot's own local pose. Never on Vicon.

Descriptor: the median range in each of ``sectors`` bearing bins, normalised by
``max_range`` (empty bins = max range), packed as uint8 (60 bytes by default).
Two descriptors are compared over every circular shift; the best shift gives the
mean absolute difference (distance) and an initial yaw. In a small room this
only shortlists candidates -- ICP geometry decides (see candidate_generator.py).
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree


def scan_to_points(ranges: list[float] | np.ndarray, angle_min: float, angle_increment: float,
                   range_min: float, range_max: float) -> np.ndarray:
    r = np.asarray(ranges, dtype=float)
    angles = angle_min + angle_increment * np.arange(len(r))
    valid = np.isfinite(r) & (r >= range_min) & (r <= range_max)
    return np.column_stack((r[valid] * np.cos(angles[valid]), r[valid] * np.sin(angles[valid])))


@dataclass
class Descriptor:
    profile: np.ndarray         # (sectors,) in [0, 1]
    max_range: float

    def pack(self) -> dict:
        data = np.round(self.profile * 255).astype(np.uint8).tobytes()
        return {"sectors": len(self.profile), "max_range": self.max_range,
                "profile": base64.b64encode(data).decode("ascii")}

    @classmethod
    def unpack(cls, message: dict) -> "Descriptor":
        profile = np.frombuffer(base64.b64decode(message["profile"]), dtype=np.uint8).astype(float) / 255
        return cls(profile[:int(message["sectors"])], float(message["max_range"]))


def describe(points: np.ndarray, sectors: int = 60, max_range: float = 10.0) -> Descriptor:
    profile = np.ones(sectors)
    if len(points):
        r = np.hypot(points[:, 0], points[:, 1])
        sector = ((np.arctan2(points[:, 1], points[:, 0]) % (2 * math.pi)) / (2 * math.pi) * sectors).astype(int) % sectors
        for k in np.unique(sector):
            profile[k] = min(float(np.median(r[sector == k])), max_range) / max_range
    return Descriptor(profile, max_range)


def compare(query: Descriptor, reference: Descriptor) -> tuple[float, float]:
    """Return (distance, yaw): yaw is the rotation of ``query``'s frame relative to ``reference``'s."""
    sectors = len(reference.profile)
    shifted = np.stack([np.roll(query.profile, k) for k in range(sectors)])
    distances = np.abs(shifted - reference.profile).mean(axis=1)
    k = int(np.argmin(distances))
    return float(distances[k]), k * 2 * math.pi / sectors


@dataclass
class IcpResult:
    x: float
    y: float
    theta: float
    covariance: np.ndarray      # 3x3, (x, y, theta)
    inlier_ratio: float
    rmse: float
    iterations: int
    converged: bool


def _transform(points: np.ndarray, x: float, y: float, theta: float) -> np.ndarray:
    c, s = math.cos(theta), math.sin(theta)
    return points @ np.array([[c, s], [-s, c]]) + (x, y)


def icp(source: np.ndarray, target: np.ndarray, init: tuple[float, float, float] = (0.0, 0.0, 0.0),
        max_iterations: int = 40, max_distances: tuple[float, ...] = (1.0, 0.5, 0.25),
        inlier_distance: float = 0.15, tolerance: float = 1e-5) -> IcpResult:
    """Find the pose (x, y, theta) of ``source``'s frame in ``target``'s frame."""
    tree = cKDTree(target)
    x, y, theta = init
    iterations, converged = 0, False
    for max_distance in max_distances:
        for _ in range(max_iterations):
            iterations += 1
            moved = _transform(source, x, y, theta)
            distance, index = tree.query(moved, distance_upper_bound=max_distance)
            ok = np.isfinite(distance)
            if ok.sum() < 10:
                break
            p, q = moved[ok], target[index[ok]]
            mp, mq = p.mean(axis=0), q.mean(axis=0)
            h = (p - mp).T @ (q - mq)
            d_theta = math.atan2(h[0, 1] - h[1, 0], h[0, 0] + h[1, 1])
            c, s = math.cos(d_theta), math.sin(d_theta)
            d_t = mq - mp @ np.array([[c, s], [-s, c]])
            # compose the increment with the current estimate
            x, y = (np.array([x, y]) @ np.array([[c, s], [-s, c]]) + d_t)
            theta = math.atan2(math.sin(theta + d_theta), math.cos(theta + d_theta))
            if abs(d_theta) < tolerance and np.hypot(*d_t) < tolerance:
                converged = True
                break
    moved = _transform(source, x, y, theta)
    distance, index = tree.query(moved, distance_upper_bound=inlier_distance)
    inliers = np.isfinite(distance)
    n = int(inliers.sum())
    rmse = float(np.sqrt(np.mean(distance[inliers] ** 2))) if n else math.inf
    covariance = np.full((3, 3), np.inf)
    if n >= 3:
        rotated = moved[inliers] - (x, y)
        jac = np.zeros((2 * n, 3))
        jac[0::2, 0] = 1; jac[1::2, 1] = 1
        jac[0::2, 2] = -rotated[:, 1]; jac[1::2, 2] = rotated[:, 0]
        info = jac.T @ jac
        if np.linalg.cond(info) < 1e12:
            covariance = max(rmse, 0.01) ** 2 * np.linalg.inv(info)
    return IcpResult(float(x), float(y), float(theta), covariance, n / len(source) if len(source) else 0.0,
                     rmse, iterations, converged)
