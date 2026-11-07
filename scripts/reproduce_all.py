#!/usr/bin/env python3
"""Execute the reproducibility pipeline in evidence-preserving order."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
for script in ("reproduce_physical.py", "reproduce_statistics.py --input paper_results/physical/timing_per_run.csv --output paper_results/physical/physical_statistics.csv", "reproduce_simulation.py", "generate_figures.py", "update_report.py"):
    subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True)
