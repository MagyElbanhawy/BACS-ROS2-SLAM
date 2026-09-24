#!/usr/bin/env python3
"""
Definitive S8: does the observability term's validated ranking improvement
(S7-C) translate into end-to-end map-fusion error?

Held-out seeds (default 10..39, disjoint from the 0..7 used for screening),
N in {2,3,4,5}, all arms on the corrected deferral-derived gamma. Two BACS+
settings are included so the parameter choice is decided by the data:
  - plus_0.30_6   : w_obs=0.30, obs_ref=6.0  (the setting S7-C validated)
  - plus_0.60_5   : w_obs=0.60, obs_ref=5.0, base weights renormalised to 0.4x
                    (the earlier screening setting)

Writes paper_results/s8_30seed_raw.csv (one row per seed x N x arm) and prints a
stats table: mean/median/SD/95% CI pose & align RMSE, paired Wilcoxon p and
Cliff's delta for plus-vs-fifo and plus-vs-gated.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bacs_sim import SimConfig, run, precompute
from bacs_sim.experiments import summary_stats, cliffs_delta

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "paper_results")


def base_cfg(n, seed, session_s):
    c = SimConfig()
    c.seed = seed
    c.world.n_robots = n
    c.world.session_s = session_s
    c.trust.gamma_rule = "deferral_derived"
    return c


def build(arm, n, seed, session_s):
    c = base_cfg(n, seed, session_s)
    if arm == "fifo":
        c.scheduler.policy = "fifo"
    elif arm == "bacs_gated":
        c.scheduler.policy = "bacs_gated"
    elif arm == "plus_0.30_6":
        c.scheduler.policy = "bacs_plus"
        c.infogain.w_obs, c.infogain.obs_ref = 0.30, 6.0
    elif arm == "plus_0.60_5":
        c.scheduler.policy = "bacs_plus"
        c.infogain.w_obs, c.infogain.obs_ref = 0.60, 5.0
        c.infogain.w_novelty, c.infogain.w_degree, c.infogain.w_loop = 0.20, 0.08, 0.12
    else:
        raise ValueError(arm)
    return c


ARMS = ["fifo", "bacs_gated", "plus_0.30_6", "plus_0.60_5"]


def paired(df, n, a, b, metric="pose_rmse"):
    """Paired Wilcoxon + Cliff's delta of (a - b) on metric, aligned by seed."""
    from scipy.stats import wilcoxon
    da = df[(df.n_robots == n) & (df.arm == a)].sort_values("seed")[metric].values
    db = df[(df.n_robots == n) & (df.arm == b)].sort_values("seed")[metric].values
    m = np.isfinite(da) & np.isfinite(db)
    if m.sum() < 5 or np.allclose(da[m], db[m]):
        return dict(p=np.nan, delta=cliffs_delta(da[m], db[m]),
                    a_mean=float(np.mean(da[m])), b_mean=float(np.mean(db[m])))
    st = wilcoxon(da[m], db[m])
    return dict(p=float(st.pvalue), delta=cliffs_delta(da[m], db[m]),
                a_mean=float(np.mean(da[m])), b_mean=float(np.mean(db[m])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lo", type=int, default=10)
    ap.add_argument("--hi", type=int, default=40)   # exclusive -> 30 seeds
    ap.add_argument("--session", type=float, default=480.0)
    ap.add_argument("--counts", type=int, nargs="+", default=[2, 3, 4, 5])
    args = ap.parse_args()
    seeds = range(args.lo, args.hi)
    os.makedirs(OUT, exist_ok=True)

    rows = []
    for n in args.counts:
        for s in seeds:
            pre = precompute(base_cfg(n, s, args.session))
            for arm in ARMS:
                r = run(build(arm, n, s, args.session), precomputed=pre)
                rows.append(dict(n_robots=n, seed=s, arm=arm,
                                 pose_rmse=r.pose_rmse, align_rmse=r.align_rmse,
                                 trust_yield=r.trust_yield, n_delivered=r.n_delivered))
        print(f"[N={n}] done ({len(list(seeds))} seeds x {len(ARMS)} arms)", flush=True)

    df = pd.DataFrame(rows)
    raw = os.path.join(OUT, "s8_30seed_raw.csv")
    df.to_csv(raw, index=False)
    print(f"raw -> {raw}\n")
    write_tables(df, args.counts)


def write_tables(df, counts):
    """Derive the frozen summary + paired-test tables. PRIMARY metric is
    align_rmse (map-fusion consistency); pose_rmse is secondary."""
    summ_rows, test_rows = [], []

    print(f"{'N':>2} {'arm':>12} | {'ALIGN mean':>10} {'median':>8} {'SD':>7} "
          f"{'95% CI':>17} | {'pose mean':>9} {'pose SD':>7}")
    for n in counts:
        for arm in ARMS:
            al = df[(df.n_robots == n) & (df.arm == arm)]["align_rmse"].values
            po = df[(df.n_robots == n) & (df.arm == arm)]["pose_rmse"].values
            a, p = summary_stats(al), summary_stats(po)
            summ_rows.append(dict(n_robots=n, arm=arm,
                                  align_mean=a["mean"], align_median=a["median"],
                                  align_sd=a["std"], align_ci_lo=a["ci_lo"],
                                  align_ci_hi=a["ci_hi"], pose_mean=p["mean"],
                                  pose_median=p["median"], pose_sd=p["std"]))
            print(f"{n:>2} {arm:>12} | {a['mean']:>10.4f} {a['median']:>8.4f} "
                  f"{a['std']:>7.4f} [{a['ci_lo']:.4f},{a['ci_hi']:.4f}] | "
                  f"{p['mean']:>9.4f} {p['std']:>7.4f}")

    print("\nPaired tests (PRIMARY align_rmse; negative delta => first arm better):")
    for n in counts:
        for a, b in [("bacs_gated", "fifo"), ("plus_0.30_6", "fifo"),
                     ("plus_0.60_5", "fifo"), ("plus_0.30_6", "bacs_gated")]:
            for metric in ("align_rmse", "pose_rmse"):
                r = paired(df, n, a, b, metric=metric)
                imp = 100 * (r["b_mean"] - r["a_mean"]) / r["b_mean"] if r["b_mean"] else float("nan")
                test_rows.append(dict(n_robots=n, metric=metric, arm_a=a, arm_b=b,
                                      a_mean=r["a_mean"], b_mean=r["b_mean"],
                                      improvement_pct=imp, wilcoxon_p=r["p"],
                                      cliffs_delta=r["delta"]))
                if metric == "align_rmse":
                    sig = "*" if (r["p"] == r["p"] and r["p"] < 0.05) else " "
                    print(f"  N={n} {a:>12} vs {b:>10} [align]: {r['a_mean']:.4f} vs "
                          f"{r['b_mean']:.4f} ({imp:+.1f}%) p={r['p']:.3g}{sig} "
                          f"delta={r['delta']:+.2f}")

    pd.DataFrame(summ_rows).to_csv(os.path.join(OUT, "s8_30seed_summary.csv"), index=False)
    pd.DataFrame(test_rows).to_csv(os.path.join(OUT, "s8_30seed_tests.csv"), index=False)
    print("\nsummary -> paper_results/s8_30seed_summary.csv")
    print("tests   -> paper_results/s8_30seed_tests.csv")
    print("done")


if __name__ == "__main__":
    main()
