"""Inter-robot constraint candidates from keyframe scan matching (ROS-free core).

Flow on robot i:
1. every keyframe period, store (scan points, local pose) and publish its compact
   descriptor on the Wi-Fi side channel;
2. match each NEW own keyframe against the other robots' stored descriptors (so
   each keyframe pair is examined once, by the robot that created the later one);
3. for a place-recognition match, request that remote keyframe's points;
4. when they arrive, run ICP; an accepted result becomes a candidate for
   ``/bacs/candidates``: pose of kf_j (robot j) in kf_i's frame (robot i).

Trust and information are sensor-derived surrogates, defined in
docs/HARDWARE_EXPERIMENT_V2.md §3. No ground truth is used anywhere.
"""

from __future__ import annotations

import base64
import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import IO, Any, Callable

import numpy as np

from .place_recognition import Descriptor, compare, describe, icp

ATTEMPT_FIELDS = ["t_ns", "robot_i", "kf_i", "robot_j", "kf_j", "stage", "place_distance",
                  "init_yaw", "inlier_ratio", "rmse", "converged", "dx", "dy", "dtheta", "accepted", "reason", "seq"]


@dataclass
class GeneratorParams:
    sectors: int = 60
    max_range: float = 10.0
    shortlist: int = 3                    # remote keyframes verified by ICP per new keyframe
    place_threshold: float = 0.12         # only shortlist descriptors closer than this
    min_inlier_ratio: float = 0.8         # ICP acceptance (see docs/HARDWARE_EXPERIMENT_V2.md §3)
    max_rmse: float = 0.05                # metres
    min_points: int = 60
    trust_rmse_ref: float = 0.05          # trust = inlier_ratio * exp(-rmse / trust_rmse_ref)
    info_sigma_ref: float = 0.05          # info = 1 / (1 + sqrt(trace(Sigma_xy)) / info_sigma_ref)


def encode_points(points: np.ndarray) -> str:
    return base64.b64encode(points.astype(np.float16).tobytes()).decode("ascii")


def decode_points(text: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(text), dtype=np.float16).astype(float).reshape(-1, 2)


@dataclass
class Keyframe:
    robot: str
    kf: int
    stamp_ns: int
    descriptor: Descriptor
    points: np.ndarray | None = None      # own keyframes and fetched remote ones only


@dataclass
class CandidateGenerator:
    robot: str
    clock_ns: Callable[[], int]
    params: GeneratorParams = field(default_factory=GeneratorParams)
    attempts_log: IO[str] | None = None

    def __post_init__(self) -> None:
        self.own: dict[int, Keyframe] = {}
        self.remote: dict[tuple[str, int], Keyframe] = {}
        self.pending: dict[tuple[str, int], list[int]] = defaultdict(list)   # remote kf -> own kfs waiting for it
        self.pair_counts: dict[str, int] = defaultdict(int)
        self.next_seq = 0
        self.writer = None
        if self.attempts_log is not None:
            self.writer = csv.DictWriter(self.attempts_log, fieldnames=ATTEMPT_FIELDS, lineterminator="\n")
            self.writer.writeheader()

    # --- own keyframes -------------------------------------------------------------------------
    def add_own_keyframe(self, kf: int, stamp_ns: int, points: np.ndarray) -> tuple[dict, list[dict], list[dict]]:
        """Store a keyframe; return (descriptor message, point requests, candidates).

        Candidates are returned immediately for matches whose remote points were
        already fetched; the rest arrive later through :meth:`add_remote_points`.
        """
        descriptor = describe(points, self.params.sectors, self.params.max_range)
        self.own[kf] = Keyframe(self.robot, kf, stamp_ns, descriptor, points)
        requests, ready = [], []
        if len(points) >= self.params.min_points:
            for key, distance, yaw in self._shortlist(descriptor):
                row = {"robot_i": self.robot, "kf_i": kf, "robot_j": key[0], "kf_j": key[1], "stage": "place",
                       "place_distance": distance, "init_yaw": yaw}
                self.pending[key].append(kf)
                if self.remote[key].points is not None:
                    ready.append(key)
                elif len(self.pending[key]) == 1:
                    requests.append({"from": self.robot, "robot": key[0], "kf": key[1]})
                self._log(row, accepted=True, reason="shortlisted")
        message = {"robot": self.robot, "kf": kf, "stamp_ns": stamp_ns, **descriptor.pack()}
        candidates = [c for key in ready for c in self.match_pending(key)]
        return message, requests, candidates

    def points_message(self, kf: int) -> dict | None:
        frame = self.own.get(kf)
        return None if frame is None else {"robot": self.robot, "kf": kf, "points": encode_points(frame.points)}

    # --- remote keyframes ------------------------------------------------------------------------
    def add_remote_descriptor(self, message: dict) -> None:
        if message["robot"] == self.robot:
            return
        key = (message["robot"], int(message["kf"]))
        self.remote.setdefault(key, Keyframe(key[0], key[1], int(message["stamp_ns"]), Descriptor.unpack(message)))

    def add_remote_points(self, message: dict) -> list[dict]:
        """Store fetched points and run ICP for every own keyframe waiting on them."""
        key = (message["robot"], int(message["kf"]))
        if key not in self.remote:
            return []
        self.remote[key].points = decode_points(message["points"])
        return self.match_pending(key)

    def match_pending(self, key: tuple[str, int]) -> list[dict]:
        remote = self.remote[key]
        if remote.points is None:
            return []
        candidates = []
        for kf in self.pending.pop(key, []):
            candidate = self._register(self.own[kf], remote)
            if candidate:
                candidates.append(candidate)
        return candidates

    # --- internals -------------------------------------------------------------------------------
    def _shortlist(self, descriptor: Descriptor) -> list[tuple[tuple[str, int], float, float]]:
        scored = sorted(((key, *compare(frame.descriptor, descriptor)) for key, frame in self.remote.items()),
                        key=lambda item: item[1])
        return [item for item in scored[:self.params.shortlist] if item[1] < self.params.place_threshold]

    def _register(self, own: Keyframe, remote: Keyframe) -> dict | None:
        _, yaw = compare(remote.descriptor, own.descriptor)
        result = icp(remote.points, own.points, init=(0.0, 0.0, yaw))
        row = {"robot_i": self.robot, "kf_i": own.kf, "robot_j": remote.robot, "kf_j": remote.kf, "stage": "icp",
               "init_yaw": yaw, "inlier_ratio": result.inlier_ratio, "rmse": result.rmse,
               "converged": result.converged, "dx": result.x, "dy": result.y, "dtheta": result.theta}
        cov = result.covariance
        if not result.converged:
            return self._log(row, accepted=False, reason="not_converged")
        if result.inlier_ratio < self.params.min_inlier_ratio:
            return self._log(row, accepted=False, reason="inlier_ratio")
        if result.rmse > self.params.max_rmse:
            return self._log(row, accepted=False, reason="rmse")
        if not np.all(np.isfinite(cov)):
            return self._log(row, accepted=False, reason="degenerate")
        seq = self.next_seq; self.next_seq += 1
        pair = remote.robot
        trust = result.inlier_ratio * math.exp(-result.rmse / self.params.trust_rmse_ref)
        info = 1.0 / (1.0 + math.sqrt(cov[0, 0] + cov[1, 1]) / self.params.info_sigma_ref)
        candidate = {"seq": seq, "robot_i": self.robot, "robot_j": remote.robot, "kf_i": own.kf, "kf_j": remote.kf,
                     "t_gen_ns": self.clock_ns(), "predicted_trust": trust, "information_score": info,
                     "pair_constraints": self.pair_counts[pair], "dx": result.x, "dy": result.y,
                     "dtheta": result.theta, "var_x": float(cov[0, 0]), "var_y": float(cov[1, 1]),
                     "var_theta": float(cov[2, 2])}
        self.pair_counts[pair] += 1
        self._log(row, accepted=True, reason="candidate", seq=seq)
        return candidate

    def _log(self, row: dict[str, Any], accepted: bool, reason: str, seq: int | str = "") -> None:
        if self.writer is not None:
            self.writer.writerow({"t_ns": self.clock_ns(), **row, "accepted": int(accepted), "reason": reason,
                                  "seq": seq})
            self.attempts_log.flush()
        return None
