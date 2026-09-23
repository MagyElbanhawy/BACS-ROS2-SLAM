#!/usr/bin/env python3
"""Validate immutable physical evidence and create derived inventories."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.physical.pipeline import validate_all

if __name__ == "__main__":
    validate_all(ROOT)
    print("Hardware validation completed; see hardware/validation/.")
