"""
Reproducibility Runner for EMRMF vs. BACS+ Controlled Bridge Experiment.

Executes a preregistered paired comparison between the published EMRMF baseline
and the final frozen BACS+ configuration (plus_0.30_6) across identical simulated
environments, ground-truth trajectories, candidate constraint pools, and metrics.

Usage:
  python scripts/revision/run_emrmf_bacs_bridge.py --quick
  python scripts/revision/run_emrmf_bacs_bridge.py --full [--jobs N]
"""
import os
import sys
import time
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
import numpy as np
import pandas as pd

# Ensure workspace root is in path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bacs_sim.config import SimConfig
from bacs_sim.simulator import run, precompute


CONDITIONS = [
    {"name": "C0", "model": "independent", "loss": 0.0,  "delay": 0.0},
    {"name": "C1", "model": "independent", "loss": 0.10, "delay": 0.0},
    {"name": "C2", "model": "independent", "loss": 0.30, "delay": 0.0},
    {"name": "C3", "model": "burst",       "loss": 0.30, "delay": 0.20},
]


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

    # Policy configuration
    if policy_name == "emrmf_reference":
        cfg.scheduler.policy = "emrmf_reference"
        cfg.trust.gamma_rule = "derived"
        cfg.scheduler.use_observability = False
        cfg.scheduler.trust_gate = 0.0
    elif policy_name == "bacs_plus":
        cfg.scheduler.policy = "bacs_plus"
        cfg.trust.gamma_rule = "deferral_derived"
        cfg.infogain.w_obs = 0.30
        cfg.infogain.obs_ref = 6.0
        cfg.scheduler.use_observability = True
        cfg.scheduler.trust_gate = 0.05
    elif policy_name == "fifo":
        cfg.scheduler.policy = "fifo"
        cfg.trust.gamma_rule = "deferral_derived"
        cfg.scheduler.use_observability = False
        cfg.scheduler.trust_gate = 0.0
    elif policy_name == "random":
        cfg.scheduler.policy = "random"
        cfg.trust.gamma_rule = "deferral_derived"
        cfg.scheduler.use_observability = False
        cfg.scheduler.trust_gate = 0.0
    elif policy_name == "bacs_gated":
        cfg.scheduler.policy = "bacs_gated"
        cfg.trust.gamma_rule = "deferral_derived"
        cfg.scheduler.use_observability = False
        cfg.scheduler.trust_gate = 0.05
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


def run_bridge_experiment(seeds, counts, conditions, policies, out_dir: Path, session_s: float = 480.0, jobs: int = 1):
    """Run paired evaluations over precomputed world data."""
    t_start = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []

    tasks = [(cond, n, s, policies, session_s)
             for cond in conditions for n in counts for s in seeds]
    total_combos = len(tasks)

    print(f"Starting EMRMF vs BACS+ Bridge Experiment")
    print(f"  Seeds ({len(seeds)}): {min(seeds)}..{max(seeds)}")
    print(f"  Robot counts ({len(counts)}): {counts}")
    print(f"  Conditions ({len(conditions)}): {[c['name'] for c in conditions]}")
    print(f"  Policies ({len(policies)}): {policies}")
    print(f"  Total Paired Cases per Arm: {total_combos}")
    print(f"  Parallel Jobs: {jobs}")
    print("-" * 60)

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
                    print(f"  Progress: {completed}/{total_combos} combos ({100.0*completed/total_combos:.1f}%) | Elapsed: {elapsed:.1f}s | Est. total: {est_total:.1f}s ({est_total/60.0:.1f} min)")
    else:
        for t in tasks:
            completed += 1
            combo_recs = _eval_single_combo(t)
            records.extend(combo_recs)
            if completed % max(1, total_combos // 10) == 0 or completed == total_combos:
                elapsed = time.time() - t_start
                est_total = (elapsed / completed) * total_combos
                print(f"  Progress: {completed}/{total_combos} combos ({100.0*completed/total_combos:.1f}%) | Elapsed: {elapsed:.1f}s | Est. total: {est_total:.1f}s ({est_total/60.0:.1f} min)")

    t_total = time.time() - t_start
    df_raw = pd.DataFrame(records)
    raw_path = out_dir / "raw.csv"
    df_raw.to_csv(raw_path, index=False)
    print(f"\nSaved raw results to: {raw_path}")

    # Write runtime metadata
    runtime_path = out_dir / "runtime.txt"
    with open(runtime_path, "w") as f:
        f.write(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total execution time: {t_total:.2f} seconds ({t_total/60.0:.2f} minutes)\n")
        f.write(f"Parallel jobs: {jobs}\n")
        f.write(f"Total simulation runs: {len(df_raw)}\n")
        f.write(f"Seeds: {min(seeds)}..{max(seeds)}\n")
        f.write(f"Robot counts: {counts}\n")
        f.write(f"Conditions: {[c['name'] for c in conditions]}\n")

    return df_raw


def main():
    parser = argparse.ArgumentParser(description="Run EMRMF vs BACS+ Controlled Bridge Experiment")
    parser.add_argument("--quick", action="store_true", help="Run quick smoke test (2 seeds, N=2, C0)")
    parser.add_argument("--full", action="store_true", help="Run full preregistered 480-pair experiment (seeds 70-99, N=2-5, C0-C3)")
    parser.add_argument("--seeds", type=str, default=None, help="Custom seed range, e.g., '70-99'")
    parser.add_argument("--jobs", "-j", type=int, default=os.cpu_count() or 4, help="Number of parallel worker processes (default: all CPU cores)")
    parser.add_argument("--outdir", type=str, default=None, help="Output directory path")

    args = parser.parse_args()

    out_dir = Path(args.outdir) if args.outdir else ROOT / "paper_results" / "revision" / "emrmf_bacs_bridge"

    if args.quick:
        seeds = range(70, 72)
        counts = [2]
        conditions = CONDITIONS[:1]
        policies = ["emrmf_reference", "bacs_plus", "fifo"]
        session_s = 240.0
        jobs = 1
        print("=== RUNNING QUICK SMOKE TEST ===")
    elif args.full or args.seeds:
        if args.seeds:
            s_low, s_high = map(int, args.seeds.split("-"))
            seeds = range(s_low, s_high + 1)
        else:
            seeds = range(70, 100)
        counts = [2, 3, 4, 5]
        conditions = CONDITIONS
        policies = ["emrmf_reference", "bacs_plus", "fifo", "random", "bacs_gated"]
        session_s = 480.0
        jobs = max(1, args.jobs)
        print(f"=== RUNNING FULL PREREGISTERED EXPERIMENT (Parallel Jobs: {jobs}) ===")
    else:
        seeds = range(70, 72)
        counts = [2]
        conditions = CONDITIONS[:1]
        policies = ["emrmf_reference", "bacs_plus", "fifo"]
        session_s = 240.0
        jobs = 1
        print("No mode specified. Defaulting to --quick smoke test.")

    df_raw = run_bridge_experiment(seeds, counts, conditions, policies, out_dir, session_s=session_s, jobs=jobs)
    print("Experiment completed successfully.")


if __name__ == "__main__":
    main()
