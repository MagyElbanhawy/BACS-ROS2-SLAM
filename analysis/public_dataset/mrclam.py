from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

BARCODE_COLUMNS = ["subject", "barcode"]
GROUNDTRUTH_COLUMNS = ["time_s", "x", "y", "theta"]
MEASUREMENT_COLUMNS = ["time_s", "barcode", "range_m", "bearing_rad"]


@dataclass(frozen=True)
class DatasetCandidate:
    dataset: str
    session: str
    robot_i: str
    robot_j: str
    payload: dict
    translation_error_m: float


@dataclass(frozen=True)
class PoseSample:
    time_s: float
    x: float
    y: float
    theta: float


class MrclamDatasetError(RuntimeError):
    pass


def _read_table(path: Path, columns: list[str]) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"MRCLAM replay needs {path.name} under {path.parent}.")
    return pd.read_csv(path, sep=r"\s+", comment="#", names=columns, header=None, engine="python")


def _nearest_pose(track: pd.DataFrame, time_s: float) -> PoseSample:
    if track.empty:
        raise MrclamDatasetError("MRCLAM replay needs non-empty ground-truth tracks for every robot.")
    idx = (track["time_s"] - time_s).abs().idxmin()
    row = track.loc[idx]
    return PoseSample(float(row.time_s), float(row.x), float(row.y), float(row.theta))


def _relative_pose(origin: PoseSample, target: PoseSample) -> tuple[float, float, float]:
    dx, dy = target.x - origin.x, target.y - origin.y
    c, s = math.cos(origin.theta), math.sin(origin.theta)
    x_rel = c * dx + s * dy
    y_rel = -s * dx + c * dy
    yaw_rel = math.atan2(math.sin(target.theta - origin.theta), math.cos(target.theta - origin.theta))
    return x_rel, y_rel, yaw_rel


def _candidate_payload(*, seq: int, robot_i: str, robot_j: str, time_s: float, dx: float, dy: float,
                       dtheta: float, predicted_trust: float, information_score: float,
                       pair_constraints: int) -> dict:
    sigma_xy = 0.05 + 0.02 * math.hypot(dx, dy)
    sigma_theta = 0.05 + 0.02 * abs(dtheta)
    return {
        "seq": seq,
        "robot_i": robot_i,
        "robot_j": robot_j,
        "kf_i": seq,
        "kf_j": seq,
        "t_gen_ns": int(time_s * 1e9),
        "predicted_trust": predicted_trust,
        "information_score": information_score,
        "pair_constraints": pair_constraints,
        "dx": dx,
        "dy": dy,
        "dtheta": dtheta,
        "var_x": sigma_xy ** 2,
        "var_y": sigma_xy ** 2,
        "var_theta": sigma_theta ** 2,
    }


def load_mrclam_candidates(root: Path, *, robot_ids: tuple[int, int] = (1, 2),
                           max_range_m: float = 5.0) -> list[DatasetCandidate]:
    """Build replay candidates from robot-to-robot range/bearing observations.

    The adapter is intentionally offline-only: ``root`` must already contain an
    extracted public MRCLAM session.
    """
    if len(robot_ids) != 2:
        raise ValueError("MRCLAM replay currently supports exactly two robots per run.")
    barcodes = _read_table(root / "Barcodes.dat", BARCODE_COLUMNS)
    barcode_to_subject = {int(r.barcode): int(r.subject) for r in barcodes.itertuples(index=False)}
    robot_names = {rid: f"robot{rid}" for rid in robot_ids}
    pair_counts = {(robot_names[robot_ids[0]], robot_names[robot_ids[1]]): 0,
                   (robot_names[robot_ids[1]], robot_names[robot_ids[0]]): 0}
    tracks = {rid: _read_table(root / f"Robot{rid}_Groundtruth.dat", GROUNDTRUTH_COLUMNS) for rid in robot_ids}
    measurements = {rid: _read_table(root / f"Robot{rid}_Measurement.dat", MEASUREMENT_COLUMNS) for rid in robot_ids}
    session = root.name
    seq = 0
    out: list[DatasetCandidate] = []
    for rid in robot_ids:
        robot_i = robot_names[rid]
        for row in measurements[rid].itertuples(index=False):
            subject = barcode_to_subject.get(int(row.barcode))
            if subject not in robot_ids or subject == rid or float(row.range_m) > max_range_m:
                continue
            robot_j = robot_names[int(subject)]
            pair_key = (robot_i, robot_j)
            own_pose = _nearest_pose(tracks[rid], float(row.time_s))
            other_pose = _nearest_pose(tracks[int(subject)], float(row.time_s))
            dx_true, dy_true, dtheta_true = _relative_pose(own_pose, other_pose)
            dx_meas = float(row.range_m) * math.cos(float(row.bearing_rad))
            dy_meas = float(row.range_m) * math.sin(float(row.bearing_rad))
            trust = max(0.01, math.exp(-float(row.range_m) / 6.0) * math.exp(-abs(float(row.bearing_rad)) / 1.5))
            info = 1.0 / (1.0 + float(row.range_m) + 0.5 * abs(float(row.bearing_rad)))
            payload = _candidate_payload(seq=seq, robot_i=robot_i, robot_j=robot_j, time_s=float(row.time_s),
                                         dx=dx_meas, dy=dy_meas, dtheta=dtheta_true,
                                         predicted_trust=trust, information_score=info,
                                         pair_constraints=pair_counts[pair_key])
            pair_counts[pair_key] += 1
            out.append(DatasetCandidate(dataset="MRCLAM", session=session, robot_i=robot_i, robot_j=robot_j,
                                        payload=payload,
                                        translation_error_m=math.hypot(dx_meas - dx_true, dy_meas - dy_true)))
            seq += 1
    if not out:
        raise MrclamDatasetError(
            f"No inter-robot MRCLAM observations were found under {root}. Check the extracted session files."
        )
    return sorted(out, key=lambda c: (c.payload["t_gen_ns"], c.payload["seq"]))
