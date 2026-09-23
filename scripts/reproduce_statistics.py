#!/usr/bin/env python3
"""Produce only statistics supported by genuine run-level observations."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.physical.pipeline import write_csv
from analysis.statistics.metrics import cliffs_delta, paired_wilcoxon


def main() -> None:
    path = ROOT / "paper_results" / "physical" / "timing_per_run.csv"
    if not path.exists():
        raise SystemExit("Run scripts/reproduce_physical.py first.")
    by_policy: dict[str, dict[str, float]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            by_policy.setdefault(row["policy"], {})[row["run"]] = float(row["deferral_mean_s"])
    fifo, plus = by_policy["FIFO"], by_policy["BACS+"]
    runs = sorted(set(fifo) & set(plus), key=int)
    left, right = [fifo[x] for x in runs], [plus[x] for x in runs]
    test = paired_wilcoxon(left, right)
    rows = [
        {"metric": "map_alignment_rmse_m", "comparison": "FIFO vs BACS+",
         "n_pairs": 0, "wilcoxon_statistic": "", "p_value": "", "cliffs_delta": "",
         "status": "NOT_COMPUTABLE", "reason": "No fused-map estimate or estimated trajectory is present."},
        {"metric": "mean_scheduler_deferral_s", "comparison": "FIFO vs BACS+",
         "n_pairs": len(runs), "wilcoxon_statistic": test["statistic"], "p_value": test["p_value"],
         "cliffs_delta": cliffs_delta(left, right), "status": "COMPUTED",
         "reason": "Paired by logged run identifier; interpretation is limited to scheduler deferral."},
    ]
    write_csv(ROOT / "paper_results" / "physical" / "physical_statistics.csv", list(rows[0]), rows)


if __name__ == "__main__":
    main()
