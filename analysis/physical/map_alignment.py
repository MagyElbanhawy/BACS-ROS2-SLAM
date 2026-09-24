"""Vicon-referenced inter-robot map-alignment RMSE from logged fused poses.

Metric (per run): take the samples at which both robots have a fused pose and a
Vicon pose. The inter-robot vectors ``d_est = p1_est - p2_est`` and
``d_vic = p1_vic - p2_vic`` are translation-free, so the map origin does not
matter. One rotation ``R`` (map -> Vicon) is fitted per session on all samples
(2-D Kabsch, no scale, no translation). The map-alignment RMSE is
``sqrt(mean ||R d_est - d_vic||^2)`` over the co-location samples, i.e. those
where the robots are within ``radius_m`` of each other in Vicon. A perfectly
merged map gives zero regardless of per-robot drift that both maps share.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

POLICY_ORDER = ["FIFO", "BACS", "BACS+"]


def policy_of(session: str) -> str:
    """``HWS-002-FIFO`` -> ``FIFO``; ``HWS-005-BACS+`` -> ``BACS+``."""
    return session.split("-", 2)[2]


def load_fused(paths: list[Path]) -> dict[str, dict[str, np.ndarray]]:
    """Return per-session arrays of synchronised two-robot samples.

    Keys: ``t`` (ns), ``est1``, ``est2``, ``vic1``, ``vic2`` (N x 2). Robots are
    ordered by name, so robot 1 is ``limo01``.
    """
    ticks: dict[str, dict[int, dict[str, tuple[float, float, float, float]]]] = defaultdict(lambda: defaultdict(dict))
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                ticks[row["session"]][int(row["stamp_ns"])][row["robot"]] = (
                    float(row["est_x"]), float(row["est_y"]), float(row["vicon_x"]), float(row["vicon_y"]))
    sessions = {}
    for session, by_tick in ticks.items():
        robots = sorted({r for sample in by_tick.values() for r in sample})
        if len(robots) != 2:
            raise ValueError(f"{session}: expected exactly two robots, found {robots}")
        rows = [(t, s[robots[0]], s[robots[1]]) for t, s in sorted(by_tick.items()) if len(s) == 2]
        if not rows:
            continue
        a = np.array([[t, *r1, *r2] for t, r1, r2 in rows], dtype=float)
        sessions[session] = {"t": a[:, 0].astype(np.int64), "est1": a[:, 1:3], "vic1": a[:, 3:5],
                             "est2": a[:, 5:7], "vic2": a[:, 7:9], "robots": robots}
    return sessions


def fit_rotation(source: np.ndarray, target: np.ndarray) -> float:
    """Angle of the rotation R minimising sum ||R s - t||^2 (2-D Kabsch)."""
    cross = np.sum(source[:, 0] * target[:, 1] - source[:, 1] * target[:, 0])
    dot = np.sum(source[:, 0] * target[:, 0] + source[:, 1] * target[:, 1])
    return math.atan2(cross, dot)


def rotate(vectors: np.ndarray, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return vectors @ np.array([[c, s], [-s, c]])


def read_segmentation(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [{"policy": r["policy"], "run": int(r["run"]), "start": int(r["start_timestamp"]),
                 "end": int(r["end_timestamp"])} for r in csv.DictReader(handle)]


def per_run_rmse(sessions: dict[str, dict[str, np.ndarray]], segmentation: list[dict[str, Any]],
                 radius_m: float = 0.5, min_pairs: int = 20) -> list[dict[str, Any]]:
    rows = []
    by_policy = {policy_of(s): s for s in sessions}
    for seg in sorted(segmentation, key=lambda r: (POLICY_ORDER.index(r["policy"]) if r["policy"] in POLICY_ORDER else 99, r["run"])):
        base = {"policy": seg["policy"], "run": seg["run"], "radius_m": radius_m}
        session = by_policy.get(seg["policy"])
        if session is None:
            rows.append({**base, "status": "NO_FUSED_POSES"}); continue
        data = sessions[session]
        d_est_all, d_vic_all = data["est1"] - data["est2"], data["vic1"] - data["vic2"]
        angle = fit_rotation(d_est_all, d_vic_all)
        mask = (data["t"] >= seg["start"]) & (data["t"] <= seg["end"])
        d_est, d_vic = rotate(d_est_all[mask], angle), d_vic_all[mask]
        coloc = np.linalg.norm(d_vic, axis=1) <= radius_m
        residual_all = np.linalg.norm(d_est - d_vic, axis=1)
        n_pairs = int(coloc.sum())
        rmse = float(np.sqrt(np.mean(residual_all[coloc] ** 2))) if n_pairs else math.nan
        rows.append({**base, "session": session, "samples": int(mask.sum()), "colocation_pairs": n_pairs,
                     "map_alignment_rmse_m": rmse,
                     "relative_rmse_all_samples_m": float(np.sqrt(np.mean(residual_all ** 2))) if mask.any() else math.nan,
                     "fitted_rotation_deg": math.degrees(angle),
                     "status": "COMPUTED" if n_pairs >= min_pairs else "INSUFFICIENT_COLOCATION"})
    return rows


def summarise(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for policy in POLICY_ORDER:
        values = np.array([r["map_alignment_rmse_m"] for r in rows if r["policy"] == policy and r["status"] == "COMPUTED"])
        if not len(values):
            out.append({"policy": policy, "n_runs": 0, "status": "NOT_COMPUTABLE"}); continue
        sd = float(values.std(ddof=1)) if len(values) > 1 else 0.0
        half = float(stats.t.ppf(0.975, len(values) - 1) * sd / math.sqrt(len(values))) if len(values) > 1 else math.nan
        out.append({"policy": policy, "n_runs": len(values), "mean_m": float(values.mean()), "std_m": sd,
                    "ci95_low_m": float(values.mean()) - half, "ci95_high_m": float(values.mean()) + half,
                    "median_m": float(np.median(values)), "p25_m": float(np.percentile(values, 25)),
                    "p75_m": float(np.percentile(values, 75)), "status": "COMPUTED"})
    return out


def cliffs_delta(candidate: np.ndarray, reference: np.ndarray) -> float:
    diff = candidate[:, None] - reference[None, :]
    return float((np.sum(diff > 0) - np.sum(diff < 0)) / diff.size)


def compare(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pairwise tests; ``reference`` is the earlier policy in POLICY_ORDER.

    The paired test matches runs by run index across sessions recorded on
    different days, so its validity rests on that pairing; the unpaired
    Mann-Whitney test does not. Report both.
    """
    values = {p: {r["run"]: r["map_alignment_rmse_m"] for r in rows if r["policy"] == p and r["status"] == "COMPUTED"}
              for p in POLICY_ORDER}
    out = []
    for reference, candidate in combinations(POLICY_ORDER, 2):
        ref, cand = values[reference], values[candidate]
        base = {"metric": "map_alignment_rmse_m", "reference": reference, "candidate": candidate}
        if len(ref) < 2 or len(cand) < 2:
            out.append({**base, "status": "NOT_COMPUTABLE"}); continue
        ref_a, cand_a = np.array(list(ref.values())), np.array(list(cand.values()))
        runs = sorted(set(ref) & set(cand))
        paired_ref, paired_cand = np.array([ref[r] for r in runs]), np.array([cand[r] for r in runs])
        row = {**base, "n_reference": len(ref_a), "n_candidate": len(cand_a), "n_pairs": len(runs),
               "mean_reference_m": float(ref_a.mean()), "mean_candidate_m": float(cand_a.mean()),
               "relative_change_of_means": float((cand_a.mean() - ref_a.mean()) / ref_a.mean()),
               "cliffs_delta": cliffs_delta(cand_a, ref_a)}
        if len(runs) >= 2 and np.any(paired_cand - paired_ref):
            row["pairs_candidate_lower"] = int(np.sum(paired_cand < paired_ref))
            row["wilcoxon_paired_p_two_sided"] = float(stats.wilcoxon(paired_cand, paired_ref, alternative="two-sided").pvalue)
            row["wilcoxon_paired_p_one_sided_less"] = float(stats.wilcoxon(paired_cand, paired_ref, alternative="less").pvalue)
        row["mannwhitney_p_two_sided"] = float(stats.mannwhitneyu(cand_a, ref_a, alternative="two-sided").pvalue)
        row["mannwhitney_p_one_sided_less"] = float(stats.mannwhitneyu(cand_a, ref_a, alternative="less").pvalue)
        row["pairing"] = "run index across sessions recorded on different days"
        row["status"] = "COMPUTED"
        out.append(row)
    return out


def write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        fields += [k for k in row if k not in fields]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n"); writer.writeheader(); writer.writerows(rows)


def run(pose_paths: list[Path], segmentation: Path, out: Path, radius_m: float = 0.5, min_pairs: int = 20) -> None:
    per_run = per_run_rmse(load_fused(pose_paths), read_segmentation(segmentation), radius_m, min_pairs)
    write_rows(out / "map_alignment_per_run.csv", per_run)
    write_rows(out / "map_alignment_summary.csv", summarise(per_run))
    write_rows(out / "map_alignment_statistics.csv", compare(per_run))
