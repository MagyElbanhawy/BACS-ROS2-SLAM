"""
Pair observability for Observability-Aware BACS (BACS+).

The information surrogate of Eq. (12) scores a candidate on novelty, node degree
and loop length. None of those terms asks whether the *relative transform*
between the two robots involved is actually determined yet. Section 6.5 reports
that this omission is why the plain scheduler's advantage reverses beyond three
robots: as the team grows, per-pair airtime falls and some robot pairs become
under-constrained, but the surrogate keeps spending airtime where coverage is
high rather than where the graph is observable.

`PairObservability` tracks, per ordered robot pair, how many inter-robot
constraints have already been delivered, and returns an observability deficit

    O_ij = exp(-n_ij / n_ref)   in (0, 1]

which is 1 when the pair has no delivered constraints (its relative transform is
undetermined) and decays toward 0 as constraints accumulate. Adding w_o * O_ij
to the surrogate biases airtime toward pairs whose transform is not yet pinned
down -- the coverage/observability tension the plain surrogate ignores.
"""
from __future__ import annotations

import math


class PairObservability:
    """Delivered-constraint counter per robot pair, exposing O_ij in (0, 1]."""

    def __init__(self, n_ref: float = 6.0):
        self.n_ref = max(float(n_ref), 1e-9)
        self._count: dict = {}

    @staticmethod
    def _key(i: int, j: int):
        # The relative transform is symmetric in the pair, so (i, j) and (j, i)
        # share a bucket.
        return (i, j) if i <= j else (j, i)

    def count(self, i: int, j: int) -> int:
        return self._count.get(self._key(i, j), 0)

    def score(self, i: int, j: int) -> float:
        """Observability deficit O_ij in (0, 1]; 1 when the pair is unconstrained."""
        return math.exp(-self.count(i, j) / self.n_ref)

    def mark(self, i: int, j: int) -> None:
        """Record that a constraint tying pair (i, j) has been delivered."""
        k = self._key(i, j)
        self._count[k] = self._count.get(k, 0) + 1
