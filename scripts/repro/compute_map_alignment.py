#!/usr/bin/env python3
"""Compute per-run Vicon-referenced map-alignment RMSE and policy statistics.

    python scripts/repro/compute_map_alignment.py \
        --poses 'paper_results/physical/fused/fused_*.csv' \
        --segmentation paper_results/physical/run_segmentation.csv \
        --out paper_results/physical

Writes map_alignment_per_run.csv, map_alignment_summary.csv and
map_alignment_statistics.csv. See analysis/physical/map_alignment.py for the
metric definition.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analysis.physical.map_alignment import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--poses", nargs="+", required=True, help="fused pose CSVs or glob patterns")
    parser.add_argument("--segmentation", type=Path, default=ROOT / "paper_results/physical/run_segmentation.csv")
    parser.add_argument("--out", type=Path, default=ROOT / "paper_results/physical")
    parser.add_argument("--radius", type=float, default=0.5, help="Vicon co-location radius in metres")
    parser.add_argument("--min-pairs", type=int, default=20, help="co-location samples required per run")
    args = parser.parse_args()
    paths = sorted({Path(p) for pattern in args.poses for p in glob.glob(pattern)})
    if not paths:
        raise SystemExit("No pose files matched.")
    run(paths, args.segmentation, args.out, args.radius, args.min_pairs)
    print(f"Wrote map_alignment_*.csv to {args.out}")


if __name__ == "__main__":
    main()
