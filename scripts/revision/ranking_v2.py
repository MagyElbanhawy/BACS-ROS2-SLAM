#!/usr/bin/env python3
"""Ranking v2, C0-C3 study (tw_now / tw_arrival / tw_arrival_sub): does ranking by
expected effective information at the server beat random?

Independent of the *_tw study in scripts/revision/run_ranking_v2.py, whose outputs
live in paper_results/revision/ranking_v2/; this study's outputs live in
paper_results/revision/ranking_v2_c0c3/ (conditions: C0 nominal, C1 duty 0.5 %,
C2 SF9, C3 20 % loss).

    python scripts/revision/ranking_v2.py pilot            # T_defer -> gamma for C1-C3 (DEV seeds)
    python scripts/revision/ranking_v2.py dev              # DEV seeds 0-9, C0; writes decision.md once
    python scripts/revision/ranking_v2.py test C0 C3 ...   # TEST seeds 40-69 (needs decision.md)
    python scripts/revision/ranking_v2.py analyze          # tables, figures (see ranking_v2_analysis.py)

All outputs go to paper_results/revision/ranking_v2_c0c3/. Per-cell results are cached in
ranking_v2_c0c3/_cells/ so an interrupted run resumes where it stopped.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from bacs_sim.experiments import S8_ARMS, _mk, s8_config  # noqa: E402
from bacs_sim.simulator import precompute, run  # noqa: E402

OUT = ROOT / "paper_results" / "revision" / "ranking_v2_c0c3"
CELLS = OUT / "_cells"
TW = ["tw_now", "tw_arrival", "tw_arrival_sub"]
for _p in TW:  # I_hat_plus with w_o = 0.30, n_ref = 6
    S8_ARMS.setdefault(_p, (_p, dict(w_obs=0.30, obs_ref=6.0)))
DEV_SEEDS, TEST_SEEDS, COUNTS, SESSION_S = range(0, 10), range(40, 70), (2, 3, 4, 5), 480.0
DEV_POLICIES = ["fifo", "random", "info_only", "bacs_gated", "plus_0.30_6"] + TW
TEST_POLICIES = ["fifo", "lifo", "random", "trust_only", "info_only", "bacs_gated", "plus_0.30_6"] + TW
T_DEFER_C0 = 155.0  # S8 setup: deferral-derived gamma = ln2/155
# Condition -> overrides of existing SimConfig fields. conditions.json (written by
# `pilot`, possibly edited by the user's C1/C2 decision) adds t_defer and any
# further overrides; see REPORT.md.
# C1/C2 at the specified W = 60 s transmit nothing (C1 at N >= 3, C2 at any N):
# the per-window budget delta*W/N is below one packet's T_air and budgets do not
# carry over. Per the user's decision the window is lengthened (existing
# scheduler.window_s) so the per-window budget matches C0's scale:
# C1 W = 120 s (same budget as C0), C2 W = 200 s (fits one SF9 52-byte packet at N = 5).
BASE_CONDITIONS = {
    "C0": {},
    "C1": {"lora.duty_cycle": 0.005, "scheduler.window_s": 120.0},
    "C2": {"lora.sf": 9, "scheduler.window_s": 200.0},
    "C3": {"channel.loss_rate": 0.20},
}


def conditions() -> dict:
    path = OUT / "conditions.json"
    cond = {k: {"overrides": dict(v), "t_defer": T_DEFER_C0 if k == "C0" else None} for k, v in BASE_CONDITIONS.items()}
    if path.exists():
        cond.update(json.loads(path.read_text()))
    return cond


def configure(arm: str, seed: int, n: int, cond: dict):
    c = s8_config(arm, seed, n, SESSION_S)
    for key, value in cond["overrides"].items():
        obj, attr = key.split(".", 1)
        setattr(getattr(c, obj), attr, value)
    if cond.get("t_defer"):
        c.trust.t_defer_prior = float(cond["t_defer"])
    return c


def run_cell(job):
    phase, cname, cond, seed, n, policies, iexact = job
    path = CELLS / phase / cname / f"{seed}_{n}.pkl"
    if path.exists():
        return cname, seed, n, 0.0, True
    t0 = time.time()
    base = _mk(seed=seed, n_robots=n)
    base.world.session_s = SESSION_S
    pre = precompute(base)
    rows, txs = [], []
    for arm in policies:
        ts = time.time()
        r = run(configure(arm, seed, n, cond), precomputed=pre, collect_tx=True, iexact_fraction=iexact)
        log = pd.DataFrame(r.extras["tx_log"])
        tx_age = (log.t_sent - log.t_gen) if len(log) else pd.Series(dtype=float)
        rows.append(dict(condition=cname, seed=seed, n_robots=n, policy=arm, align_rmse=r.align_rmse,
                         pose_rmse=r.pose_rmse, trust_yield=r.trust_yield, n_delivered=r.n_delivered,
                         n_sent=r.n_sent, airtime_util=r.airtime_util,
                         median_age_tx=float(tx_age.median()) if len(log) else math.nan,
                         median_age_arrival=float(log.actual_arrival_age.median()) if len(log) else math.nan,
                         mean_R=float(log.R.mean()) if len(log) else math.nan,
                         gamma=r.gamma_final, runtime_s=time.time() - ts))
        if len(log):
            log.insert(0, "policy", arm); log.insert(0, "n_robots", n); log.insert(0, "seed", seed)
            log.insert(0, "condition", cname)
            txs.append(log)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as handle:
        pickle.dump((rows, pd.concat(txs) if txs else pd.DataFrame()), handle)
    os.replace(tmp, path)
    return cname, seed, n, time.time() - t0, False


def execute(phase, jobs, workers):
    by_cond = {}
    for j in jobs:
        by_cond.setdefault(j[1], []).append(j)
    for cname, cj in by_cond.items():
        cj.sort(key=lambda j: -j[4])  # largest N first for load balance
        t0, done, total = time.time(), 0, len(cj)
        print(f"[{phase}] {cname}: {total} cells x {len(cj[0][5])} policies", flush=True)
        with ProcessPoolExecutor(workers) as pool:
            for fut in as_completed([pool.submit(run_cell, j) for j in cj]):
                _, seed, n, dt, cached = fut.result()
                done += 1
                el = time.time() - t0
                print(f"[{phase}] {cname} {done}/{total} seed={seed} N={n} "
                      f"{'cached' if cached else f'{dt:.0f}s'} elapsed {el / 60:.1f} min "
                      f"eta {el / done * (total - done) / 60:.1f} min", flush=True)
        with (OUT / f"runtime_{phase}_{cname}.txt").open("a") as handle:  # one line per invocation
            handle.write(f"{phase} {cname}: {total} cells, wall {time.time() - t0:.0f} s in this invocation "
                         f"({time.strftime('%Y-%m-%d %H:%M')}), {workers} workers\n")


def collect(phase, cname):
    rows, txs = [], []
    for p in sorted((CELLS / phase / cname).glob("*.pkl")):
        r, t = pickle.load(p.open("rb"))
        rows += r
        if len(t):
            txs.append(t)
    return pd.DataFrame(rows), (pd.concat(txs, ignore_index=True) if txs else pd.DataFrame())


def pilot(workers):
    cond = conditions()
    jobs = [("pilot", c, cond[c], s, n, ["bacs_gated"], 0.0) for c in cond for s in DEV_SEEDS for n in COUNTS]
    execute("pilot", jobs, workers)
    rows, table = {}, []
    for c in cond:
        raw, tx = collect("pilot", c)
        d = (tx.t_sent - tx.t_gen) if len(tx) else pd.Series(dtype=float)
        # T_defer = MEAN scheduling deferral of transmitted constraints. The median is
        # degenerate here: the simulator adds a window's candidates at the window
        # start and sends those created later in the window at their creation
        # time, so many transmissions have zero deferral (C1 pilot median = 0 s).
        tdefer = float(d.mean()) if len(d) else math.nan
        table.append(dict(condition=c, overrides=json.dumps(cond[c]["overrides"]), n_transmitted=len(d),
                          deferral_median_s=float(d.median()) if len(d) else math.nan, deferral_mean_s=tdefer,
                          gamma_if_used=math.log(2) / tdefer if len(d) and tdefer > 0 else math.nan,
                          zero_deferral_share=float((d == 0).mean()) if len(d) else math.nan,
                          cells_with_zero_tx=int((raw.n_sent == 0).sum()), cells=len(raw)))
        if c != "C0":
            rows[c] = dict(overrides=cond[c]["overrides"], t_defer=tdefer if len(d) else None)
    pd.DataFrame(table).to_csv(OUT / "pilot_tdefer.csv", index=False, lineterminator="\n")
    existing = json.loads((OUT / "conditions.json").read_text()) if (OUT / "conditions.json").exists() else {}
    existing.update(rows)
    existing["C0"] = dict(overrides={}, t_defer=T_DEFER_C0)
    (OUT / "conditions.json").write_text(json.dumps(existing, indent=2) + "\n")
    print(pd.DataFrame(table).to_string(index=False))


def dev(workers):
    cond = conditions()["C0"]
    jobs = [("dev", "C0", cond, s, n, DEV_POLICIES, 1.0) for s in DEV_SEEDS for n in COUNTS]
    execute("dev", jobs, workers)
    raw, tx = collect("dev", "C0")
    raw.to_csv(OUT / "dev_raw.csv", index=False, lineterminator="\n")
    tx.to_csv(OUT / "tx_log_dev.csv", index=False, lineterminator="\n")
    decision = OUT / "decision.md"
    if decision.exists():
        print("decision.md already exists; not rewritten")
        return
    tab = raw.pivot_table(index="policy", columns="n_robots", values="align_rmse", aggfunc="mean")
    tab["pooled"] = raw.groupby("policy").align_rmse.mean()
    tab["sd_pooled"] = raw.groupby("policy").align_rmse.std()
    tab = tab.loc[DEV_POLICIES]
    chosen = tab.loc[TW, "pooled"].idxmin()
    lines = ["# Ranking v2: DEV decision", "",
             f"Written by `ranking_v2.py dev` on {time.strftime('%Y-%m-%d %H:%M:%S %Z')}, before any TEST run.",
             "Rule (fixed in advance): among tw_now, tw_arrival and tw_arrival_sub, choose the lowest mean",
             "map-alignment RMSE over DEV seeds 0-9 x N = 2, 3, 4, 5 (40 seed-team pairs), condition C0.", "",
             f"**Chosen variant: `{chosen}`** (primary hypothesis for TEST: {chosen} vs random).", "",
             "DEV ablation table (map-alignment RMSE, m; mean per N, pooled mean and SD over 40 pairs):", "",
             "| policy | N=2 | N=3 | N=4 | N=5 | pooled mean | pooled SD |", "|---|---|---|---|---|---|---|"]
    for p, r in tab.iterrows():
        lines.append(f"| {p}{' **(chosen)**' if p == chosen else ''} | " + " | ".join(
            f"{r[n]:.4f}" for n in COUNTS) + f" | {r.pooled:.4f} | {r.sd_pooled:.4f} |")
    lines += ["", "This file is not modified after it is written."]
    decision.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def test(workers, names):
    if not (OUT / "decision.md").exists():
        sys.exit("decision.md missing: run `dev` first")
    cond = conditions()
    for c in names:
        if not cond[c].get("t_defer"):
            sys.exit(f"{c}: no t_defer (run `pilot`, and see REPORT.md for C1/C2)")
    jobs = [("test", c, cond[c], s, n, TEST_POLICIES, 1.0) for c in names for s in TEST_SEEDS for n in COUNTS]
    execute("test", jobs, workers)
    for c in names:
        d = OUT / c
        d.mkdir(exist_ok=True)
        raw, tx = collect("test", c)
        raw.to_csv(d / "test_raw.csv", index=False, lineterminator="\n")
        tx.to_csv(d / f"tx_log_test_{c}.csv", index=False, lineterminator="\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=["pilot", "dev", "test"])
    ap.add_argument("conditions", nargs="*", default=["C0", "C1", "C2", "C3"])
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    {"pilot": lambda: pilot(a.workers), "dev": lambda: dev(a.workers),
     "test": lambda: test(a.workers, a.conditions)}[a.phase]()


if __name__ == "__main__":
    main()
