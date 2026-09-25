"""Statistics shared by the revision-v3 scripts.

Conventions follow analysis/simulation/s8.py: sample SD (ddof=1), t-based 95 % CI,
two-sided paired Wilcoxon signed-rank by seed, Cliff's delta of (a, b) with
negative meaning a is lower, Holm step-down correction within a stated family.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats


def describe(values) -> dict:
    v = np.asarray(values, float)
    v = v[np.isfinite(v)]
    n = len(v)
    mean = float(v.mean()) if n else math.nan
    sd = float(v.std(ddof=1)) if n > 1 else math.nan
    half = float(stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n)) if n > 1 else math.nan
    return {"n": n, "mean": mean, "sd": sd, "ci95_lo": mean - half, "ci95_hi": mean + half,
            "median": float(np.median(v)) if n else math.nan}


def cliffs_delta(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    diff = a[:, None] - b[None, :]
    return float((np.sum(diff > 0) - np.sum(diff < 0)) / diff.size)


def paired(a, b) -> dict:
    """Paired comparison of a against b (same seeds, same order)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    d = a - b
    if len(d) >= 5 and np.any(d != 0):
        res = stats.wilcoxon(a, b, alternative="two-sided")
        w, p = float(res.statistic), float(res.pvalue)
    else:  # identical in every seed: no test is possible
        w, p = math.nan, math.nan
    return {"n_pairs": int(len(d)), "mean_a": float(a.mean()), "mean_b": float(b.mean()),
            "pct_change_of_mean": 100.0 * (a.mean() - b.mean()) / b.mean(),
            "wilcoxon_W": w, "wilcoxon_p_two_sided": p, "cliffs_delta": cliffs_delta(a, b),
            "seeds_won": int(np.sum(a < b)), "seeds_tied": int(np.sum(a == b)), "seeds_lost": int(np.sum(a > b))}


def holm(p: pd.Series) -> pd.Series:
    """Holm-Bonferroni adjusted p-values; NaN entries are left out of the family."""
    out = pd.Series(np.nan, index=p.index)
    valid = p.dropna().sort_values()
    m = len(valid)
    running = 0.0
    for i, (idx, value) in enumerate(valid.items()):
        running = max(running, min(1.0, (m - i) * value))
        out[idx] = running
    return out
