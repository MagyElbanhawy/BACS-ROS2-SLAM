#!/usr/bin/env python3
"""Run deterministic S7-C/S8/S9-style simulated policy comparisons."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simulation.run import write_outputs

if __name__ == "__main__":
    write_outputs(ROOT)
    print("Simulation outputs written under paper_results/simulation/.")
