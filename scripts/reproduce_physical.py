#!/usr/bin/env python3
"""Recompute physical timing, radio, and evidence-limited map outputs."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.physical.pipeline import physical_analysis, validate_all

if __name__ == "__main__":
    validate_all(ROOT)
    physical_analysis(ROOT)
    print("Physical reproduction completed; non-recorded metrics remain explicit.")
