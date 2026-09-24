"""Deterministic, testable scheduler logic used by the ROS 2 nodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, exp, log
from typing import Iterable


def lora_airtime_s(
    payload_bytes: int, spreading_factor: int = 7, bandwidth_hz: int = 125_000,
    coding_rate_denominator: int = 5, preamble_symbols: int = 8,
) -> float:
    """Return LoRa packet time-on-air using the Semtech explicit-header formula."""
    if payload_bytes < 0 or not 6 <= spreading_factor <= 12 or bandwidth_hz <= 0:
        raise ValueError("invalid LoRa configuration")
    cr = coding_rate_denominator - 4
    if cr not in (1, 2, 3, 4):
        raise ValueError("coding rate must be one of 4/5 through 4/8")
    ts = (2 ** spreading_factor) / bandwidth_hz
    low_data_rate = int(spreading_factor >= 11 and bandwidth_hz <= 125_000)
    numerator = 8 * payload_bytes - 4 * spreading_factor + 28 + 16
    denominator = 4 * (spreading_factor - 2 * low_data_rate)
    payload_symbols = 8 + max(ceil(numerator / denominator) * (cr + 4), 0)
    return (preamble_symbols + 4.25 + payload_symbols) * ts


@dataclass(frozen=True)
class Constraint:
    """A candidate inter-robot constraint available for transmission."""

    sequence: int
    generated_ns: int
    payload_bytes: int
    predicted_trust: float
    information_score: float
    robot_i: str
    robot_j: str
    pair_constraints: int = 0

    def observability(self, reference: int = 6) -> float:
        if reference <= 0:
            raise ValueError("reference must be positive")
        return exp(-self.pair_constraints / reference)


@dataclass
class DutyCycleBudget:
    """Rolling-window airtime ledger; configured values are never measurements."""

    window_s: float = 60.0
    duty_cycle: float = 0.01
    transmissions: list[tuple[float, float]] = field(default_factory=list)

    @property
    def capacity_s(self) -> float:
        return self.window_s * self.duty_cycle

    def used_s(self, now_s: float) -> float:
        start = now_s - self.window_s
        self.transmissions = [(t, a) for t, a in self.transmissions if t >= start]
        return sum(a for _, a in self.transmissions)

    def can_send(self, now_s: float, airtime_s: float) -> bool:
        return self.used_s(now_s) + airtime_s <= self.capacity_s + 1e-12

    def record(self, now_s: float, airtime_s: float) -> None:
        if not self.can_send(now_s, airtime_s):
            raise ValueError("duty-cycle budget exceeded")
        self.transmissions.append((now_s, airtime_s))


class Scheduler:
    """Select constraints without modelling channel delay or radio measurements."""

    def __init__(
        self, policy: str, budget: DutyCycleBudget, trust_threshold: float = 0.5,
        observability_weight: float = 0.30, observability_reference: int = 6,
        defer_half_life_s: float = 60.0,
    ) -> None:
        if policy not in {"FIFO", "BACS", "BACS+"}:
            raise ValueError(f"unsupported policy: {policy}")
        if defer_half_life_s <= 0:
            raise ValueError("defer_half_life_s must be positive")
        self.policy, self.budget = policy, budget
        self.trust_threshold, self.observability_weight = trust_threshold, observability_weight
        self.observability_reference = observability_reference
        self.gamma_defer = log(2) / defer_half_life_s

    def score(self, item: Constraint, now_ns: int) -> float:
        age_s = max(0, now_ns - item.generated_ns) / 1e9
        freshness = exp(-self.gamma_defer * age_s)
        base = item.information_score * item.predicted_trust * freshness
        if self.policy == "BACS+":
            base *= 1 + self.observability_weight * item.observability(self.observability_reference)
        return base / lora_airtime_s(item.payload_bytes)

    def rank(self, candidates: Iterable[Constraint], now_ns: int) -> list[Constraint]:
        """Return admissible candidates in transmission order without touching the budget."""
        eligible = [c for c in candidates if c.predicted_trust >= self.trust_threshold]
        return sorted(eligible, key=lambda c: c.sequence) if self.policy == "FIFO" else sorted(
            eligible, key=lambda c: (-self.score(c, now_ns), c.sequence)
        )

    def select(self, candidates: Iterable[Constraint], now_ns: int) -> list[Constraint]:
        ordered = self.rank(candidates, now_ns)
        selected: list[Constraint] = []
        now_s = now_ns / 1e9
        for item in ordered:
            airtime = lora_airtime_s(item.payload_bytes)
            if self.budget.can_send(now_s, airtime):
                self.budget.record(now_s, airtime)
                selected.append(item)
        return selected
