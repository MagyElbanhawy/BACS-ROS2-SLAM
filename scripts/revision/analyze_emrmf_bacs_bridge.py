"""
Statistical Analysis & Mechanism Profiler for EMRMF vs. BACS+ Bridge Experiment.

Reads `paper_results/revision/emrmf_bacs_bridge/raw.csv` and computes:
- Primary paired Wilcoxon signed-rank test and 95% CIs
- Holm-adjusted condition-specific breakdowns (C0-C3)
- Scalability breakdown (N=2..5)
- Constraint mechanism and outlier rejection profiling
- Publication claim text generator

Writes outputs to paper_results/revision/emrmf_bacs_bridge/.
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def cliffs_delta(a, b):
    """Compute Cliff's delta effect size in [-1, 1]."""
    a = np.asarray([v for v in a if np.isfinite(v)], float)
    b = np.asarray([v for v in b if np.isfinite(v)], float)
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    gt = (a[:, None] > b[None, :]).sum()
    lt = (a[:, None] < b[None, :]).sum()
    return float((gt - lt) / (len(a) * len(b)))


def holm_adjust(pvals):
    """Apply Holm-Bonferroni correction to array of p-values."""
    pvals = np.asarray(pvals, float)
    n = len(pvals)
    sorted_idx = np.argsort(pvals)
    adj = np.zeros(n)
    cum_max = 0.0
    for rank, idx in enumerate(sorted_idx):
        p = pvals[idx]
        adj_p = min(1.0, p * (n - rank))
        cum_max = max(cum_max, adj_p)
        adj[idx] = cum_max
    return adj


def analyze_bridge_results(raw_path: Path, out_dir: Path):
    """Process raw paired experiment results into statistical tables and report."""
    if not raw_path.exists():
        print(f"Error: Raw data file {raw_path} not found.")
        return

    df = pd.read_csv(raw_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filter to primary comparison arms
    df_emrmf = df[df.policy == "emrmf_reference"].set_index(["condition", "n_robots", "seed"])
    df_bacs  = df[df.policy == "bacs_plus"].set_index(["condition", "n_robots", "seed"])

    # Find common paired keys
    common_keys = df_emrmf.index.intersection(df_bacs.index)
    if len(common_keys) == 0:
        print("Error: No matching paired runs found between emrmf_reference and bacs_plus.")
        return

    df_e = df_emrmf.loc[common_keys].reset_index()
    df_b = df_bacs.loc[common_keys].reset_index()

    # Align vectors
    e_align = df_e["align_rmse"].values
    b_align = df_b["align_rmse"].values

    delta = b_align - e_align
    rel_impr = 100.0 * (e_align - b_align) / np.maximum(e_align, 1e-9)

    valid_mask = np.isfinite(e_align) & np.isfinite(b_align)
    n_valid = int(valid_mask.sum())

    if n_valid < 5:
        print(f"Warning: Only {n_valid} valid paired samples. Statistics may be unreliable.")

    # 1. PRIMARY STATISTICAL TEST
    stat = wilcoxon(e_align[valid_mask], b_align[valid_mask])
    w_stat = float(stat.statistic)
    p_val = float(stat.pvalue)

    mean_e = float(np.mean(e_align[valid_mask]))
    sd_e   = float(np.std(e_align[valid_mask], ddof=1))
    med_e  = float(np.median(e_align[valid_mask]))

    mean_b = float(np.mean(b_align[valid_mask]))
    sd_b   = float(np.std(b_align[valid_mask], ddof=1))
    med_b  = float(np.median(b_align[valid_mask]))

    mean_diff = float(np.mean(delta[valid_mask]))
    sd_diff   = float(np.std(delta[valid_mask], ddof=1))
    med_diff  = float(np.median(delta[valid_mask]))

    ci_half = 1.96 * sd_diff / np.sqrt(n_valid) if n_valid > 1 else 0.0
    ci_lo = mean_diff - ci_half
    ci_hi = mean_diff + ci_half

    mean_rel_impr = float(np.mean(rel_impr[valid_mask]))
    c_delta = cliffs_delta(b_align[valid_mask], e_align[valid_mask])

    wins = int((delta[valid_mask] < -1e-6).sum())
    ties = int((np.abs(delta[valid_mask]) <= 1e-6).sum())
    losses = int((delta[valid_mask] > 1e-6).sum())

    catastrophic_e = float(np.mean(e_align[valid_mask] > 0.50))
    catastrophic_b = float(np.mean(b_align[valid_mask] > 0.50))

    primary_df = pd.DataFrame([{
        "comparison": "BACS+ vs EMRMF reference",
        "n_pairs": n_valid,
        "emrmf_mean_rmse": mean_e,
        "emrmf_sd_rmse": sd_e,
        "emrmf_median_rmse": med_e,
        "bacs_plus_mean_rmse": mean_b,
        "bacs_plus_sd_rmse": sd_b,
        "bacs_plus_median_rmse": med_b,
        "mean_paired_diff": mean_diff,
        "ci95_lo": ci_lo,
        "ci95_hi": ci_hi,
        "median_paired_diff": med_diff,
        "mean_improvement_pct": mean_rel_impr,
        "wilcoxon_W": w_stat,
        "p_value": p_val,
        "cliffs_delta": c_delta,
        "bacs_plus_wins": wins,
        "ties": ties,
        "emrmf_wins": losses,
        "emrmf_catastrophic_rate": catastrophic_e,
        "bacs_plus_catastrophic_rate": catastrophic_b,
    }])
    primary_df.to_csv(out_dir / "primary.csv", index=False)

    # 2. BY CONDITION ANALYSIS (C0 - C3)
    cond_rows = []
    unadj_pvals = []
    cond_names = ["C0", "C1", "C2", "C3"]
    for c_name in cond_names:
        sub_e = df_e[df_e.condition == c_name]["align_rmse"].values
        sub_b = df_b[df_b.condition == c_name]["align_rmse"].values
        m = np.isfinite(sub_e) & np.isfinite(sub_b)
        n_c = int(m.sum())
        if n_c >= 5:
            st = wilcoxon(sub_e[m], sub_b[m])
            p_c = float(st.pvalue)
            w_c = float(st.statistic)
        else:
            p_c, w_c = np.nan, np.nan
        unadj_pvals.append(p_c)

        d_c = sub_b[m] - sub_e[m]
        rel_c = 100.0 * (sub_e[m] - sub_b[m]) / np.maximum(sub_e[m], 1e-9)

        cond_rows.append({
            "condition": c_name,
            "n_pairs": n_c,
            "emrmf_mean": float(np.mean(sub_e[m])),
            "bacs_mean": float(np.mean(sub_b[m])),
            "abs_diff": float(np.mean(d_c)),
            "improvement_pct": float(np.mean(rel_c)),
            "wilcoxon_W": w_c,
            "p_unadjusted": p_c,
            "wins": int((d_c < -1e-6).sum()),
            "ties": int((np.abs(d_c) <= 1e-6).sum()),
            "losses": int((d_c > 1e-6).sum()),
            "emrmf_catastrophic": float(np.mean(sub_e[m] > 0.50)),
            "bacs_catastrophic": float(np.mean(sub_b[m] > 0.50)),
        })

    adj_pvals = holm_adjust(unadj_pvals)
    for r, adj_p in zip(cond_rows, adj_pvals):
        r["p_holm"] = float(adj_p)

    df_cond = pd.DataFrame(cond_rows)
    df_cond.to_csv(out_dir / "by_condition.csv", index=False)

    # 3. SCALABILITY ANALYSIS (N = 2, 3, 4, 5)
    scal_rows = []
    for n_bot in [2, 3, 4, 5]:
        sub_e = df_e[df_e.n_robots == n_bot]["align_rmse"].values
        sub_b = df_b[df_b.n_robots == n_bot]["align_rmse"].values
        m = np.isfinite(sub_e) & np.isfinite(sub_b)
        n_s = int(m.sum())
        if n_s >= 5:
            st = wilcoxon(sub_e[m], sub_b[m])
            p_s = float(st.pvalue)
            w_s = float(st.statistic)
        else:
            p_s, w_s = np.nan, np.nan

        d_s = sub_b[m] - sub_e[m]
        rel_s = 100.0 * (sub_e[m] - sub_b[m]) / np.maximum(sub_e[m], 1e-9)

        scal_rows.append({
            "n_robots": n_bot,
            "n_pairs": n_s,
            "emrmf_mean": float(np.mean(sub_e[m])),
            "bacs_mean": float(np.mean(sub_b[m])),
            "abs_diff": float(np.mean(d_s)),
            "improvement_pct": float(np.mean(rel_s)),
            "wilcoxon_W": w_s,
            "p_value": p_s,
            "wins": int((d_s < -1e-6).sum()),
            "ties": int((np.abs(d_s) <= 1e-6).sum()),
            "losses": int((d_s > 1e-6).sum()),
        })

    df_scal = pd.DataFrame(scal_rows)
    df_scal.to_csv(out_dir / "by_robot_count.csv", index=False)

    # 4. MECHANISM BREAKDOWN
    mech_cols = [
        "n_candidates", "n_sent", "n_delivered", "n_accepted", "n_rejected",
        "n_outliers_delivered", "n_outliers_rejected", "n_inliers_rejected",
        "trust_yield", "airtime_util", "outlier_share", "sched_ms"
    ]
    mech_rows = []
    for pol in df.policy.unique():
        sub = df[df.policy == pol]
        r_dict = {"policy": pol, "n_runs": len(sub)}
        for col in mech_cols:
            if col in sub.columns:
                r_dict[f"{col}_mean"] = float(sub[col].mean())
                r_dict[f"{col}_std"]  = float(sub[col].std())
        mech_rows.append(r_dict)

    df_mech = pd.DataFrame(mech_rows)
    df_mech.to_csv(out_dir / "mechanism.csv", index=False)

    # 5. SYNTHESIZE REPORT & PAPER CLAIM TEXT
    claim_text = generate_claim_text(mean_e, mean_b, mean_rel_impr, p_val, c_delta, wins, n_valid)
    write_markdown_report(out_dir / "REPORT.md", primary_df, df_cond, df_scal, df_mech, claim_text)
    print(f"Analysis complete. Summaries saved to {out_dir}/")


def generate_claim_text(mean_e, mean_b, impr_pct, p_val, c_delta, wins, n_tot):
    """Generate publication-ready text based on statistical significance."""
    if p_val < 0.05 and mean_b < mean_e:
        return (
            f"Under the controlled paired protocol (n={n_tot}), BACS+ significantly reduced "
            f"mean map-alignment RMSE from {mean_e:.3f} m with published EMRMF reference to {mean_b:.3f} m, "
            f"corresponding to a {impr_pct:.1f}% error reduction (paired Wilcoxon W, p = {p_val:.2e}, "
            f"Cliff's delta = {c_delta:.2f}). BACS+ achieved a lower alignment error in {wins} of {n_tot} paired cases."
        )
    elif mean_b < mean_e:
        return (
            f"BACS+ produced a lower mean map-alignment RMSE than EMRMF reference ({mean_b:.3f} m vs {mean_e:.3f} m), "
            f"corresponding to a {impr_pct:.1f}% numerical error reduction; however, the paired comparison did not reach "
            f"statistical significance (p = {p_val:.4f}), so the result is interpreted as a favorable trend."
        )
    else:
        return (
            f"Under the controlled paired protocol (n={n_tot}), EMRMF reference achieved a mean map-alignment RMSE "
            f"of {mean_e:.3f} m versus {mean_b:.3f} m for BACS+ (p = {p_val:.4f}). Investigation of the constraint "
            f"selection mechanism reveals the operational trade-offs under this specific channel load."
        )


def _df_to_markdown(df):
    try:
        return df.to_markdown(index=False)
    except Exception:
        cols = list(df.columns)
        header = "| " + " | ".join(str(c) for c in cols) + " |"
        sep = "| " + " | ".join(["---"] * len(cols)) + " |"
        rows = []
        for _, row in df.iterrows():
            r_str = "| " + " | ".join(str(row[c]) for c in cols) + " |"
            rows.append(r_str)
        return "\n".join([header, sep] + rows)


def write_markdown_report(report_path: Path, df_primary, df_cond, df_scal, df_mech, claim_text):
    """Write comprehensive Markdown report."""
    with open(report_path, "w") as f:
        f.write("# EMRMF vs. BACS+ Controlled Bridge Experiment Report\n\n")
        f.write("## 1. Executive Summary & Publication Claim\n\n")
        f.write(f"> **Publication Claim Text**:\n> {claim_text}\n\n")
        f.write("## 2. Primary Paired Endpoint (Map-Alignment RMSE)\n\n")
        f.write(_df_to_markdown(df_primary) + "\n\n")
        f.write("## 3. Condition-Specific Breakdown (C0–C3)\n\n")
        f.write(_df_to_markdown(df_cond) + "\n\n")
        f.write("## 4. Scalability Breakdown (N = 2..5)\n\n")
        f.write(_df_to_markdown(df_scal) + "\n\n")
        f.write("## 5. Constraint & Airtime Mechanism Profiling\n\n")
        f.write(_df_to_markdown(df_mech) + "\n\n")


def main():
    root_dir = ROOT / "paper_results" / "revision" / "emrmf_bacs_bridge"
    raw_csv = root_dir / "raw.csv"
    analyze_bridge_results(raw_csv, root_dir)


if __name__ == "__main__":
    main()
