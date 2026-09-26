#!/usr/bin/env python3
"""Why does the frozen S8 arm plus_0.60_5 not reproduce?

    python scripts/revision/plus060_investigation.py [--workers 1]

Three checks against paper_results/simulation/frozen/s8_30seed_raw.csv, written to
paper_results/revision/ranking_v2/plus_0.60_5_investigation/:
  grid.csv       bacs_plus over w_obs x obs_ref (deferral-derived gamma) at two cells
                 (seed 10 N=2, seed 11 N=3): which settings reproduce each frozen value?
  seeds.csv      bacs_plus(0.60, 5) for all 30 seeds at N=2, 3 under three gamma rules:
                 row-wise and set-wise matches (tests seed/row misalignment).
  mechanisms.csv alternative observability definitions (hyperbolic, linear deficit,
                 ordered pair) at 4 cells, for (0.60, 5) and, as a control, (0.30, 6).
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "paper_results" / "revision" / "ranking_v2" / "plus_0.60_5_investigation"
FROZEN = ROOT / "paper_results" / "simulation" / "frozen" / "s8_30seed_raw.csv"


import bacs_sim.observability as _ob  # noqa: E402
_ORIG = {"score": _ob.PairObservability.score, "key": _ob.PairObservability.__dict__["_key"]}


def _run(seed, n, w, ref, rule="deferral_derived", variant=None):
    import bacs_sim.observability as ob
    import bacs_sim.simulator as sim
    from bacs_sim.experiments import _mk, s8_config
    # Restore the shipped definitions first: worker processes are reused across jobs.
    ob.PairObservability.score = _ORIG["score"]
    ob.PairObservability._key = _ORIG["key"]
    if variant == "hyperbolic":
        ob.PairObservability.score = lambda s, i, j: 1.0 / (1.0 + s.count(i, j) / s.n_ref)
    elif variant == "linear_deficit":
        ob.PairObservability.score = lambda s, i, j: max(0.0, 1.0 - s.count(i, j) / s.n_ref)
    elif variant == "ordered_pair":
        ob.PairObservability._key = staticmethod(lambda i, j: (i, j))
    base = _mk(seed=seed, n_robots=n)
    base.world.session_s = 480.0
    pre = sim.precompute(base)
    c = s8_config("plus_0.30_6", seed, n)
    c.infogain.w_obs, c.infogain.obs_ref, c.trust.gamma_rule = w, ref, rule
    r = sim.run(c, precomputed=pre)
    return dict(seed=seed, n_robots=n, w_obs=w, obs_ref=ref, gamma_rule=rule, variant=variant or "current",
                align_rmse=r.align_rmse, pose_rmse=r.pose_rmse, n_delivered=r.n_delivered)


def _job(args):
    return _run(*args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fr = pd.read_csv(FROZEN).set_index(["seed", "n_robots", "arm"])
    jobs = {
        "grid": [(s, n, w, ref) for s, n in ((10, 2), (11, 3)) for w in (0.3, 0.45, 0.5, 0.6, 0.75, 0.9, 1.0, 1.2)
                 for ref in (3, 4, 5, 6, 8, 10)],
        "seeds": [(s, n, 0.6, 5, rule) for n in (2, 3) for s in range(10, 40)
                  for rule in ("deferral_derived", "fixed", "derived")],
        "mechanisms": [(s, n, w, ref, "deferral_derived", v) for s in (10, 11) for n in (2, 3)
                       for v in ("hyperbolic", "linear_deficit", "ordered_pair") for w, ref in ((0.6, 5), (0.3, 6))],
    }
    with ProcessPoolExecutor(a.workers) as pool:
        for name, js in jobs.items():
            df = pd.DataFrame(list(pool.map(_job, js)))
            df["frozen_plus_0.60_5"] = [fr.align_rmse[(s, n, "plus_0.60_5")] for s, n in zip(df.seed, df.n_robots)]
            df["frozen_plus_0.30_6"] = [fr.align_rmse[(s, n, "plus_0.30_6")] for s, n in zip(df.seed, df.n_robots)]
            df["matches_frozen_0.60_5"] = (df.align_rmse - df["frozen_plus_0.60_5"]).abs() < 1e-12
            df["matches_frozen_0.30_6"] = (df.align_rmse - df["frozen_plus_0.30_6"]).abs() < 1e-12
            df.to_csv(OUT / f"{name}.csv", index=False, lineterminator="\n")
            print(name, "done", flush=True)
    grid = pd.read_csv(OUT / "grid.csv")
    per_cell = [set(zip(g.w_obs, g.obs_ref)) for _, g in grid[grid["matches_frozen_0.60_5"]].groupby(["seed", "n_robots"])]
    seeds = pd.read_csv(OUT / "seeds.csv")
    lines = ["check,result"]
    lines.append(f"grid: settings matching both cells,{sorted(per_cell[0] & per_cell[1]) if len(per_cell) == 2 else []}")
    for (n, rule), g in seeds.groupby(["n_robots", "gamma_rule"]):
        frz = pd.read_csv(FROZEN)
        col = frz[(frz.n_robots == n) & (frz.arm == "plus_0.60_5")].align_rmse.to_numpy()
        anywhere = sum(np.min(np.abs(col - v)) < 1e-12 for v in g.align_rmse)
        lines.append(f"seeds N={n} {rule}: row-wise matches {int(g['matches_frozen_0.60_5'].sum())}/30; "
                     f"values found anywhere in the frozen column {anywhere}/30,")
    mech = pd.read_csv(OUT / "mechanisms.csv")
    for (v, w, ref), g in mech.groupby(["variant", "w_obs", "obs_ref"]):
        lines.append(f"mechanism {v} ({w}; {ref}): matches frozen 0.60_5 {int(g['matches_frozen_0.60_5'].sum())}/4; "
                     f"matches frozen 0.30_6 {int(g['matches_frozen_0.30_6'].sum())}/4,")
    (OUT / "summary.csv").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
