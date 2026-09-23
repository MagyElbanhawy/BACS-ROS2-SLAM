"""Statistical primitives with no manuscript-result constants."""

from __future__ import annotations

from math import sqrt
from typing import Sequence

from scipy.stats import wilcoxon


def cliffs_delta(left: Sequence[float], right: Sequence[float]) -> float:
    """Return Cliff's delta using all cross-group ordered pairs."""
    if not left or not right:
        raise ValueError("both groups must contain observations")
    greater = sum(x > y for x in left for y in right)
    lesser = sum(x < y for x in left for y in right)
    return (greater - lesser) / (len(left) * len(right))


def paired_wilcoxon(left: Sequence[float], right: Sequence[float]) -> dict[str, float]:
    """Run the two-sided paired Wilcoxon signed-rank test."""
    if len(left) != len(right) or not left:
        raise ValueError("paired samples must have equal, non-zero length")
    result = wilcoxon(left, right, alternative="two-sided", method="auto")
    return {"statistic": float(result.statistic), "p_value": float(result.pvalue)}
