#!/usr/bin/env python3
"""Write paper_results/physical/hardware_metrics.csv (Table 6) from measured sessions.

    python scripts/parse_hardware_logs.py

Run after scripts/join_radio_logs.py (one joined log per session) and
scripts/repro/compute_map_alignment.py. Definitions: analysis/physical/hardware_metrics.py
and docs/METRIC_DEFINITIONS.md. Values are whatever the logs give; nothing is scaled to
match the manuscript -- scripts/update_report.py does the comparison.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.physical.hardware_metrics import hardware_metrics  # noqa: E402
from analysis.physical.pipeline import duty_cycle  # noqa: E402


def main() -> None:
    out = ROOT / "paper_results" / "physical" / "hardware_metrics.csv"
    rows = hardware_metrics(ROOT / "hardware" / "raw", ROOT / "paper_results" / "physical" / "map_alignment_per_run.csv",
                            out, duty_cycle(ROOT))
    for row in rows:
        print(f"{row['session']:<16} {row['status']}")
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
