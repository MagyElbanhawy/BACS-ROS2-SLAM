#!/usr/bin/env python3
"""Ranking v2 analysis: summaries, paired tests, mechanism, stress trend, figures, REPORT.md.

    python scripts/revision/ranking_v2_analysis.py

Reads paper_results/revision/ranking_v2_c0c3/{decision.md, conditions.json, pilot_tdefer*.csv,
dev_raw.csv, C*/test_raw.csv, C*/tx_log_test_C*.csv} and writes the per-condition tables,
stress_trend.csv, fig_*.png and REPORT.md (narrative from ranking_v2_report_template.md).
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as st

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from stats import describe, holm, paired  # noqa: E402

OUT = ROOT / "paper_results" / "revision" / "ranking_v2_c0c3"
CONDS = ["C0", "C1", "C2", "C3"]
COUNTS = [2, 3, 4, 5]
POLICIES = ["fifo", "lifo", "random", "trust_only", "info_only", "bacs_gated", "plus_0.30_6",
            "tw_now", "tw_arrival", "tw_arrival_sub"]
LABEL = {"fifo": "FIFO", "lifo": "LIFO", "random": "Random", "trust_only": "Trust-only", "info_only": "Info-only",
         "bacs_gated": "BACS", "plus_0.30_6": "BACS+ (0.30, 6)", "tw_now": "TW-now", "tw_arrival": "TW-arrival",
         "tw_arrival_sub": "TW-arrival-sub"}
COLORS = {"fifo": "#2a78d6", "lifo": "#e87ba4", "random": "#008300", "trust_only": "#e34948",
          "info_only": "#4a3aa7", "bacs_gated": "#eb6834", "plus_0.30_6": "#1baf7a",
          "tw_now": "#eda100", "tw_arrival": "#eda100", "tw_arrival_sub": "#eda100"}
HATCH = {"lifo": "\\\\\\", "random": "...", "trust_only": "///", "info_only": "xxx", "tw_now": "---",
         "tw_arrival_sub": "+++"}
RAMP = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]  # blue 250/400/550/700: N or condition
METRICS = ["align_rmse", "pose_rmse", "trust_yield", "n_delivered", "airtime_util", "median_age_tx",
           "median_age_arrival", "mean_R"]


def _ensure_test_raw(cond: str) -> str:
    """Make sure <cond>/test_raw.csv and the tx log exist.

    `ranking_v2.py test` writes them only after every condition has finished, so a
    condition whose 120 cells are all cached is assembled here from the cache.
    Returns a status string for printing."""
    d = OUT / cond
    if (d / "test_raw.csv").exists() and (d / f"tx_log_test_{cond}.csv").exists():
        return "ready (test_raw.csv)"
    cells = sorted((OUT / "_cells" / "test" / cond).glob("*.pkl"))
    expected = 30 * len(COUNTS)
    if len(cells) < expected:
        return f"not finished ({len(cells)}/{expected} cells cached) - skipped"
    import pickle
    rows, txs = [], []
    for path in cells:
        r, t = pickle.load(path.open("rb"))
        rows += r
        if len(t):
            txs.append(t)
    d.mkdir(exist_ok=True)
    pd.DataFrame(rows).to_csv(d / "test_raw.csv", index=False, lineterminator="\n")
    pd.concat(txs, ignore_index=True).to_csv(d / f"tx_log_test_{cond}.csv", index=False, lineterminator="\n")
    return f"ready (assembled from {len(cells)} cached cells)"


def chosen_variant() -> str:
    m = re.search(r"Chosen variant: `(\w+)`", (OUT / "decision.md").read_text())
    return m.group(1)


def table(header, rows) -> str:
    return "\n".join(["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
                     + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


def fp(p):
    return "n/a" if p is None or (isinstance(p, float) and math.isnan(p)) else (f"{p:.1e}" if p < 1e-3 else f"{p:.3f}")


# ------------------------------------------------------------------ tables
def summary(raw: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for n in COUNTS + ["pooled"]:
        d = raw if n == "pooled" else raw[raw.n_robots == n]
        for p in POLICIES:
            g = d[d.policy == p]
            for m in METRICS:
                rows.append({"n_robots": n, "policy": p, "metric": m, **describe(g[m])})
    return pd.DataFrame(rows)


def families(chosen):
    return {
        "primary: chosen vs random": [(chosen, "random")],
        "comparators: chosen vs plus_0.30_6 / fifo": [(chosen, "plus_0.30_6"), (chosen, "fifo")],
        "ablation: info_only -> tw_now -> tw_arrival -> tw_arrival_sub":
            [("tw_now", "info_only"), ("tw_arrival", "tw_now"), ("tw_arrival_sub", "tw_arrival")],
    }


def paired_tests(raw: pd.DataFrame, chosen: str, metric="align_rmse") -> pd.DataFrame:
    rows = []
    piv = raw.pivot_table(index=["n_robots", "seed"], columns="policy", values=metric)
    for fam, comps in families(chosen).items():
        for a, b in comps:
            for n in COUNTS + ["pooled"]:
                d = piv if n == "pooled" else piv.loc[n]
                diff = (d[a] - d[b]).to_numpy(float)
                ci = st.t.ppf(0.975, len(diff) - 1) * diff.std(ddof=1) / math.sqrt(len(diff))
                rows.append({"family": fam, "policy": a, "versus": b, "n_robots": n, "metric": metric,
                             **paired(d[a].to_numpy(), d[b].to_numpy()), "mean_diff": diff.mean(),
                             "mean_diff_ci95_lo": diff.mean() - ci, "mean_diff_ci95_hi": diff.mean() + ci})
    out = pd.DataFrame(rows)
    out["p_holm"] = np.nan
    for _, idx in out.groupby("family").groups.items():
        out.loc[idx, "p_holm"] = holm(out.loc[idx, "wilcoxon_p_two_sided"])
    return out


def mechanism(tx: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for p in POLICIES:
        d = tx[tx.policy == p]
        dl = d[d.delivered]
        ok = dl[["predicted_arrival_age", "actual_arrival_age"]].dropna()
        rem = dl.t_arrival - dl.t_sched
        rows.append({
            "policy": p, "n_transmitted": len(d), "delivered_share": d.delivered.mean(),
            "mean_attempts": d.attempts.mean(), "outlier_share": d.is_outlier.mean(),
            "mean_theta_schedule": d.theta_schedule.mean(), "mean_theta_now": d.theta_now.mean(),
            "mean_theta_hat_code": d.theta_hat_code.mean(), "mean_theta_arrival": d.theta_arrival.mean(),
            "mean_delta_theta": d.delta_theta.mean(),
            "mean_delta_theta_inliers": d[~d.is_outlier].delta_theta.mean(),
            "mean_delta_theta_outliers": d[d.is_outlier].delta_theta.mean(),
            "retention_R_mean": d.R.mean(), "retention_R_median": d.R.median(),
            "I_exact_mean": d.I_exact.mean(), "I_exact_median": d.I_exact.median(),
            "I_theta_arrival_mean": d.I_theta_arrival.mean(), "I_hat_mean": d.I_hat.mean(),
            "age_at_schedule_mean": d.age_at_schedule.mean(),
            "predicted_arrival_age_mean": ok.predicted_arrival_age.mean(),
            "actual_arrival_age_mean": ok.actual_arrival_age.mean(),
            "arrival_age_MAE": (ok.predicted_arrival_age - ok.actual_arrival_age).abs().mean(),
            "arrival_age_bias": (ok.predicted_arrival_age - ok.actual_arrival_age).mean(),
            "arrival_age_spearman": st.spearmanr(ok.predicted_arrival_age, ok.actual_arrival_age)[0] if len(ok) > 2 else np.nan,
            "code_dt_hat_MAE_vs_remaining_delay": (dl.dt_hat_code - rem).abs().mean(),
            "I_exact_fraction_computed": d.I_exact.notna().mean(),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ figures
def _style(ax):
    ax.grid(axis="y", color="#e2e2e0", zorder=0)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def fig_ablation(summ: pd.DataFrame, path: Path):
    import matplotlib.pyplot as plt
    pol = ["fifo", "random", "info_only", "bacs_gated", "plus_0.30_6", "tw_now", "tw_arrival", "tw_arrival_sub"]
    s = summ[summ.metric == "align_rmse"]
    fig, ax = plt.subplots(figsize=(10, 4.8), dpi=150)
    w = 0.8 / len(pol)
    for i, p in enumerate(pol):
        r = s[(s.policy == p) & (s.n_robots != "pooled")].copy()
        r = r.set_index("n_robots").loc[COUNTS]
        x = np.arange(len(COUNTS)) + (i - (len(pol) - 1) / 2) * w
        ax.bar(x, r["mean"], w * 0.92, color=COLORS[p], hatch=HATCH.get(p), edgecolor="white", lw=0.8,
               label=LABEL[p], zorder=2)
        ax.errorbar(x, r["mean"], yerr=[r["mean"] - r.ci95_lo, r.ci95_hi - r["mean"]], fmt="none",
                    ecolor="#52514e", elinewidth=1, capsize=2, zorder=3)
    ax.set_xticks(range(len(COUNTS)), [str(n) for n in COUNTS])
    ax.set_xlabel("Robots (N)")
    ax.set_ylabel("Map-alignment RMSE (m)")
    ax.set_title("Map-alignment RMSE (m), C0 nominal: mean and 95% CI, TEST seeds 40-69", loc="left", fontsize=11)
    _style(ax)
    ax.set_ylim(0, None)
    ax.legend(ncol=8, fontsize=7.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.13))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_mechanism(summaries: dict, path: Path):
    import matplotlib.pyplot as plt
    conds = [c for c in CONDS if c in summaries]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), dpi=150)
    w = 0.8 / len(conds)
    for ax, (m, lab) in zip(axes, (("mean_R", "Retention R (mean per run)"), ("trust_yield", "Trust yield (mean server θ)"))):
        for i, c in enumerate(conds):
            s = summaries[c]
            r = s[(s.metric == m) & (s.n_robots == "pooled")].set_index("policy").loc[POLICIES]
            x = np.arange(len(POLICIES)) + (i - (len(conds) - 1) / 2) * w
            ax.bar(x, r["mean"], w * 0.92, color=RAMP[i], edgecolor="white", lw=0.6, label=c, zorder=2)
            ax.errorbar(x, r["mean"], yerr=[r["mean"] - r.ci95_lo, r.ci95_hi - r["mean"]], fmt="none",
                        ecolor="#52514e", elinewidth=0.8, capsize=1.5, zorder=3)
        ax.set_xticks(range(len(POLICIES)), [LABEL[p] for p in POLICIES], rotation=40, ha="right", fontsize=8)
        ax.set_title(f"{lab}: mean and 95% CI over 120 runs", loc="left", fontsize=10)
        _style(ax)
    axes[0].legend(ncol=4, fontsize=8, frameon=False, loc="lower left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def fig_stress(trend: pd.DataFrame, chosen: str, path: Path):
    import matplotlib.pyplot as plt
    conds = [c for c in CONDS if c in set(trend.condition)]
    fig, ax = plt.subplots(figsize=(8, 4.4), dpi=150)
    ax.axhline(0, color="#52514e", lw=1, ls="--", zorder=1)
    for i, n in enumerate(COUNTS + ["pooled"]):
        r = trend[trend.n_robots.astype(str) == str(n)].set_index("condition").loc[conds]
        x = np.arange(len(conds)) + (i - 2) * 0.12
        pooled = n == "pooled"
        ax.errorbar(x, r.mean_diff, yerr=[r.mean_diff - r.mean_diff_ci95_lo, r.mean_diff_ci95_hi - r.mean_diff],
                    fmt="o" if not pooled else "D", ms=8 if not pooled else 9, color=RAMP[i] if not pooled else "#0b0b0b",
                    elinewidth=1.2, capsize=2, label=f"N = {n}" if not pooled else "pooled (120 pairs)", zorder=3)
    ax.set_xticks(range(len(conds)), conds)
    ax.set_xlabel("Condition")
    ax.set_ylabel(f"{LABEL[chosen]} − Random, alignment RMSE (m)")
    ax.set_title("Paired difference vs Random (below 0 = chosen variant better): mean and 95% CI", loc="left", fontsize=10)
    _style(ax)
    ax.legend(ncol=5, fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14))
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


# ------------------------------------------------------------------ report
def fmt_summary(s: pd.DataFrame, metric: str, digits=3) -> str:
    rows = []
    for p in POLICIES:
        row = [LABEL[p]]
        for n in COUNTS + ["pooled"]:
            r = s[(s.metric == metric) & (s.policy == p) & (s.n_robots == n)]
            if not len(r):
                row.append("")
                continue
            r = r.iloc[0]
            row.append(f"{r['mean']:.{digits}f} ± {r.sd:.{digits}f} [{r.ci95_lo:.{digits}f}, {r.ci95_hi:.{digits}f}]")
        rows.append(row)
    return table(["policy", "N=2", "N=3", "N=4", "N=5", "pooled"], rows)


def fmt_extra(s: pd.DataFrame) -> str:
    ms = [("trust_yield", 3), ("n_delivered", 1), ("airtime_util", 3), ("median_age_tx", 1),
          ("median_age_arrival", 1), ("mean_R", 3), ("pose_rmse", 3)]
    rows = []
    for p in POLICIES:
        row = [LABEL[p]]
        for m, d in ms:
            r = s[(s.metric == m) & (s.policy == p) & (s.n_robots == "pooled")].iloc[0]
            row.append(f"{r['mean']:.{d}f} ± {r.sd:.{d}f}")
        rows.append(row)
    return table(["policy (pooled over N)", "trust yield", "delivered", "airtime util.", "median age at tx (s)",
                  "median age at arrival (s)", "mean R", "pose RMSE (m)"], rows)


def fmt_tests(t: pd.DataFrame) -> str:
    rows = [[r.family.split(":")[0], f"{r.policy} vs {r.versus}", r.n_robots, f"{r.pct_change_of_mean:+.1f} %",
             f"{r.mean_diff:+.4f} [{r.mean_diff_ci95_lo:+.4f}, {r.mean_diff_ci95_hi:+.4f}]",
             fp(r.wilcoxon_p_two_sided), fp(r.p_holm), f"{r.cliffs_delta:+.2f}",
             f"{r.seeds_won}/{r.n_pairs}" + (f" ({r.seeds_tied} tied)" if r.seeds_tied else "")]
            for r in t.itertuples()]
    return table(["family", "comparison", "N", "Δ mean", "mean paired diff (m) [95% CI]", "Wilcoxon p",
                  "Holm p", "Cliff's δ", "won"], rows)


def fmt_mech(m: pd.DataFrame) -> str:
    rows = [[LABEL[r.policy], r.n_transmitted, f"{r.mean_theta_schedule:.3f}", f"{r.mean_theta_arrival:.3f}",
             f"{r.mean_delta_theta:+.3f}", f"{r.mean_delta_theta_inliers:+.3f}", f"{r.mean_delta_theta_outliers:+.3f}",
             f"{r.retention_R_mean:.3f}", f"{r.I_exact_median:.2f}", f"{r.predicted_arrival_age_mean:.1f}",
             f"{r.actual_arrival_age_mean:.1f}", f"{r.arrival_age_MAE:.1f}", f"{r.arrival_age_spearman:.3f}",
             f"{r.outlier_share:.3f}"] for r in m.itertuples()]
    return table(["policy", "tx", "θ sched (pred.)", "θ arrival (server)", "Δθ", "Δθ inliers", "Δθ outliers",
                  "R", "median I_exact", "pred. arrival age (s)", "actual arrival age (s)", "age MAE (s)",
                  "age Spearman", "outlier share"], rows)


def main():
    import matplotlib
    matplotlib.use("Agg")
    chosen = chosen_variant()
    summaries, trend_rows, sections = {}, [], []
    ready = {c: _ensure_test_raw(c) for c in CONDS}
    for c, state in ready.items():
        print(f"{c}: {state}")
    if not any(v.startswith("ready") for v in ready.values()):
        sys.exit("No condition has finished its TEST run yet (see the counts above). Run "
                 "`python3 scripts/revision/ranking_v2.py test C0 C1 C2 C3` to completion first.")
    for c in CONDS:
        d = OUT / c
        if not ready[c].startswith("ready"):
            continue
        raw = pd.read_csv(d / "test_raw.csv")
        tx = pd.read_csv(d / f"tx_log_test_{c}.csv")
        s = summary(raw)
        s.to_csv(d / "test_summary.csv", index=False, lineterminator="\n")
        t = paired_tests(raw, chosen)
        t.to_csv(d / "test_paired_tests.csv", index=False, lineterminator="\n")
        m = mechanism(tx)
        m.to_csv(d / "mechanism.csv", index=False, lineterminator="\n")
        summaries[c] = s
        for r in t[(t.policy == chosen) & (t.versus == "random")].itertuples():
            trend_rows.append({"condition": c, "n_robots": r.n_robots, "chosen": chosen,
                               "mean_chosen": r.mean_a, "mean_random": r.mean_b,
                               "gain_pct_vs_random": -r.pct_change_of_mean, "mean_diff": r.mean_diff,
                               "mean_diff_ci95_lo": r.mean_diff_ci95_lo, "mean_diff_ci95_hi": r.mean_diff_ci95_hi,
                               "wilcoxon_p_two_sided": r.wilcoxon_p_two_sided, "p_holm": r.p_holm,
                               "cliffs_delta": r.cliffs_delta, "seeds_won": r.seeds_won, "n_pairs": r.n_pairs})
        sections.append(f"### {c}\n\n**Map-alignment RMSE (m), mean ± SD [95 % t-CI]**\n\n"
                        f"{fmt_summary(s, 'align_rmse')}\n\n**Other metrics, pooled over N (mean ± SD, 120 runs)**\n\n"
                        f"{fmt_extra(s)}\n\n**Paired tests on map-alignment RMSE** (Δ and diff negative = first "
                        f"policy lower; won = pairs where it is lower; Holm within each family, 5 tests per "
                        f"comparison)\n\n{fmt_tests(t)}\n\n**Mechanism (all transmitted constraints, pooled over N)**"
                        f"\n\n{fmt_mech(m)}\n")
    trend = pd.DataFrame(trend_rows)
    trend.to_csv(OUT / "stress_trend.csv", index=False, lineterminator="\n")
    if "C0" in summaries:
        fig_ablation(summaries["C0"], OUT / "fig_ablation.png")
    fig_mechanism(summaries, OUT / "fig_mechanism.png")
    fig_stress(trend, chosen, OUT / "fig_stress.png")
    missing = [c for c in CONDS if c not in summaries]
    if missing:
        print(f"NOTE: {', '.join(missing)} not finished; tables, figures and REPORT.md cover "
              f"{', '.join(summaries)} only. Re-run this script when the TEST run completes.")

    cond = json.loads((OUT / "conditions.json").read_text())
    crow = [[c, json.dumps(cond[c]["overrides"]), f"{cond[c]['t_defer']:.1f}", f"{math.log(2) / cond[c]['t_defer']:.5f}"]
            for c in CONDS if c in cond]
    pilot = pd.read_csv(OUT / "pilot_tdefer.csv")
    prow = [[r.condition, r.n_transmitted, f"{r.deferral_median_s:.1f}", f"{r.deferral_mean_s:.1f}",
             f"{r.cells_with_zero_tx}/{r.cells}"] for r in pilot.itertuples()]
    p60 = pd.read_csv(OUT / "pilot_tdefer_W60_infeasible.csv")
    p60row = [[r.condition, r.overrides, r.n_transmitted, f"{r.cells_with_zero_tx}/{r.cells}"] for r in p60.itertuples()]
    trow = [[r.condition, r.n_robots, f"{r.mean_chosen:.4f}", f"{r.mean_random:.4f}", f"{r.gain_pct_vs_random:+.1f} %",
             f"{r.mean_diff:+.4f} [{r.mean_diff_ci95_lo:+.4f}, {r.mean_diff_ci95_hi:+.4f}]", fp(r.wilcoxon_p_two_sided),
             fp(r.p_holm), f"{r.cliffs_delta:+.2f}", f"{r.seeds_won}/{r.n_pairs}"] for r in trend.itertuples()]
    runtimes = "\n".join(f"- {p.read_text().strip()}" for p in sorted(OUT.glob("runtime_*.txt")))
    decision = (OUT / "decision.md").read_text().split("\n", 1)[1]
    template = (HERE / "ranking_v2_report_template.md").read_text()
    report = template.format(
        chosen=chosen, chosen_label=LABEL[chosen], decision=decision,
        conditions=table(["condition", "overrides", "T_defer (s)", "γ = ln2/T_defer (1/s)"], crow),
        pilot=table(["condition", "transmitted", "median deferral (s)", "mean deferral (s)", "cells with no tx"], prow),
        pilot60=table(["condition", "overrides (W = 60 s)", "transmitted", "cells with no tx"], p60row),
        trend=table(["condition", "N", f"{LABEL[chosen]}", "Random", "gain vs Random", "mean paired diff (m) [95% CI]",
                     "Wilcoxon p", "Holm p", "Cliff's δ", "won"], trow),
        sections="\n".join(sections), runtimes=runtimes)
    (OUT / "REPORT.md").write_text(report)
    print("wrote", (OUT / "REPORT.md").relative_to(ROOT))


if __name__ == "__main__":
    main()
