#!/usr/bin/env python3
"""Sanity-check logged fused poses against Vicon before computing any RMSE.

For each session and robot, over non-overlapping windows of ``--window`` seconds:

* speed of the fused estimate and of Vicon (median and 95th percentile);
* for moving windows, the angle between the displacement direction and the
  heading (yaw). A differential-drive robot moves along +/-heading, so large
  angles in Vicon mean a frame/convention problem in the ground truth or a
  non-differential drive; large angles only in the estimate mean the fused
  map/base_link convention is wrong.
* the fused-vs-Vicon speed ratio (should be close to 1 if localisation tracks).

    python scripts/repro/check_fused_poses.py paper_results/physical/fused/fused_*.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import math
from collections import defaultdict

import numpy as np


def load(paths: list[str]) -> dict[tuple[str, str], dict[str, np.ndarray]]:
    rows: dict[tuple[str, str], list[list[float]]] = defaultdict(list)
    for path in paths:
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                rows[(row["session"], row["robot"])].append([
                    int(row["stamp_ns"]) / 1e9, float(row["est_x"]), float(row["est_y"]), float(row["est_yaw"]),
                    float(row["vicon_x"]), float(row["vicon_y"]), float(row["vicon_yaw"])])
    out = {}
    for key, values in rows.items():
        a = np.array(sorted(values))
        out[key] = {"t": a[:, 0], "est": a[:, 1:4], "vicon": a[:, 4:7]}
    return out


def window_stats(t: np.ndarray, pose: np.ndarray, window_s: float, moving_mps: float) -> dict[str, float]:
    edges = np.searchsorted(t, np.arange(t[0], t[-1], window_s))
    speeds, angles = [], []
    for i, j in zip(edges[:-1], edges[1:]):
        if j - i < 2:
            continue
        j -= 1
        dt = t[j] - t[i]
        dx, dy = pose[j, 0] - pose[i, 0], pose[j, 1] - pose[i, 1]
        speed = math.hypot(dx, dy) / dt
        speeds.append(speed)
        if speed >= moving_mps:
            heading = math.atan2(math.sin(pose[i, 2]) + math.sin(pose[j, 2]), math.cos(pose[i, 2]) + math.cos(pose[j, 2]))
            error = abs(math.atan2(math.sin(math.atan2(dy, dx) - heading), math.cos(math.atan2(dy, dx) - heading)))
            angles.append(min(error, math.pi - error))  # forward or reverse motion both count as aligned
    speeds_a, angles_a = np.array(speeds), np.degrees(np.array(angles))
    return {"median_speed": float(np.median(speeds_a)) if speeds else math.nan,
            "p95_speed": float(np.percentile(speeds_a, 95)) if speeds else math.nan,
            "moving_windows": len(angles),
            "aligned_fraction": float(np.mean(angles_a < 15.0)) if angles else math.nan,
            "median_heading_error_deg": float(np.median(angles_a)) if angles else math.nan}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("poses", nargs="+", help="fused pose CSV files or glob patterns")
    parser.add_argument("--window", type=float, default=1.0, help="window length in seconds")
    parser.add_argument("--moving", type=float, default=0.05, help="minimum speed (m/s) to test heading alignment")
    parser.add_argument("--min-aligned", type=float, default=0.8, help="aligned fraction required to pass")
    args = parser.parse_args()
    paths = sorted({p for pattern in args.poses for p in glob.glob(pattern)})
    if not paths:
        raise SystemExit("No pose files matched.")
    failed = False
    header = f"{'session':<16}{'robot':<8}{'source':<7}{'med v':>8}{'p95 v':>8}{'moving':>8}{'aligned':>9}{'med err':>9}"
    print(header); print("-" * len(header))
    for (session, robot), data in sorted(load(paths).items()):
        stats = {src: window_stats(data["t"], data[src], args.window, args.moving) for src in ("est", "vicon")}
        for src in ("est", "vicon"):
            s = stats[src]
            print(f"{session:<16}{robot:<8}{src:<7}{s['median_speed']:>8.3f}{s['p95_speed']:>8.3f}"
                  f"{s['moving_windows']:>8d}{s['aligned_fraction']:>9.2f}{s['median_heading_error_deg']:>9.1f}")
        ratio = stats["est"]["median_speed"] / stats["vicon"]["median_speed"] if stats["vicon"]["median_speed"] else math.nan
        problems = []
        if not 0.8 <= ratio <= 1.25:
            problems.append(f"fused/Vicon speed ratio {ratio:.2f}")
        for src in ("vicon", "est"):
            if stats[src]["aligned_fraction"] < args.min_aligned:
                problems.append(f"{src} motion not along heading ({stats[src]['aligned_fraction']:.0%} aligned)")
        print(f"  -> {'FAIL: ' + '; '.join(problems) if problems else 'PASS'}")
        failed |= bool(problems)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
