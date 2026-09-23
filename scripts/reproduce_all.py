#!/usr/bin/env python3
"""Execute the reproducibility pipeline in evidence-preserving order."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
for script in ("reproduce_physical.py", "reproduce_statistics.py", "reproduce_simulation.py", "generate_figures.py", "update_report.py"):
    subprocess.run([sys.executable, str(ROOT / "scripts" / script)], check=True)
