#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analysis.public_dataset import ReplayConfig, load_mrclam_candidates, replay_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a public multi-robot dataset through FIFO/BACS/BACS+.")
    parser.add_argument("dataset_path", type=Path, help="Local path to an extracted public dataset session")
    parser.add_argument("--dataset", default="mrclam", choices=["mrclam"])
    parser.add_argument("--out", type=Path, default=Path("paper_results/public_dataset"))
    args = parser.parse_args()
    if args.dataset != "mrclam":
        raise SystemExit(f"Unsupported dataset adapter: {args.dataset}")
    candidates = load_mrclam_candidates(args.dataset_path)
    replay_dataset(candidates, args.out, ReplayConfig())


if __name__ == "__main__":
    main()
