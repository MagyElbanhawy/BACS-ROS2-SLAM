#!/usr/bin/env python3
"""Revision v3, Task 2: extra scheduling baselines under the frozen S8 protocol.

    python scripts/revision/run_baselines.py [--workers 4]

Protocol (identical to paper_results/simulation/frozen/s8_30seed_raw.csv): held-out
seeds 10-39, N = 2, 3, 4, 5, 480 s sessions, deferral-derived gamma on every arm, all
arms on the same precomputed world per (seed, N). The fifo, bacs_gated and plus_0.30_6
rows are first checked against the frozen table; if any differs the script writes
frozen_check.csv and stops without computing statistics.

Outputs in paper_results/revision/baselines/: raw.csv, frozen_check.csv, summary.csv,
paired_tests.csv, fig_baselines.png, runtime.txt.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bacs_sim.experiments import s8_seed  # noqa: E402
from stats import describe, holm, paired  # noqa: E402

OUT = ROOT / "paper_results" / "revision" / "baselines"
FROZEN = ROOT / "paper_results" / "simulation" / "frozen" / "s8_30seed_raw.csv"
ARMS = ["fifo", "lifo", "random", "trust_only", "info_only", "bacs_gated", "plus_0.30_6"]
FROZEN_ARMS = ["fifo", "bacs_gated", "plus_0.30_6"]
REFERENCES = ["fifo", "plus_0.30_6"]
SEEDS, COUNTS, SESSION_S = range(10, 40), (2, 3, 4, 5), 480.0
METRICS = ["align_rmse", "pose_rmse", "n_delivered"]
TOL = 1e-12  # float round-off; n_delivered must match exactly
LABELS = {"fifo": "FIFO", "lifo": "LIFO", "random": "Random", "trust_only": "Trust-only",
          "info_only": "Info-only", "bacs_gated": "BACS", "plus_0.30_6": "BACS+ (0.30, 6)"}
# FIFO / BACS / BACS+ keep the colours of figures/extract/sim_s8_*.png; the new
# baselines take the next reference-palette slots (yellow is skipped: it is
# BACS+ (0.60, 5) in the existing figures) and carry a hatch as secondary encoding.
COLORS = {"fifo": "#2a78d6", "lifo": "#e87ba4", "random": "#008300", "trust_only": "#e34948",
          "info_only": "#4a3aa7", "bacs_gated": "#eb6834", "plus_0.30_6": "#1baf7a"}
HATCH = {"lifo": "\\\\\\", "random": "...", "trust_only": "///", "info_only": "xxx"}


def cell(args):
    seed, n = args
    return s8_seed(seed, n, ARMS, SESSION_S)


def frozen_check(raw: pd.DataFrame) -> pd.DataFrame:
    frozen = pd.read_csv(FROZEN)
    frozen = frozen[frozen.arm.isin(FROZEN_ARMS)]
    m = frozen.merge(raw, on=["n_robots", "seed", "arm"], suffixes=("_frozen", "_new"), how="left")
    rows = []
    for arm in FROZEN_ARMS:
        a = m[m.arm == arm]
        for metric in ("align_rmse", "pose_rmse", "trust_yield", "n_delivered"):
            diff = np.abs(a[f"{metric}_new"].to_numpy(float) - a[f"{metric}_frozen"].to_numpy(float))
            tol = 0 if metric == "n_delivered" else TOL
            rows.append({"arm": arm, "metric": metric, "rows": len(a), "max_abs_diff": float(np.nanmax(diff)),
                         "rows_outside_tolerance": int(np.sum(~(diff <= tol))), "tolerance": tol})
    return pd.DataFrame(rows)


def summarise(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (n, arm), g in raw.groupby(["n_robots", "arm"], sort=False):
        for metric in METRICS:
            rows.append({"n_robots": n, "policy": arm, "metric": metric, **describe(g[metric])})
    out = pd.DataFrame(rows)
    out["policy"] = pd.Categorical(out.policy, ARMS, ordered=True)
    return out.sort_values(["metric", "n_robots", "policy"]).reset_index(drop=True)


def tests(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in ("align_rmse", "pose_rmse"):
        for ref in REFERENCES:
            for n in COUNTS:
                d = raw[raw.n_robots == n].pivot(index="seed", columns="arm", values=metric)
                for arm in ARMS:
                    if arm == ref:
                        continue
                    rows.append({"metric": metric, "reference": ref, "n_robots": n, "policy": arm,
                                 **paired(d[arm].to_numpy(), d[ref].to_numpy())})
    out = pd.DataFrame(rows)
    # Holm family: every (policy, N) test for one metric against one reference.
    out["holm_family"] = out.metric + " vs " + out.reference
    out["p_holm"] = np.nan
    for _, idx in out.groupby("holm_family").groups.items():
        out.loc[idx, "p_holm"] = holm(out.loc[idx, "wilcoxon_p_two_sided"])
    return out


def figure(summary: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = summary[summary.metric == "align_rmse"]
    fig, ax = plt.subplots(figsize=(9.5, 4.6), dpi=150)
    width = 0.8 / len(ARMS)
    for i, arm in enumerate(ARMS):
        r = s[s.policy == arm].sort_values("n_robots")
        x = np.arange(len(COUNTS)) + (i - (len(ARMS) - 1) / 2) * width
        ax.bar(x, r["mean"], width * 0.92, color=COLORS[arm], hatch=HATCH.get(arm), edgecolor="white",
               linewidth=0.8, label=LABELS[arm], zorder=2)
        ax.errorbar(x, r["mean"], yerr=[r["mean"] - r["ci95_lo"], r["ci95_hi"] - r["mean"]], fmt="none",
                    ecolor="#52514e", elinewidth=1.0, capsize=2, zorder=3)
    ax.set_xticks(np.arange(len(COUNTS)), [str(n) for n in COUNTS])
    ax.set_xlabel("Robots (N)")
    ax.set_ylabel("Map-alignment RMSE (m)")
    ax.set_title("Map-alignment RMSE (m): mean and 95% CI, 30 seeds (S8 protocol)", loc="left", fontsize=11)
    ax.grid(axis="y", color="#e2e2e0", zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(ncol=4, fontsize=8, frameon=False, loc="upper right")
    ax.set_ylim(0, None)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--analysis-only", action="store_true", help="reuse raw.csv")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if args.analysis_only:
        raw = pd.read_csv(OUT / "raw.csv")
    else:
        cells = [(s, n) for n in COUNTS for s in SEEDS]
        with ProcessPoolExecutor(args.workers) as pool:
            recs = [r for chunk in pool.map(cell, cells) for r in chunk]
        raw = pd.DataFrame(recs)[["n_robots", "seed", "arm", "align_rmse", "pose_rmse", "n_delivered", "trust_yield"]]
        raw.to_csv(OUT / "raw.csv", index=False, lineterminator="\n")
        (OUT / "runtime.txt").write_text(f"simulation wall time {time.time() - t0:.1f} s with {args.workers} workers, "
                                         f"{len(raw)} runs\n", encoding="utf-8")
    check = frozen_check(raw)
    check.to_csv(OUT / "frozen_check.csv", index=False, lineterminator="\n")
    print(check.to_string(index=False))
    if check.rows_outside_tolerance.sum():
        print("STOP: fifo/bacs_gated/plus_0.30_6 do not reproduce the frozen S8 table.")
        return 1
    summary = summarise(raw)
    summary.to_csv(OUT / "summary.csv", index=False, lineterminator="\n")
    t = tests(raw)
    t.to_csv(OUT / "paired_tests.csv", index=False, lineterminator="\n")
    figure(summary, OUT / "fig_baselines.png")
    print(f"done in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
