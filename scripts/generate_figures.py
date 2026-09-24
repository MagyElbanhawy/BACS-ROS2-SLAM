#!/usr/bin/env python3
"""Generate figures solely from result CSVs."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    out = ROOT / "figures" / "extract"; out.mkdir(parents=True, exist_ok=True)
    with (ROOT / "paper_results" / "physical" / "timing_per_packet.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    policies = sorted({x["policy"] for x in rows})
    plt.figure(figsize=(7, 4))
    plt.boxplot([[float(x["deferral_s"]) for x in rows if x["policy"] == policy] for policy in policies], tick_labels=policies)
    plt.ylabel("Scheduler deferral (s)"); plt.tight_layout(); plt.savefig(out / "physical_timing_distributions.png", dpi=200); plt.close()
    with (ROOT / "paper_results" / "physical" / "radio_summary.csv").open(newline="", encoding="utf-8") as handle:
        radio = [r for r in csv.DictReader(handle) if r["metric"] in {"rssi_dbm_mean", "snr_db_mean", "airtime_fraction_of_duty_budget"}]
    plt.figure(figsize=(8, 4))
    labels = [f"{r['policy']}\n{r['metric']}" for r in radio]
    plt.bar(range(len(radio)), [float(r["median"]) for r in radio])
    plt.xticks(range(len(radio)), labels, rotation=45, ha="right"); plt.tight_layout()
    plt.savefig(out / "physical_radio_airtime.png", dpi=200); plt.close()
    simulation_figures(out)


# Categorical slots in fixed order (validated: CVD dE >= 9, normal-vision dE >= 22); contrast is
# below 3:1 for slots 3-4, so every series also has its own marker shape and a legend.
ARM_STYLE = {"fifo": ("#2a78d6", "o"), "bacs_gated": ("#eb6834", "s"),
             "plus_0.30_6": ("#1baf7a", "D"), "plus_0.60_5": ("#eda100", "^")}
INK, MUTED = "#1f1f1e", "#6b6a64"


def _axes(ax, ylabel: str) -> None:
    ax.set_xlabel("Robots (N)", color=INK); ax.set_ylabel(ylabel, color=INK)
    ax.grid(axis="y", color="#e4e3dd", linewidth=0.8); ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.tick_params(colors=MUTED)


def simulation_figures(out: Path) -> None:
    sys.path.insert(0, str(ROOT))
    import pandas as pd
    from analysis.simulation.s8 import ARMS, LABELS
    summary_path = ROOT / "paper_results" / "simulation" / "s8_summary.csv"
    if not summary_path.exists():
        print("No S8 statistics; run scripts/reproduce_simulation.py first.")
        return
    summary = pd.read_csv(summary_path)
    source = (ROOT / "paper_results" / "simulation" / "s8_source.txt").read_text(encoding="utf-8").split(":")[0]
    counts = sorted(summary.n_robots.unique())
    for metric, ylabel, name in (("align_rmse", "Map-alignment RMSE (m)", "sim_s8_alignment.png"),
                                 ("pose_rmse", "Per-step pose RMSE (m)", "sim_s8_pose.png"),
                                 ("n_delivered", "Delivered constraints", "sim_s8_delivered.png")):
        fig, ax = plt.subplots(figsize=(7, 4))
        for k, arm in enumerate(ARMS):
            rows = summary[(summary.arm == arm) & (summary.metric == metric)].sort_values("n_robots")
            x = rows.n_robots + (k - 1.5) * 0.12
            color, marker = ARM_STYLE[arm]
            ax.errorbar(x, rows["mean"], yerr=[rows["mean"] - rows.ci_lo, rows.ci_hi - rows["mean"]], fmt=marker,
                        color=color, markersize=6, elinewidth=1.5, capsize=0, label=LABELS[arm])
        ax.set_xticks(counts); _axes(ax, ylabel)
        ax.set_title(f"{ylabel}: mean and 95% CI, 30 seeds ({source})", color=INK, fontsize=10, loc="left")
        ax.legend(frameon=False, fontsize=8, ncol=2)
        fig.tight_layout(); fig.savefig(out / name, dpi=200); plt.close(fig)

    path = ROOT / "paper_results" / "simulation" / "frozen" / "s8_30seed_raw.csv"
    fresh = ROOT / "paper_results" / "s8_30seed_raw.csv"
    raw = pd.read_csv(fresh if fresh.exists() else path)
    wide = raw.pivot_table(index=["n_robots", "seed"], columns="arm", values="align_rmse").reset_index()
    for arms, reference, name, ylabel in (
            (["bacs_gated", "plus_0.30_6", "plus_0.60_5"], "fifo", "sim_s8_paired_reduction.png",
             "FIFO RMSE − policy RMSE (m)"),
            (["plus_0.60_5"], "plus_0.30_6", "sim_s8_observability_ablation.png",
             "BACS+ (0.30, 6) RMSE − BACS+ (0.60, 5) RMSE (m)")):
        fig, ax = plt.subplots(figsize=(7, 4))
        rng = np.random.default_rng(0)
        labels = []
        for k, arm in enumerate(arms):
            color, marker = ARM_STYLE[arm]
            offset = (k - (len(arms) - 1) / 2) * 0.22
            for n in counts:
                sub = wide[wide.n_robots == n]
                diff = (sub[reference] - sub[arm]).to_numpy()
                ax.scatter(n + offset + rng.uniform(-0.05, 0.05, len(diff)), diff, s=14, color=color, marker=marker,
                           linewidths=0, label=LABELS[arm] if n == counts[0] else None)
                labels.append((n + offset, f"{int((diff > 0).sum())}/{len(diff)}"))
        top = ax.get_ylim()[1]
        for x, text in labels:
            ax.annotate(text, (x, top), ha="center", va="bottom", fontsize=7, color=MUTED, annotation_clip=False)
        ax.axhline(0, color=MUTED, linestyle="--", linewidth=1)
        ax.set_xticks(counts); _axes(ax, ylabel)
        ax.set_title(f"Per-seed paired difference; above 0 = better than {LABELS[reference]} ({source})",
                     color=INK, fontsize=10, loc="left", pad=16)
        ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncol=3)
        fig.tight_layout(); fig.savefig(out / name, dpi=200); plt.close(fig)

if __name__ == "__main__":
    main()

