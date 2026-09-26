#!/usr/bin/env python3
"""Revision v3, Task 4: temporal-decay rule comparison (S9) with 30 seeds.

    python scripts/revision/run_decay.py [--workers 4]

The five rules of bacs_sim.experiments.S9_RULES (fixed 0.003, drift derived, drift
adaptive, deferral derived, deferral adaptive) with the bacs_gated scheduler, 720 s
sessions, seeds 10-39, N = 2, 3, 4, 5, all rules on the same precomputed world per
(seed, N). This is the frozen S9 set-up (paper_results/simulation/frozen/
s9_deferral_gamma.csv: seeds 0-4, N = 2) with more seeds and team sizes. The script
first re-runs the frozen configuration and records whether it reproduces.

Outputs in paper_results/revision/decay/: raw.csv, frozen_check.csv, summary.csv,
paired_tests.csv, fig_decay.png, runtime.txt.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bacs_sim.experiments import S9_RULES, _sweep, s9_configs, s9_deferral_gamma  # noqa: E402
from stats import describe, holm, paired  # noqa: E402

OUT = ROOT / "paper_results" / "revision" / "decay"
FROZEN = ROOT / "paper_results" / "simulation" / "frozen" / "s9_deferral_gamma.csv"
RULES = [name for name, _ in S9_RULES]
REFERENCE = "deferral derived"
SEEDS, COUNTS = range(10, 40), (2, 3, 4, 5)
METRICS = {"pose_rmse": "Pose RMSE (m)", "align_rmse": "Map-alignment RMSE (m)"}
# N is ordinal: one blue ramp, light -> dark (reference palette steps 250/400/550/700).
N_COLORS = {2: "#86b6ef", 3: "#3987e5", 4: "#1c5cab", 5: "#0d366b"}


def cell(args):
    seed, n = args
    recs = _sweep(s9_configs(), [seed], n_robots=n, label_fn=lambda c: dict(rule=c.__dict__.get("_name")))
    for r in recs:
        r["n_robots"] = n
    return recs


def frozen_check() -> pd.DataFrame:
    new = s9_deferral_gamma(seeds=range(5)).set_index("rule")
    old = pd.read_csv(FROZEN).set_index("rule")
    rows = []
    for rule in RULES:
        for col in ("pose_rmse_mean", "align_rmse_mean", "n_delivered_mean", "gamma_mean"):
            rows.append({"rule": rule, "column": col, "frozen": old.loc[rule, col], "rerun": new.loc[rule, col],
                         "abs_diff": abs(old.loc[rule, col] - new.loc[rule, col])})
    return pd.DataFrame(rows)


def summarise(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for n in COUNTS:
        for rule in RULES:
            g = raw[(raw.n_robots == n) & (raw.rule == rule)]
            row = {"n_robots": n, "rule": rule}
            for metric in ("pose_rmse", "align_rmse", "gamma", "n_delivered"):
                for k, v in describe(g[metric]).items():
                    row[f"{metric}_{k}"] = v
            rows.append(row)
    return pd.DataFrame(rows)


def tests(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for metric in METRICS:
        for n in COUNTS:
            d = raw[raw.n_robots == n].pivot(index="seed", columns="rule", values=metric)
            for rule in RULES:
                if rule != REFERENCE:
                    rows.append({"metric": metric, "n_robots": n, "rule": REFERENCE, "versus": rule,
                                 **paired(d[REFERENCE].to_numpy(), d[rule].to_numpy())})
    out = pd.DataFrame(rows).rename(columns={"mean_a": "mean_deferral_derived", "mean_b": "mean_other",
                                             "seeds_won": "seeds_deferral_derived_lower",
                                             "seeds_lost": "seeds_other_lower"})
    # Holm family: the 4 rules x 4 team sizes for one metric.
    out["p_holm"] = np.nan
    for _, idx in out.groupby("metric").groups.items():
        out.loc[idx, "p_holm"] = holm(out.loc[idx, "wilcoxon_p_two_sided"])
    return out


def figure(summary: pd.DataFrame, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4), dpi=150, sharey=False)
    width = 0.8 / len(COUNTS)
    for ax, (metric, label) in zip(axes, METRICS.items()):
        for i, n in enumerate(COUNTS):
            r = summary[summary.n_robots == n].set_index("rule").loc[RULES]
            x = np.arange(len(RULES)) + (i - (len(COUNTS) - 1) / 2) * width
            mean = r[f"{metric}_mean"]
            ax.bar(x, mean, width * 0.92, color=N_COLORS[n], edgecolor="white", linewidth=0.8, label=f"N = {n}", zorder=2)
            ax.errorbar(x, mean, yerr=[mean - r[f"{metric}_ci95_lo"], r[f"{metric}_ci95_hi"] - mean], fmt="none",
                        ecolor="#52514e", elinewidth=1.0, capsize=2, zorder=3)
        ax.set_xticks(np.arange(len(RULES)), [r.replace(" ", "\n") for r in RULES], fontsize=9)
        ax.set_ylabel(label)
        ax.set_title(f"{label}: mean and 95% CI, 30 seeds", loc="left", fontsize=10)
        ax.grid(axis="y", color="#e2e2e0", zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.set_ylim(0, None)
    axes[0].legend(ncol=4, fontsize=8, frameon=False, loc="upper left")
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
    check = frozen_check()
    check.to_csv(OUT / "frozen_check.csv", index=False, lineterminator="\n")
    print(check.to_string(index=False))
    if args.analysis_only:
        raw = pd.read_csv(OUT / "raw.csv")
    else:
        cells = [(s, n) for n in COUNTS for s in SEEDS]
        recs = []

        with ProcessPoolExecutor(args.workers) as pool:
            futures = {pool.submit(cell, c): c for c in cells}

            for i, future in enumerate(as_completed(futures), 1):
                c = futures[future]
                chunk = future.result()
                recs.extend(chunk)

                raw_checkpoint = pd.DataFrame(recs)[
                    ["n_robots", "seed", "rule", "pose_rmse",
                     "align_rmse", "gamma", "n_delivered",
                     "trust_yield", "airtime_util", "dt_bias"]
                ]

                raw_checkpoint.to_csv(
                    OUT / "raw_partial.csv",
                    index=False,
                    lineterminator="\n",
                )

                elapsed = time.time() - t0
                avg = elapsed / i
                remaining = avg * (len(cells) - i)

                print(
                    f"[{i}/{len(cells)}] "
                    f"seed={c[0]} N={c[1]} | "
                    f"{100*i/len(cells):.1f}% | "
                    f"ETA {remaining/60:.1f} min",
                    flush=True,
                )

        raw = pd.DataFrame(recs)[
            ["n_robots", "seed", "rule", "pose_rmse",
             "align_rmse", "gamma", "n_delivered",
             "trust_yield", "airtime_util", "dt_bias"]
        ]
        # as_completed returns cells in completion order; restore the
        # deterministic (N, seed, rule) order so raw.csv is reproducible.
        raw["_r"] = raw["rule"].map({r: i for i, r in enumerate(RULES)})
        raw = raw.sort_values(["n_robots", "seed", "_r"]).drop(columns="_r").reset_index(drop=True)

        raw.to_csv(
            OUT / "raw.csv",
            index=False,
            lineterminator="\n",
        )
        (OUT / "runtime.txt").write_text(f"wall time {time.time() - t0:.1f} s with {args.workers} workers, "
                                         f"{len(raw)} runs (plus the 25-run frozen check)\n", encoding="utf-8")
    summary = summarise(raw)
    summary.to_csv(OUT / "summary.csv", index=False, lineterminator="\n")
    tests(raw).to_csv(OUT / "paired_tests.csv", index=False, lineterminator="\n")
    figure(summary, OUT / "fig_decay.png")
    print(f"done in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
