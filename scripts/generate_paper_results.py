#!/usr/bin/env python3
"""Regenerate the frozen simulation result tables used by the paper.

The S8 30-seed run is intentionally explicit because it is substantially more
expensive than the other table generators.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "paper_results")
sys.path.insert(0, ROOT)

from bacs_sim import experiments


def write(name: str, frame: pd.DataFrame) -> None:
    path = os.path.join(RESULTS, name)
    frame.to_csv(path, index=False)
    print(f"-> {os.path.relpath(path, ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screening-seeds", type=int, default=5)
    parser.add_argument("--s7c-seeds", type=int, default=10)
    parser.add_argument("--s8-lo", type=int, default=10)
    parser.add_argument("--s8-hi", type=int, default=40)
    parser.add_argument("--skip-s8", action="store_true")
    args = parser.parse_args()
    os.makedirs(RESULTS, exist_ok=True)

    write("progression.csv", experiments.progression(seeds=range(args.screening_seeds)))
    write(
        "s7c_incremental_validation.csv",
        experiments.s7c_incremental_validation(seeds=range(args.screening_seeds)),
    )
    write(
        "s7c_paired.csv",
        experiments.s7c_paired(seeds=range(args.s7c_seeds)),
    )
    write(
        "s9_deferral_gamma.csv",
        experiments.s9_deferral_gamma(seeds=range(args.screening_seeds)),
    )

    if not args.skip_s8:
        script = os.path.join(os.path.dirname(__file__), "run_s8_30seed.py")
        subprocess.run(
            [sys.executable, script, "--lo", str(args.s8_lo), "--hi", str(args.s8_hi)],
            check=True,
        )


if __name__ == "__main__":
    main()
