"""S8 (30 held-out seeds, N = 2-5) statistics rebuilt from the per-seed raw CSV.

Input: ``s8_30seed_raw.csv`` (n_robots, seed, arm, pose_rmse, align_rmse,
trust_yield, n_delivered) as written by ``scripts/run_s8_30seed.py``. The fresh run
(``paper_results/s8_30seed_raw.csv``) is used when present, else the frozen copy
(``paper_results/simulation/frozen/``). Conventions follow run_s8_30seed.py:
two-sided paired Wilcoxon by seed; Cliff's delta of (a, b), negative => a lower;
improvement = 100 * (mean_b - mean_a) / mean_b.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ARMS = ["fifo", "bacs_gated", "plus_0.30_6", "plus_0.60_5"]
LABELS = {"fifo": "FIFO", "bacs_gated": "BACS", "plus_0.30_6": "BACS+ (0.30, 6)", "plus_0.60_5": "BACS+ (0.60, 5)"}
COMPARISONS = [("bacs_gated", "fifo"), ("plus_0.30_6", "fifo"), ("plus_0.60_5", "fifo"),
               ("plus_0.30_6", "bacs_gated"), ("plus_0.60_5", "plus_0.30_6")]
METRICS = ["align_rmse", "pose_rmse", "n_delivered"]


def raw_path(root: Path) -> tuple[Path, str]:
    fresh = root / "paper_results" / "s8_30seed_raw.csv"
    frozen = root / "paper_results" / "simulation" / "frozen" / "s8_30seed_raw.csv"
    if fresh.exists():
        return fresh, "regenerated"
    if frozen.exists():
        return frozen, "frozen"
    raise FileNotFoundError("no s8_30seed_raw.csv (run scripts/reproduce_simulation.py)")


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    diff = a[:, None] - b[None, :]
    return float((np.sum(diff > 0) - np.sum(diff < 0)) / diff.size)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (n, arm), group in df.groupby(["n_robots", "arm"]):
        for metric in METRICS:
            v = group[metric].to_numpy(dtype=float)
            v = v[np.isfinite(v)]
            sd = float(v.std(ddof=1)) if len(v) > 1 else 0.0
            half = float(stats.t.ppf(0.975, len(v) - 1) * sd / math.sqrt(len(v))) if len(v) > 1 else math.nan
            rows.append({"n_robots": n, "arm": arm, "metric": metric, "n_seeds": len(v), "mean": v.mean(),
                         "median": float(np.median(v)), "sd": sd, "ci_lo": v.mean() - half, "ci_hi": v.mean() + half})
    return pd.DataFrame(rows)


def paired(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for n in sorted(df.n_robots.unique()):
        for a, b in COMPARISONS:
            for metric in ("align_rmse", "pose_rmse"):
                da = df[(df.n_robots == n) & (df.arm == a)].set_index("seed")[metric]
                db = df[(df.n_robots == n) & (df.arm == b)].set_index("seed")[metric]
                seeds = da.index.intersection(db.index)
                x, y = da.loc[seeds].to_numpy(float), db.loc[seeds].to_numpy(float)
                ok = np.isfinite(x) & np.isfinite(y)
                x, y = x[ok], y[ok]
                if len(x) == 0:
                    continue
                p = float(stats.wilcoxon(x, y).pvalue) if len(x) >= 5 and not np.allclose(x, y) else math.nan
                rows.append({"n_robots": n, "arm_a": a, "arm_b": b, "metric": metric, "n_pairs": len(x),
                             "a_mean": x.mean(), "b_mean": y.mean(),
                             "improvement_pct": 100 * (y.mean() - x.mean()) / y.mean(),
                             "wilcoxon_p": p, "cliffs_delta": cliffs_delta(x, y),
                             "seeds_a_lower": int(np.sum(x < y))})
    return pd.DataFrame(rows)


def run(root: Path) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    path, source = raw_path(root)
    df = pd.read_csv(path)
    out = root / "paper_results" / "simulation"
    out.mkdir(parents=True, exist_ok=True)
    s, t = summary(df), paired(df)
    s.to_csv(out / "s8_summary.csv", index=False, lineterminator="\n")
    t.to_csv(out / "s8_paired_tests.csv", index=False, lineterminator="\n")
    (out / "s8_source.txt").write_text(f"{source}: {path.relative_to(root).as_posix()}\n", encoding="utf-8")
    return s, t, source
