#!/usr/bin/env python3
"""Join one hardware session's robot and server radio logs into a scheduler log.

    python scripts/join_radio_logs.py ~/bacs_hw_logs/HWS-101-BACS+ \
        hardware/raw/HWS-101-BACS+/bacs_scheduler_log_HWS-101-BACS+_BACS+.csv

Prints per-run counts (candidates, sent, received, unmatched/duplicate/undecodable
receptions) so losses are visible, not silently dropped.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.physical.radio_join import join_session


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    reports = join_session(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]))
    for report in reports:
        print(", ".join(f"{k}={v}" for k, v in report.items()))


if __name__ == "__main__":
    main()
