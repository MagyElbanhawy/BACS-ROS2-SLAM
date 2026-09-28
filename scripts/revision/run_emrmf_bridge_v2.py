"""
Reproducibility Runner for EMRMF vs. BACS+ Bridge V2 Experiment.

Executes a preregistered paired comparison between published EMRMF (Saber et al. 2026)
and final frozen BACS+ (plus_0.30_6) across fresh seeds 100-129 under conditions L0-L3.

Output directory: paper_results/revision/emrmf_bridge_v2/
Do NOT commit, push, or modify existing folders.

Usage:
  python scripts/revision/run_emrmf_bridge_v2.py [--jobs N]
"""
import os
import sys
import time
import hashlib
import datetime
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy.stats import wilcoxon

# Ensure workspace root is in path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bacs_sim.config import SimConfig
from bacs_sim.simulator import run, precompute


CONDITIONS = [
    {"name": "L0", "model": "independent", "loss": 0.0,  "delay": 0.0},
    {"name": "L1", "model": "independent", "loss": 0.10, "delay": 0.0},
    {"name": "L2", "model": "independent", "loss": 0.30, "delay": 0.0},
    {"name": "L3", "model": "burst",       "loss": 0.30, "delay": 0.20, "ge_p_bad": 0.30, "ge_mean_burst": 4.0},
]

ARMS = [
    "emrmf_published",
    "emrmf_drift",
    "fifo_defer",
    "random",
    "bacs_gated",
    "plus_0.30_6"
]


def file_sha256(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def verify_seed_freshness(seeds: range):
    """Verify that no existing raw CSV file contains seeds >= 100."""
    paper_results_dir = ROOT / "paper_results"
    for csv_file in paper_results_dir.glob("**/*.csv"):
        try:
            df = pd.read_csv(csv_file)
            if "seed" in df.columns:
                max_seed = df["seed"].max()
                if max_seed >= min(seeds):
                    raise RuntimeError(
                        f"Seed freshness violation! File {csv_file.relative_to(ROOT)} contains seed {max_seed} >= {min(seeds)}"
                    )
        except Exception as e:
            if isinstance(e, RuntimeError):
                raise e
            continue
    print(f"Seed freshness verified: No existing CSV contains seeds >= {min(seeds)}.")


def write_preregistration(out_dir: Path, seeds: range):
    """Write prereg.md with timestamp and SHA-256 hashes BEFORE experiment execution."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prereg_path = out_dir / "prereg.md"

    f_sched = ROOT / "bacs_sim" / "schedulers.py"
    f_sim   = ROOT / "bacs_sim" / "simulator.py"
    f_exp   = ROOT / "bacs_sim" / "experiments.py"

    hash_sched = file_sha256(f_sched)
    hash_sim   = file_sha256(f_sim)
    hash_exp   = file_sha256(f_exp)

    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    content = f"""# Preregistration: EMRMF vs. BACS+ Bridge V2 Experiment

**Experiment Identifier**: `emrmf_bridge_v2`  
**Date & Timestamp**: {timestamp}  
**Status**: FROZEN BEFORE EXECUTION  

---

## 1. Code Integrity & SHA-256 Hashes

| File | SHA-256 Hash |
| :--- | :--- |
| `bacs_sim/schedulers.py` | `{hash_sched}` |
| `bacs_sim/simulator.py` | `{hash_sim}` |
| `bacs_sim/experiments.py` | `{hash_exp}` |

---

## 2. Objective & Primary Hypothesis

### 2.1 Context & Terminology
- **EMRMF**: Enhanced Multi-Robot Map Fusion (Saber et al. 2026). Published baseline.
- **Modelling Assumption**: FIFO candidate transmission is adopted for EMRMF because the published paper did not specify an airtime constraint selection rule under duty-cycle limited channels.

### 2.2 Primary Hypothesis
- **Primary Comparison**: `plus_0.30_6` vs `emrmf_published` on map-alignment RMSE (`align_rmse`), pooled over all 480 paired runs (L0-L3 $\\times$ N=2..5 $\\times$ seeds 100-129).
- **Statistical Test**: Two-sided paired Wilcoxon signed-rank test ($\alpha = 0.05$).

---

## 3. Secondary Hypotheses & Decompositions (Holm-Adjusted)

1. **Condition-Specific Tests**: Paired Wilcoxon per condition (L0, L1, L2, L3) with Holm-Bonferroni correction.
2. **Methodological Decomposition**: Stepwise progression isolating specific mechanisms:
   - `emrmf_published` $\to$ `emrmf_drift`: Effect of drift-derived gamma calibration under FIFO.
   - `emrmf_drift` $\to$ `fifo_defer`: Effect of airtime deferral-derived gamma calibration under FIFO.
   - `fifo_defer` $\to$ `plus_0.30_6`: Effect of bandwidth- and observability-aware knapsack scheduling at fixed deferral gamma.
3. **Control Comparison**: `plus_0.30_6` vs `random`.

---

## 4. Evaluated Arms & Parameters

- **Seeds**: {min(seeds)} to {max(seeds)} ({len(seeds)} fresh seeds).
- **Robot Team Sizes ($N$)**: 2, 3, 4, 5.
- **Session Duration**: 480 s.
- **LoRa Physical Model**: SF7, 125 kHz BW, 1% EU868 regulatory duty-cycle ceiling.
- **Conditions**: L0 (no loss), L1 (10% iid), L2 (30% iid), L3 (30% GE burst + 0.2s delay).

### Arms (Identical Precomputed Worlds):
1. **`emrmf_published`**: FIFO (`-c.t_created`), `gamma=0.10`, `p=3`, `tau_e=0.5m`, floor `0.01`, `trust_gate=0.0`, `use_observability=False`. [PRIMARY CONTROL]
2. **`emrmf_drift`**: FIFO (`-c.t_created`), `gamma=0.0333` (drift-derived Eq. 20), `trust_gate=0.0`, `use_observability=False`.
3. **`fifo_defer`**: FIFO (`-c.t_created`), `gamma=0.0045` (deferral-derived $\ln 2 / 155s$), `trust_gate=0.0`, `use_observability=False`.
4. **`random`**: Random candidate ordering, `gamma=0.0045`, `trust_gate=0.0`, `use_observability=False`.
5. **`bacs_gated`**: Gated density ranking, `gamma=0.0045`, `trust_gate=0.05`, `use_observability=False`.
6. **`plus_0.30_6`**: BACS+ density ranking, `gamma=0.0045`, `w_obs=0.30`, `obs_ref=6.0`, `trust_gate=0.05`, `use_observability=True`. [PRIMARY TREATMENT]
"""
    with open(prereg_path, "w") as f:
        f.write(content)
    print(f"Preregistration written to: {prereg_path}")


def configure_arm(policy_name: str, cond: dict, seed: int, n_robots: int, session_s: float = 480.0) -> SimConfig:
    """Build SimConfig for a specific policy arm and condition."""
    cfg = SimConfig()
    cfg.seed = seed
    cfg.world.n_robots = n_robots
    cfg.world.session_s = session_s

    # Channel condition
    cfg.channel.loss_model = cond["model"]
    cfg.channel.loss_rate = cond["loss"]
    cfg.channel.extra_delay_s = cond["delay"]
    if "ge_p_bad" in cond:
        cfg.channel.ge_p_bad = cond["ge_p_bad"]
    if "ge_mean_burst" in cond:
        cfg.channel.ge_mean_burst = cond["ge_mean_burst"]

    # Arm parameters
    if policy_name == "emrmf_published":
        cfg.scheduler.policy = "emrmf_reference"
        cfg.trust.gamma_rule = "fixed"
        cfg.trust.gamma = 0.10
        cfg.trust.p = 3
        cfg.trust.tau_e = 0.5
        cfg.trust.floor = 0.01
        cfg.scheduler.trust_gate = 0.0
        cfg.scheduler.use_observability = False
    elif policy_name == "emrmf_drift":
        cfg.scheduler.policy = "emrmf_reference"
        cfg.trust.gamma_rule = "fixed"
        cfg.trust.gamma = 0.0333
        cfg.trust.p = 3
        cfg.trust.tau_e = 0.5
        cfg.trust.floor = 0.01
        cfg.scheduler.trust_gate = 0.0
        cfg.scheduler.use_observability = False
    elif policy_name == "fifo_defer":
        cfg.scheduler.policy = "emrmf_reference"
        cfg.trust.gamma_rule = "fixed"
        cfg.trust.gamma = 0.0045
        cfg.trust.p = 3
        cfg.trust.tau_e = 0.5
        cfg.trust.floor = 0.01
        cfg.scheduler.trust_gate = 0.0
        cfg.scheduler.use_observability = False
    elif policy_name == "random":
        cfg.scheduler.policy = "random"
        cfg.trust.gamma_rule = "fixed"
        cfg.trust.gamma = 0.0045
        cfg.scheduler.trust_gate = 0.0
        cfg.scheduler.use_observability = False
    elif policy_name == "bacs_gated":
        cfg.scheduler.policy = "bacs_gated"
        cfg.trust.gamma_rule = "fixed"
        cfg.trust.gamma = 0.0045
        cfg.scheduler.trust_gate = 0.05
        cfg.scheduler.use_observability = False
    elif policy_name == "plus_0.30_6":
        cfg.scheduler.policy = "bacs_plus"
        cfg.trust.gamma_rule = "fixed"
        cfg.trust.gamma = 0.0045
        cfg.infogain.w_obs = 0.30
        cfg.infogain.obs_ref = 6.0
        cfg.scheduler.trust_gate = 0.05
        cfg.scheduler.use_observability = True
    else:
        raise ValueError(f"Unknown policy arm: {policy_name}")

    return cfg


def _eval_single_combo(task):
    """Worker function for single (cond, n, s) task."""
    cond, n, s, policies, session_s = task

    base_cfg = SimConfig()
    base_cfg.seed = s
    base_cfg.world.n_robots = n
    base_cfg.world.session_s = session_s
    base_cfg.channel.loss_model = cond["model"]
    base_cfg.channel.loss_rate = cond["loss"]
    base_cfg.channel.extra_delay_s = cond["delay"]
    if "ge_p_bad" in cond:
        base_cfg.channel.ge_p_bad = cond["ge_p_bad"]
    if "ge_mean_burst" in cond:
        base_cfg.channel.ge_mean_burst = cond["ge_mean_burst"]

    # Precompute shared world & candidates
    pre = precompute(base_cfg)

    combo_recs = []
    for pol in policies:
        cfg = configure_arm(pol, cond, s, n, session_s=session_s)
        res = run(cfg, precomputed=pre)

        rec = {
            "condition": cond["name"],
            "n_robots": n,
            "seed": s,
            "policy": pol,
            "align_rmse": res.align_rmse,
            "pose_rmse": res.pose_rmse,
            "trust_yield": res.trust_yield,
            "accept_rate": res.accept_rate,
            "airtime_util": res.airtime_util,
            "n_candidates": res.n_candidates,
            "n_sent": res.n_sent,
            "n_delivered": res.n_delivered,
            "n_accepted": res.extras.get("n_accepted", 0),
            "n_rejected": res.extras.get("n_rejected", 0),
            "n_outliers_delivered": res.extras.get("n_outliers_delivered", 0),
            "n_outliers_rejected": res.extras.get("n_outliers_rejected", 0),
            "n_inliers_rejected": res.extras.get("n_inliers_rejected", 0),
            "bytes_sent": res.bytes_sent,
            "starvation": res.starvation,
            "outlier_share": res.outlier_share,
            "sched_ms": res.sched_overhead_ms,
            "gamma_final": res.gamma_final,
            "dt_bias": res.dt_pred_bias,
            "is_catastrophic": bool(res.align_rmse > 0.50 if np.isfinite(res.align_rmse) else False),
        }
        combo_recs.append(rec)
    return combo_recs


def run_bridge_v2_experiment(seeds, counts, conditions, policies, out_dir: Path, session_s: float = 480.0, jobs: int = 4):
    """Run paired evaluations over precomputed world data."""
    t_start = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [(cond, n, s, policies, session_s)
             for cond in conditions for n in counts for s in seeds]
    total_combos = len(tasks)

    print(f"Starting EMRMF vs BACS+ Bridge V2 Experiment")
    print(f"  Seeds ({len(seeds)}): {min(seeds)}..{max(seeds)}")
    print(f"  Robot counts ({len(counts)}): {counts}")
    print(f"  Conditions ({len(conditions)}): {[c['name'] for c in conditions]}")
    print(f"  Policies ({len(policies)}): {policies}")
    print(f"  Total Paired Cases per Arm: {total_combos}")
    print(f"  Parallel Jobs: {jobs}")
    print("-" * 60, flush=True)

    records = []
    completed = 0
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as executor:
            futures = [executor.submit(_eval_single_combo, t) for t in tasks]
            for future in as_completed(futures):
                completed += 1
                combo_recs = future.result()
                records.extend(combo_recs)
                if completed % max(1, total_combos // 10) == 0 or completed == total_combos:
                    elapsed = time.time() - t_start
                    est_total = (elapsed / completed) * total_combos
                    print(f"  Progress: {completed}/{total_combos} combos ({100.0*completed/total_combos:.1f}%) | Elapsed: {elapsed:.1f}s | Est. total: {est_total:.1f}s ({est_total/60.0:.1f} min)", flush=True)
    else:
        for t in tasks:
            completed += 1
            combo_recs = _eval_single_combo(t)
            records.extend(combo_recs)
            if completed % max(1, total_combos // 10) == 0 or completed == total_combos:
                elapsed = time.time() - t_start
                est_total = (elapsed / completed) * total_combos
                print(f"  Progress: {completed}/{total_combos} combos ({100.0*completed/total_combos:.1f}%) | Elapsed: {elapsed:.1f}s | Est. total: {est_total:.1f}s ({est_total/60.0:.1f} min)", flush=True)

    t_total = time.time() - t_start
    df_raw = pd.DataFrame(records)
    raw_path = out_dir / "raw.csv"
    df_raw.to_csv(raw_path, index=False)
    print(f"\nSaved raw results to: {raw_path}", flush=True)

    return df_raw


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
    """Apply Holm-Bonferroni correction."""
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


def analyze_v2_results(raw_path: Path, out_dir: Path):
    """Generate summary.csv, primary.csv, secondary.csv, decomposition.csv, REPORT.md."""
    df_raw = pd.read_csv(raw_path)

    # 1. SUMMARY CSV
    g = df_raw.groupby(["condition", "n_robots", "policy"])[["align_rmse", "pose_rmse", "trust_yield", "accept_rate", "airtime_util", "n_delivered", "n_outliers_delivered"]].agg(["mean", "std", "median"])
    g.columns = [f"{col}_{stat}" for col, stat in g.columns]
    summary_df = g.reset_index()
    summary_df.to_csv(out_dir / "summary.csv", index=False)

    # Align primary arms
    df_emp = df_raw[df_raw.policy == "emrmf_published"].set_index(["condition", "n_robots", "seed"])
    df_plus = df_raw[df_raw.policy == "plus_0.30_6"].set_index(["condition", "n_robots", "seed"])

    common_keys = df_emp.index.intersection(df_plus.index)
    e_align = df_emp.loc[common_keys]["align_rmse"].values
    b_align = df_plus.loc[common_keys]["align_rmse"].values

    valid = np.isfinite(e_align) & np.isfinite(b_align)
    n_pairs = int(valid.sum())

    mean_a = float(np.mean(e_align[valid]))
    mean_b = float(np.mean(b_align[valid]))
    mean_diff = float(np.mean(b_align[valid] - e_align[valid]))

    # % change formulas requested:
    # 1. 100 * (mean_a - mean_b) / mean_b
    pct_change_mean_ratio = float(100.0 * (mean_a - mean_b) / max(mean_b, 1e-9))
    # 2. mean of per-pair % changes: mean(100 * (a_i - b_i) / b_i)
    per_pair_pct = 100.0 * (e_align[valid] - b_align[valid]) / np.maximum(b_align[valid], 1e-9)
    mean_per_pair_pct_change = float(np.mean(per_pair_pct))

    st = wilcoxon(e_align[valid], b_align[valid])
    w_stat, p_val = float(st.statistic), float(st.pvalue)

    c_delta = cliffs_delta(b_align[valid], e_align[valid])
    wins = int((b_align[valid] < e_align[valid] - 1e-6).sum())
    ties = int((np.abs(b_align[valid] - e_align[valid]) <= 1e-6).sum())
    losses = int((b_align[valid] > e_align[valid] + 1e-6).sum())

    cat_a = float(np.mean(e_align[valid] > 0.50))
    cat_b = float(np.mean(b_align[valid] > 0.50))

    primary_df = pd.DataFrame([{
        "comparison": "plus_0.30_6 vs emrmf_published",
        "n_pairs": n_pairs,
        "emrmf_published_mean_rmse": mean_a,
        "plus_0.30_6_mean_rmse": mean_b,
        "mean_paired_diff": mean_diff,
        "pct_change_mean_ratio": pct_change_mean_ratio,
        "mean_per_pair_pct_change": mean_per_pair_pct_change,
        "wilcoxon_W": w_stat,
        "p_value": p_val,
        "cliffs_delta": c_delta,
        "plus_wins": wins,
        "ties": ties,
        "emrmf_wins": losses,
        "emrmf_catastrophic_rate": cat_a,
        "plus_catastrophic_rate": cat_b,
    }])
    primary_df.to_csv(out_dir / "primary.csv", index=False)

    # SECONDARY CSV: per condition & plus vs random
    sec_rows = []
    unadj_p = []
    for c_name in ["L0", "L1", "L2", "L3"]:
        sub_a = df_emp.xs(c_name, level="condition")["align_rmse"].values
        sub_b = df_plus.xs(c_name, level="condition")["align_rmse"].values
        m = np.isfinite(sub_a) & np.isfinite(sub_b)
        n_c = int(m.sum())
        ma, mb = float(np.mean(sub_a[m])), float(np.mean(sub_b[m]))
        if n_c >= 5:
            w_c, p_c = wilcoxon(sub_a[m], sub_b[m])
            w_c, p_c = float(w_c), float(p_c)
        else:
            w_c, p_c = np.nan, np.nan
        unadj_p.append(p_c)
        sec_rows.append({
            "comparison": f"plus_0.30_6 vs emrmf_published ({c_name})",
            "condition": c_name,
            "n_pairs": n_c,
            "mean_a": ma,
            "mean_b": mb,
            "pct_change_mean_ratio": 100.0 * (ma - mb) / max(mb, 1e-9),
            "mean_per_pair_pct": float(np.mean(100.0 * (sub_a[m] - sub_b[m]) / np.maximum(sub_b[m], 1e-9))),
            "wilcoxon_W": w_c,
            "p_unadjusted": p_c,
            "cliffs_delta": cliffs_delta(sub_b[m], sub_a[m]),
            "wins": int((sub_b[m] < sub_a[m] - 1e-6).sum()),
            "losses": int((sub_b[m] > sub_a[m] + 1e-6).sum())
        })

    # Add plus vs random
    df_rand = df_raw[df_raw.policy == "random"].set_index(["condition", "n_robots", "seed"])
    common_rand = df_plus.index.intersection(df_rand.index)
    ra = df_rand.loc[common_rand]["align_rmse"].values
    rb = df_plus.loc[common_rand]["align_rmse"].values
    m_r = np.isfinite(ra) & np.isfinite(rb)
    ma_r, mb_r = float(np.mean(ra[m_r])), float(np.mean(rb[m_r]))
    w_r, p_r = wilcoxon(ra[m_r], rb[m_r])
    unadj_p.append(float(p_r))
    sec_rows.append({
        "comparison": "plus_0.30_6 vs random",
        "condition": "pooled",
        "n_pairs": int(m_r.sum()),
        "mean_a": ma_r,
        "mean_b": mb_r,
        "pct_change_mean_ratio": 100.0 * (ma_r - mb_r) / max(mb_r, 1e-9),
        "mean_per_pair_pct": float(np.mean(100.0 * (ra[m_r] - rb[m_r]) / np.maximum(rb[m_r], 1e-9))),
        "wilcoxon_W": float(w_r),
        "p_unadjusted": float(p_r),
        "cliffs_delta": cliffs_delta(rb[m_r], ra[m_r]),
        "wins": int((rb[m_r] < ra[m_r] - 1e-6).sum()),
        "losses": int((rb[m_r] > ra[m_r] + 1e-6).sum())
    })

    adj_p = holm_adjust(unadj_p)
    for r, p_adj in zip(sec_rows, adj_p):
        r["p_holm"] = float(p_adj)

    secondary_df = pd.DataFrame(sec_rows)
    secondary_df.to_csv(out_dir / "secondary.csv", index=False)

    # DECOMPOSITION CSV
    # emrmf_published -> emrmf_drift -> fifo_defer -> plus_0.30_6
    df_drift = df_raw[df_raw.policy == "emrmf_drift"].set_index(["condition", "n_robots", "seed"])
    df_defer = df_raw[df_raw.policy == "fifo_defer"].set_index(["condition", "n_robots", "seed"])

    m_pub   = df_emp.loc[common_keys]["align_rmse"].values
    m_drift = df_drift.loc[common_keys]["align_rmse"].values
    m_defer = df_defer.loc[common_keys]["align_rmse"].values
    m_plus  = df_plus.loc[common_keys]["align_rmse"].values

    decomp_rows = [
        {
            "step": "1. published -> drift",
            "arm_from": "emrmf_published",
            "arm_to": "emrmf_drift",
            "mechanism": "Effect of drift-derived gamma calibration under FIFO",
            "mean_from": float(np.mean(m_pub)),
            "mean_to": float(np.mean(m_drift)),
            "abs_reduction": float(np.mean(m_pub - m_drift)),
            "pct_reduction": float(100.0 * (np.mean(m_pub) - np.mean(m_drift)) / np.mean(m_pub)),
            "p_val": float(wilcoxon(m_pub, m_drift).pvalue)
        },
        {
            "step": "2. drift -> deferral",
            "arm_from": "emrmf_drift",
            "arm_to": "fifo_defer",
            "mechanism": "Effect of airtime deferral-derived gamma calibration under FIFO",
            "mean_from": float(np.mean(m_drift)),
            "mean_to": float(np.mean(m_defer)),
            "abs_reduction": float(np.mean(m_drift - m_defer)),
            "pct_reduction": float(100.0 * (np.mean(m_drift) - np.mean(m_defer)) / np.mean(m_drift)),
            "p_val": float(wilcoxon(m_drift, m_defer).pvalue)
        },
        {
            "step": "3. deferral -> scheduling (BACS+)",
            "arm_from": "fifo_defer",
            "arm_to": "plus_0.30_6",
            "mechanism": "Effect of bandwidth & observability-aware knapsack scheduling at fixed deferral gamma",
            "mean_from": float(np.mean(m_defer)),
            "mean_to": float(np.mean(m_plus)),
            "abs_reduction": float(np.mean(m_defer - m_plus)),
            "pct_reduction": float(100.0 * (np.mean(m_defer) - np.mean(m_plus)) / np.mean(m_defer)),
            "p_val": float(wilcoxon(m_defer, m_plus).pvalue)
        },
        {
            "step": "Overall Progression",
            "arm_from": "emrmf_published",
            "arm_to": "plus_0.30_6",
            "mechanism": "Total cumulative advancement from published baseline to frozen BACS+",
            "mean_from": float(np.mean(m_pub)),
            "mean_to": float(np.mean(m_plus)),
            "abs_reduction": float(np.mean(m_pub - m_plus)),
            "pct_reduction": float(100.0 * (np.mean(m_pub) - np.mean(m_plus)) / np.mean(m_pub)),
            "p_val": float(wilcoxon(m_pub, m_plus).pvalue)
        }
    ]
    decomp_df = pd.DataFrame(decomp_rows)
    decomp_df.to_csv(out_dir / "decomposition.csv", index=False)

    # FIGURE: fig_bridge.png
    plot_bridge_figure(df_raw, decomp_df, out_dir)

    # REPORT.md
    write_report_markdown(out_dir / "REPORT.md", primary_df, secondary_df, decomp_df, summary_df)


def plot_bridge_figure(df_raw: pd.DataFrame, decomp_df: pd.DataFrame, out_dir: Path):
    """Generate two-panel publication figure fig_bridge.png."""
    plt.rcParams.update({
        'font.sans-serif': 'DejaVu Sans',
        'font.family': 'sans-serif',
        'figure.dpi': 300,
        'savefig.dpi': 300,
        'axes.grid': True,
        'grid.linestyle': '--',
        'grid.alpha': 0.5,
        'font.size': 9,
    })

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))

    # Panel A: Bar chart per arm across conditions
    conds = ["L0", "L1", "L2", "L3"]
    arms = ARMS
    colors = ["#d9534f", "#f0ad4e", "#5bc0de", "#aaaaaa", "#428bca", "#5cb85c"]

    g = df_raw.groupby(["condition", "policy"])["align_rmse"].mean().unstack()
    g = g.reindex(conds)

    x = np.arange(len(conds))
    width = 0.13

    for i, arm in enumerate(arms):
        if arm in g.columns:
            vals = g[arm].to_numpy()
            ax1.bar(x + (i - 2.5) * width, vals, width, label=arm, color=colors[i % len(colors)])

    ax1.set_xticks(x)
    ax1.set_xticklabels(["L0 (Ideal)", "L1 (10% Loss)", "L2 (30% Loss)", "L3 (Burst+Delay)"])
    ax1.set_ylabel("Mean Map-Alignment RMSE [m]")
    ax1.set_title("A. Error Across Wireless Conditions & Arms")
    ax1.legend(fontsize=7, loc="upper left")

    # Panel B: Progression Waterfall / Step chart
    steps = ["Published\n(gamma=0.10)", "Drift\n(gamma=0.033)", "Deferral\n(gamma=0.0045)", "BACS+\n(Scheduling)"]
    means = [
        float(decomp_df.loc[decomp_df["step"] == "1. published -> drift", "mean_from"].values[0]),
        float(decomp_df.loc[decomp_df["step"] == "1. published -> drift", "mean_to"].values[0]),
        float(decomp_df.loc[decomp_df["step"] == "2. drift -> deferral", "mean_to"].values[0]),
        float(decomp_df.loc[decomp_df["step"] == "3. deferral -> scheduling (BACS+)", "mean_to"].values[0]),
    ]
    ax2.plot(steps, means, 'ro-', linewidth=2, markersize=8)
    for i, m in enumerate(means):
        ax2.annotate(f"{m:.3f} m", (steps[i], m), textcoords="offset points", xytext=(0, 10), ha='center', fontweight='bold')

    ax2.set_ylabel("Pooled Mean Map-Alignment RMSE [m]")
    ax2.set_title("B. Progression Mechanism Decomposition")

    plt.tight_layout()
    fig.savefig(out_dir / "fig_bridge.png")
    plt.close(fig)


def write_report_markdown(report_path: Path, primary_df, secondary_df, decomp_df, summary_df):
    """Write REPORT.md starting with exact required primary line."""
    p_row = primary_df.iloc[0]
    pct = p_row["pct_change_mean_ratio"]
    pval = p_row["p_value"]
    status = "CONFIRMED" if pval < 0.05 else "NOT CONFIRMED"

    first_line = f"PRIMARY: BACS+ vs EMRMF (published parameters): {pct:.1f} %, p = {pval:.2e}, {status}"

    content = f"""{first_line}

# EMRMF vs. BACS+ Controlled Bridge V2 Report

## 1. Executive Summary

EMRMF (*Enhanced Multi-Robot Map Fusion*, Saber et al. 2026) established the principle of trust-weighted constraint fusion. In this controlled evaluation, candidate constraint transmission under FIFO is a **modelling assumption** adopted for EMRMF because the published paper did not specify an airtime constraint selection rule under duty-cycle limited channels.

Under the 100% paired protocol over fresh seeds 100–129 ($n=480$ pairs), BACS+ (`plus_0.30_6`) achieved a mean map-alignment RMSE of {p_row['plus_0.30_6_mean_rmse']:.3f} m versus {p_row['emrmf_published_mean_rmse']:.3f} m for published EMRMF (`emrmf_published`).

- **Ratio-based % Change**: {pct:.1f}% error reduction relative to BACS+ baseline ($100 \\times (\\text{{mean}}_a - \\text{{mean}}_b) / \\text{{mean}}_b$).
- **Mean of Per-Pair % Changes**: {p_row['mean_per_pair_pct_change']:.1f}%.
- **Paired Wilcoxon**: $W = {p_row['wilcoxon_W']:.1f}$, $p = {pval:.2e}$.
- **Cliff's Delta**: {p_row['cliffs_delta']:.2f}.
- **Head-to-Head Win Rate**: BACS+ won {int(p_row['plus_wins'])} of {int(p_row['n_pairs'])} paired cases ({100.0*p_row['plus_wins']/p_row['n_pairs']:.1f}%).

---

## 2. Primary Paired Endpoint

{_df_to_markdown(primary_df)}

---

## 3. Secondary Tests (Holm-Adjusted)

{_df_to_markdown(secondary_df)}

---

## 4. Methodological Progression & Mechanism Decomposition

{_df_to_markdown(decomp_df)}

---

## 5. Per-Condition & Scalability Summary

{_df_to_markdown(summary_df.head(20))}
"""
    with open(report_path, "w") as f:
        f.write(content)
    print(f"REPORT.md written to {report_path}")


def main():
    parser = argparse.ArgumentParser(description="Run EMRMF vs BACS+ Bridge V2 Experiment")
    parser.add_argument("--seeds", type=str, default="100-129", help="Seed range (default: 100-129)")
    parser.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 4, help="Number of parallel worker processes")

    args = parser.parse_args()
    out_dir = ROOT / "paper_results" / "revision" / "emrmf_bridge_v2"

    s_low, s_high = map(int, args.seeds.split("-"))
    seeds = range(s_low, s_high + 1)

    # 1. Verify seed freshness
    verify_seed_freshness(seeds)

    # 2. Write prereg.md BEFORE execution
    write_preregistration(out_dir, seeds)

    # 3. Run experiment
    counts = [2, 3, 4, 5]
    df_raw = run_bridge_v2_experiment(seeds, counts, CONDITIONS, ARMS, out_dir, session_s=480.0, jobs=args.jobs)

    # 4. Analyze & generate outputs
    print("\nAnalyzing results and generating summary tables & plots...", flush=True)
    analyze_v2_results(out_dir / "raw.csv", out_dir)
    print("Bridge V2 experiment completed successfully!")


if __name__ == "__main__":
    main()
