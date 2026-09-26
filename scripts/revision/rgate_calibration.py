#!/usr/bin/env python3
"""Residual-gated BACS / BACS+ (BACS-RG, BACS+-RG): two-stage DEV calibration.

    python3 scripts/revision/rgate_calibration.py stageA [--workers 8]   # tau_r and bootstrap k
    python3 scripts/revision/rgate_calibration.py stageB [--workers 8]   # alpha, at the frozen stage-A gate

Method: reject first, then rank.
  admission  r_c <= tau_r   (raw predicted residual vs the fused map), applied only once the
             robot pair has >= k delivered constraints (before that the frames are not aligned
             and every residual is large: without this bootstrap the gate deadlocks);
  priority   S_c = I_hat(+)_c * theta_hat_c**alpha / T_air(c)   (alpha = 0: BACS / BACS+ density);
  fusion     theta_c * Omega_c at the server (unchanged).

Protocol (fixed before running): DEV seeds 0-9, N = 2, 3, 4, 5, conditions C0-C3 exactly as in
paper_results/revision/ranking_v2_c0c3/conditions.json (same overrides and gamma), 480 s.
  Stage A: alpha = 0. Arms: Random, BACS, BACS+, BACS+-RG(tau, k) for tau in {0.3, 0.5, 0.75, 1.0}
           and k in {0, 3}, BACS-RG(tau, k=3). Selection: the RG arm with the lowest mean
           map-alignment RMSE pooled over C0-C3 x 40 seed-team pairs -> decision_stageA.md.
  Stage B: the frozen stage-A gate with alpha in {0.1, 0.2, 0.5}, plus alpha = 0 (reused).
           Selection: the lowest pooled DEV mean, alpha = 0 included -> decision.md.
Each decision file is written once and never overwritten. TEST (seeds 40-69) is a later step.
Outputs: paper_results/revision/rgate/ (per-cell cache in _cells/, git-ignored).
"""
from __future__ import annotations

import os

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):  # one BLAS thread per worker
    os.environ.setdefault(_v, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import pickle  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor, as_completed  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from bacs_sim.experiments import _mk, s8_config  # noqa: E402
from bacs_sim.simulator import precompute, run  # noqa: E402
from stats import describe  # noqa: E402

OUT = ROOT / "paper_results" / "revision" / "rgate"
CELLS = OUT / "_cells"
CONDITIONS_FILE = ROOT / "paper_results" / "revision" / "ranking_v2_c0c3" / "conditions.json"
CONDS = ["C0", "C1", "C2", "C3"]
DEV_SEEDS, COUNTS, SESSION_S = range(0, 10), (2, 3, 4, 5), 480.0
TAUS, KS, ALPHAS = (0.3, 0.5, 0.75, 1.0), (0, 3), (0.1, 0.2, 0.5)
N_WEIGHT = {2: 1.0, 3: 1.33, 4: 1.94, 5: 3.9}   # relative cell cost, for the time estimate


def arm_name(info: str, tau: float, k: int, alpha: float = 0.0) -> str:
    base = "BACS+-RG" if info == "plus" else "BACS-RG"
    return f"{base}(tau={tau:g},k={k}" + (f",alpha={alpha:g})" if alpha else ")")


def parse_arm(name: str) -> dict:
    """Arm name -> configuration. Controls map to the existing S8 arms."""
    controls = {"Random": "random", "BACS": "bacs_gated", "BACS+": "plus_0.30_6"}
    if name in controls:
        return dict(base=controls[name], policy=None)
    m = re.fullmatch(r"(BACS\+?)-RG\(tau=([\d.]+),k=(\d+)(?:,alpha=([\d.]+))?\)", name)
    plus = m.group(1) == "BACS+"
    return dict(base="plus_0.30_6" if plus else "bacs_gated", policy="plus_rgate" if plus else "rgate",
                tau=float(m.group(2)), k=int(m.group(3)), alpha=float(m.group(4) or 0.0))


def stage_a_arms() -> list[str]:
    return (["Random", "BACS", "BACS+"] + [arm_name("plus", t, k) for t in TAUS for k in KS]
            + [arm_name("base", t, 3) for t in TAUS])


def conditions() -> dict:
    return json.loads(CONDITIONS_FILE.read_text())


def configure(arm: str, seed: int, n: int, cond: dict):
    spec = parse_arm(arm)
    c = s8_config(spec["base"], seed, n, SESSION_S)
    for key, value in cond["overrides"].items():
        obj, attr = key.split(".", 1)
        setattr(getattr(c, obj), attr, value)
    c.trust.t_defer_prior = float(cond["t_defer"])
    if spec["policy"]:
        c.scheduler.policy = spec["policy"]
        c.scheduler.residual_gate, c.scheduler.gate_min_pair = spec["tau"], spec["k"]
        c.scheduler.trust_alpha = spec["alpha"]
    return c


def _path(stage, cname, seed, n):
    return CELLS / stage / cname / f"{seed}_{n}.pkl"


def run_cell(job):
    stage, cname, cond, seed, n, arms = job
    path = _path(stage, cname, seed, n)
    if path.exists():
        return cname, seed, n, 0.0, True
    t0 = time.time()
    base = _mk(seed=seed, n_robots=n)
    base.world.session_s = SESSION_S
    pre = precompute(base)
    rows = []
    for arm in arms:
        r = run(configure(arm, seed, n, cond), precomputed=pre, collect_tx=True, iexact_fraction=0.0)
        tx = pd.DataFrame(r.extras["tx_log"])
        g = r.extras["gate_counts"]
        out = tx[tx.is_outlier] if len(tx) else tx
        theta_all = tx.theta_arrival.sum() if len(tx) else 0.0
        rows.append(dict(
            condition=cname, seed=seed, n_robots=n, arm=arm, align_rmse=r.align_rmse, pose_rmse=r.pose_rmse,
            trust_yield=r.trust_yield, n_sent=r.n_sent, n_delivered=r.n_delivered, airtime_util=r.airtime_util,
            outliers_sent=len(out),
            outlier_airtime_share=float(out.T_air.sum() / tx.T_air.sum()) if len(tx) else math.nan,
            outlier_trust_share=float(out.theta_arrival.sum() / theta_all) if theta_all > 0 else math.nan,
            outlier_eval=g["outlier_eval"], outlier_rejected=g["outlier_rejected"],
            inlier_eval=g["inlier_eval"], inlier_rejected=g["inlier_rejected"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as handle:
        pickle.dump(rows, handle)
    os.replace(tmp, path)
    return cname, seed, n, time.time() - t0, False


def execute(stage, arms, workers):
    cond = conditions()
    jobs = [(stage, c, cond[c], s, n, arms) for c in CONDS for s in DEV_SEEDS for n in COUNTS]
    todo = [j for j in jobs if not _path(stage, j[1], j[3], j[4]).exists()]
    todo_w = sum(N_WEIGHT[j[4]] for j in todo)
    print(f"[{stage}] {len(arms)} arms; {len(todo)} of {len(jobs)} cells to compute, {workers} workers", flush=True)
    done_w, t0, done = 0.0, time.time(), 0
    jobs.sort(key=lambda j: -j[4])
    with ProcessPoolExecutor(workers) as pool:
        for fut in as_completed([pool.submit(run_cell, j) for j in jobs]):
            cname, seed, n, dt, cached = fut.result()
            done += 1
            if not cached:
                done_w += N_WEIGHT[n]
            el = time.time() - t0
            eta = f"{(todo_w - done_w) * el / done_w / 60:.0f} min" if done_w else "estimating..."
            print(f"[{stage}] {done}/{len(jobs)} {cname} seed={seed} N={n} "
                  f"{'cached' if cached else f'{dt:.0f}s'} | elapsed {el / 60:.1f} min, remaining ~{eta}", flush=True)
    with (OUT / f"runtime_{stage}.txt").open("a") as handle:
        handle.write(f"{stage}: {len(jobs)} cells ({len(todo)} computed), wall {time.time() - t0:.0f} s, "
                     f"{workers} workers ({time.strftime('%Y-%m-%d %H:%M')})\n")
    rows = []
    for c in CONDS:
        for s in DEV_SEEDS:
            for n in COUNTS:
                rows += pickle.load(_path(stage, c, s, n).open("rb"))
    return pd.DataFrame(rows)


def calibration(raw: pd.DataFrame) -> pd.DataFrame:
    out = []
    for cname, d in list(raw.groupby("condition")) + [("pooled", raw)]:
        for arm, g in d.groupby("arm", sort=False):
            a = describe(g.align_rmse)
            out.append(dict(condition=cname, arm=arm, n=a["n"], align_mean=a["mean"], align_sd=a["sd"],
                            align_ci95_lo=a["ci95_lo"], align_ci95_hi=a["ci95_hi"], align_median=a["median"],
                            align_runs_over_0_5m=float((g.align_rmse > 0.5).mean()),
                            outliers_rejected=g.outlier_rejected.sum() / max(g.outlier_eval.sum(), 1),
                            inliers_rejected=g.inlier_rejected.sum() / max(g.inlier_eval.sum(), 1),
                            outliers_sent_per_run=g.outliers_sent.mean(),
                            outlier_airtime_share=g.outlier_airtime_share.mean(),
                            outlier_trust_share=g.outlier_trust_share.mean(),
                            n_delivered=g.n_delivered.mean(), pose_mean=g.pose_rmse.mean()))
    return pd.DataFrame(out)


def md_table(cal: pd.DataFrame, cond: str) -> str:
    d = cal[cal.condition == cond]
    lines = ["| arm | align mean (m) | 95% CI | runs > 0.5 m | outliers rejected | inliers rejected | "
             "outlier share of airtime | outlier share of trust |", "|---|---|---|---|---|---|---|---|"]
    for r in d.itertuples():
        lines.append(f"| {r.arm} | {r.align_mean:.4f} | [{r.align_ci95_lo:.4f}, {r.align_ci95_hi:.4f}] | "
                     f"{100 * r.align_runs_over_0_5m:.0f} % | {100 * r.outliers_rejected:.0f} % | "
                     f"{100 * r.inliers_rejected:.1f} % | {100 * r.outlier_airtime_share:.1f} % | "
                     f"{100 * r.outlier_trust_share:.1f} % |")
    return "\n".join(lines)


def write_decision(path: Path, stage: str, rule: str, cal: pd.DataFrame, candidates: list[str]) -> str:
    pooled = cal[cal.condition == "pooled"].set_index("arm")
    chosen = pooled.loc[candidates, "align_mean"].idxmin()
    if path.exists():
        print(f"{path.name} already exists; not rewritten")
        return re.search(r"Chosen arm: `(.+?)`", path.read_text()).group(1)
    per_cond = cal.pivot_table(index="arm", columns="condition", values="align_mean").loc[pooled.index]
    lines = [f"# Residual-gate calibration: {stage} decision", "",
             f"Written {time.strftime('%Y-%m-%d %H:%M:%S %Z')} from DEV seeds 0-9 only, before any TEST run.",
             f"Rule (fixed in scripts/revision/rgate_calibration.py before running): {rule}", "",
             f"**Chosen arm: `{chosen}`**", "",
             "Pooled over C0-C3 x 40 seed-team pairs:", "", md_table(cal, "pooled"), "",
             "Mean map-alignment RMSE per condition (m):", "",
             "| arm | " + " | ".join(CONDS) + " | pooled |", "|---|" + "---|" * (len(CONDS) + 1)]
    for arm, r in per_cond.iterrows():
        lines.append(f"| {arm} | " + " | ".join(f"{r[c]:.4f}" for c in CONDS) + f" | {pooled.loc[arm, 'align_mean']:.4f} |")
    lines += ["", "This file is not modified after it is written."]
    path.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return chosen


def stage_a(workers):
    arms = stage_a_arms()
    raw = execute("stageA", arms, workers)
    raw.to_csv(OUT / "stageA_raw.csv", index=False, lineterminator="\n")
    cal = calibration(raw)
    cal.to_csv(OUT / "stageA_calibration.csv", index=False, lineterminator="\n")
    rg = [a for a in arms if "-RG" in a]
    write_decision(OUT / "decision_stageA.md", "Stage A (tau_r, k; alpha = 0)",
                   "among the BACS-RG and BACS+-RG arms, the lowest mean map-alignment RMSE pooled over "
                   "C0-C3 x DEV seeds 0-9 x N = 2-5 (160 runs per arm).", cal, rg)


def stage_b(workers):
    dec = OUT / "decision_stageA.md"
    if not dec.exists():
        sys.exit("decision_stageA.md missing: run stageA first")
    chosen = re.search(r"Chosen arm: `(.+?)`", dec.read_text()).group(1)
    spec = parse_arm(chosen)
    info = "plus" if spec["policy"] == "plus_rgate" else "base"
    arms = [chosen] + [arm_name(info, spec["tau"], spec["k"], a) for a in ALPHAS]
    raw_b = execute("stageB", arms[1:], workers)
    raw_a = pd.read_csv(OUT / "stageA_raw.csv")
    raw = pd.concat([raw_a[raw_a.arm.isin(["Random", "BACS", "BACS+", chosen])], raw_b], ignore_index=True)
    raw.to_csv(OUT / "stageB_raw.csv", index=False, lineterminator="\n")
    cal = calibration(raw)
    cal.to_csv(OUT / "stageB_calibration.csv", index=False, lineterminator="\n")
    write_decision(OUT / "decision.md", "Stage B (alpha at the frozen stage-A gate)",
                   f"among {chosen} (alpha = 0) and the same gate with alpha in {list(ALPHAS)}, the lowest mean "
                   "map-alignment RMSE pooled over C0-C3 x DEV seeds 0-9 x N = 2-5.", cal, arms)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["stageA", "stageB"])
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ".gitignore").write_text("_cells/\n")
    {"stageA": stage_a, "stageB": stage_b}[a.stage](a.workers)


if __name__ == "__main__":
    main()
