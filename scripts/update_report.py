#!/usr/bin/env python3
"""Render the reviewer report from generated CSV outputs, never embedded results."""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def value(records: list[dict[str, str]], policy: str, metric: str, column: str = "median") -> str:
    found = next((r for r in records if r["policy"] == policy and r["metric"] == metric), None)
    return f"{float(found[column]):.6g}" if found and found[column] else "N/A"


def main() -> None:
    timing = rows(ROOT / "paper_results" / "physical" / "timing_summary.csv")
    radio = rows(ROOT / "paper_results" / "physical" / "radio_summary.csv")
    report = f"""# Reproducibility report

All recomputed values below are rendered from generated CSVs by `scripts/update_report.py`; no paper result constants are embedded in analysis code. The supplied evidence validates physical N=2 only.

| Metric | Paper value | Recomputed value | Difference | Status | Source data | Analysis script |
|---|---:|---:|---:|---|---|---|
| FIFO map-alignment RMSE | Not encoded | N/A | N/A | NOT_COMPUTABLE | No fused map or estimated trajectory supplied | `scripts/reproduce_physical.py` |
| BACS map-alignment RMSE | Not encoded | N/A | N/A | NOT_COMPUTABLE | No fused map or estimated trajectory supplied | `scripts/reproduce_physical.py` |
| BACS+ map-alignment RMSE | Not encoded | N/A | N/A | NOT_COMPUTABLE | No fused map or estimated trajectory supplied | `scripts/reproduce_physical.py` |
| BACS+ improvement versus FIFO | Not encoded | N/A | N/A | NOT_COMPUTABLE | Map RMSE unavailable | `scripts/reproduce_statistics.py` |
| Map-RMSE Wilcoxon and Cliff's delta | Not encoded | N/A | N/A | NOT_COMPUTABLE | Map RMSE unavailable | `scripts/reproduce_statistics.py` |
| BACS+ median scheduling deferral (s) | N/A | {value(timing, "BACS+", "deferral_s")} | N/A | COMPUTED | Scheduler log | `scripts/reproduce_physical.py` |
| BACS+ median channel delay (s) | N/A | N/A | N/A | NOT_COMPUTABLE | `t_tx_ns`/`t_rx_ns` are not recorded | `scripts/reproduce_physical.py` |
| Deferral/channel ratio | N/A | N/A | N/A | NOT_COMPUTABLE | Channel delay not recorded | `scripts/reproduce_physical.py` |
| BACS+ median RSSI (dBm) | N/A | {value(radio, "BACS+", "rssi_dbm_mean")} | N/A | COMPUTED | Scheduler log | `scripts/reproduce_physical.py` |
| BACS+ median SNR (dB) | N/A | {value(radio, "BACS+", "snr_db_mean")} | N/A | COMPUTED | Scheduler log | `scripts/reproduce_physical.py` |
| BACS+ median airtime utilisation | N/A | {value(radio, "BACS+", "airtime_utilisation")} | N/A | COMPUTED | Scheduler log and configured LoRa parameters | `scripts/reproduce_physical.py` |

Generated/transmitted constraints are in `paper_results/physical/timing_per_run.csv`; full timing and radio distributions are in their corresponding summary files. DB3/MCAP message counts match, while stream hashes and timestamps differ; every comparison is retained in `hardware/validation/db3_mcap_equivalence.csv`.
"""
    (ROOT / "REPRODUCIBILITY_REPORT.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
