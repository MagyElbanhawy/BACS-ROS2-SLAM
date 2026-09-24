#!/usr/bin/env python3
"""Regenerate the simulation results with bacs_sim, then rebuild the S8 statistics.

    python scripts/reproduce_simulation.py              # full run (S7-C, S9, progression + S8 30 seeds)
    python scripts/reproduce_simulation.py --skip-s8    # everything except the expensive S8 run
    python scripts/reproduce_simulation.py --analysis-only   # statistics from existing/frozen CSVs

Simulator outputs go to paper_results/*.csv (written by scripts/generate_paper_results.py
and scripts/run_s8_30seed.py). Frozen copies used by the manuscript are kept in
paper_results/simulation/frozen/ and are never overwritten; scripts/update_report.py
compares against the manuscript whichever is used.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.simulation.s8 import run as s8_analysis  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-s8", action="store_true")
    parser.add_argument("--analysis-only", action="store_true")
    args = parser.parse_args()
    if not args.analysis_only:
        runner = ROOT / "scripts" / "generate_paper_results.py"
        if not (ROOT / "bacs_sim").is_dir() or not runner.exists():
            raise SystemExit("bacs_sim/ and scripts/generate_paper_results.py are required (see simulation/README.md).")
        subprocess.run([sys.executable, str(runner), *(["--skip-s8"] if args.skip_s8 else [])], check=True, cwd=ROOT)
    _, _, source = s8_analysis(ROOT)
    print(f"S8 statistics written to paper_results/simulation/ (source: {source}).")


if __name__ == "__main__":
    main()
