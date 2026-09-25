#!/usr/bin/env python3
"""Physical map-alignment RMSE from fused-pose CSVs (CLI for analysis/physical/map_alignment.py).

    python scripts/repro/compute_map_alignment.py --poses 'paper_results/physical/fused/fused_*.csv' \
        --segmentation paper_results/physical/run_segmentation.csv --out paper_results/physical

All statistics (Cliff's delta, paired/unpaired tests, one- and two-sided p) are
computed from the data by analysis/physical/map_alignment.py. No fused-pose CSVs
exist for HWS-002/003/005: the bags do not contain fused poses, so this step
currently has no input. The former synthetic script lives in
synthetic_test_fixtures/scripts/compute_map_alignment_synthetic.py.
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from analysis.physical.map_alignment import run  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--poses", required=True, help="glob of fused_<session>.csv files")
    parser.add_argument("--segmentation", default=str(ROOT / "paper_results" / "physical" / "run_segmentation.csv"))
    parser.add_argument("--out", default=str(ROOT / "paper_results" / "physical"))
    parser.add_argument("--radius", type=float, default=0.5)
    args = parser.parse_args()
    paths = [Path(p) for p in sorted(glob.glob(args.poses))]
    if not paths:
        sys.exit(f"no fused-pose CSVs match {args.poses!r}; physical map alignment is not computable")
    run(paths, Path(args.segmentation), Path(args.out), radius_m=args.radius)


if __name__ == "__main__":
    main()
