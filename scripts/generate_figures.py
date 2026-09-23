#!/usr/bin/env python3
"""Generate figures solely from result CSVs."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    out = ROOT / "figures" / "generated"; out.mkdir(parents=True, exist_ok=True)
    with (ROOT / "paper_results" / "physical" / "timing_per_packet.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    policies = sorted({x["policy"] for x in rows})
    plt.figure(figsize=(7, 4))
    plt.boxplot([[float(x["deferral_s"]) for x in rows if x["policy"] == policy] for policy in policies], tick_labels=policies)
    plt.ylabel("Scheduler deferral (s)"); plt.tight_layout(); plt.savefig(out / "physical_timing_distributions.png", dpi=200); plt.close()
    with (ROOT / "paper_results" / "physical" / "radio_summary.csv").open(newline="", encoding="utf-8") as handle:
        radio = [r for r in csv.DictReader(handle) if r["metric"] in {"rssi_dbm_mean", "snr_db_mean", "airtime_utilisation"}]
    plt.figure(figsize=(8, 4))
    labels = [f"{r['policy']}\n{r['metric']}" for r in radio]
    plt.bar(range(len(radio)), [float(r["median"]) for r in radio])
    plt.xticks(range(len(radio)), labels, rotation=45, ha="right"); plt.tight_layout()
    plt.savefig(out / "physical_radio_airtime.png", dpi=200); plt.close()
    with (ROOT / "paper_results" / "simulation" / "summary" / "simulation_summary.csv").open(newline="", encoding="utf-8") as handle:
        sim = list(csv.DictReader(handle))
    plt.figure(figsize=(7, 4))
    for policy in ("FIFO", "BACS", "BACS+"):
        subset = [x for x in sim if x["policy"] == policy and x["temporal_decay"] == "True"]
        plt.plot([int(x["robots"]) for x in subset], [float(x["mean_information"]) for x in subset], marker="o", label=policy)
    plt.xlabel("Robots"); plt.ylabel("Mean selected information"); plt.legend(); plt.tight_layout()
    plt.savefig(out / "simulation_s8.png", dpi=200); plt.close()
    for source, name, title in (("s7c_incremental_information.csv", "simulation_s7c.png", "S7-C selected information"),
                                ("s9_temporal_decay.csv", "simulation_s9.png", "S9 temporal decay"),
                                ("ablations.csv", "simulation_ablations.png", "Ablation selected information")):
        with (ROOT / "paper_results" / "simulation" / "raw" / source).open(newline="", encoding="utf-8") as handle:
            records = list(csv.DictReader(handle))
        grouped: dict[str, list[float]] = {}
        for record in records:
            grouped.setdefault(record["policy"], []).append(float(record["mean_information"]))
        plt.figure(figsize=(6, 4))
        plt.bar(grouped.keys(), [sum(values) / len(values) for values in grouped.values()])
        plt.ylabel("Mean selected information"); plt.title(title); plt.tight_layout()
        plt.savefig(out / name, dpi=200); plt.close()


if __name__ == "__main__":
    main()
