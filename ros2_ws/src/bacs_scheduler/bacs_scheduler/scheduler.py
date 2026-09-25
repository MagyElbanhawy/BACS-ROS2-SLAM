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
        self, policy: str, budget: DutyCycleBudget, trust_threshold: float = 0.05,
        observability_weight: float = 0.30, observability_reference: int = 6,
        defer_half_life_s: float = 155.0, trust_floor: float = 0.01,
        ack_timeout_s: float = 0.0, loss_rate: float = 0.0,
    ) -> None:
        if policy not in {"FIFO", "BACS", "BACS+"}:
            raise ValueError(f"unsupported policy: {policy}")
        if defer_half_life_s <= 0:
            raise ValueError("defer_half_life_s must be positive")
        self.policy, self.budget = policy, budget
        self.trust_threshold, self.observability_weight = trust_threshold, observability_weight
        self.observability_reference = observability_reference
        self.gamma_defer = log(2) / defer_half_life_s
        self.trust_floor = trust_floor
        self.ack_timeout_s = ack_timeout_s
        self.loss_rate = loss_rate

    def effective_information_score(self, item: Constraint) -> float:
        score = item.information_score
        if self.policy == "BACS+":
            score += self.observability_weight * item.observability(self.observability_reference)
        return score

    def information_density(self, item: Constraint) -> float:
        return self.effective_information_score(item) / lora_airtime_s(item.payload_bytes)

    def predicted_delay_s(self, payload_bytes: int, queue_airtime_s: float, now_s: float) -> float:
        airtime_s = lora_airtime_s(payload_bytes)
        loss = min(max(self.loss_rate, 0.0), 0.95)
        retry_s = (loss / (1.0 - loss)) * (airtime_s + self.ack_timeout_s)
        remaining_s = max(self.budget.capacity_s - self.budget.used_s(now_s), 0.0)
        extra_queue_s = max(queue_airtime_s - remaining_s, 0.0)
        deferral_windows = extra_queue_s / max(self.budget.capacity_s, 1e-9)
        return deferral_windows * self.budget.window_s + queue_airtime_s + airtime_s + retry_s

    def predicted_trust(self, item: Constraint, delay_s: float) -> float:
        geometric = min(max(item.predicted_trust, 0.0), 1.0)
        return max(self.trust_floor, geometric * exp(-self.gamma_defer * max(delay_s, 0.0)))

    def rank_with_predictions(self, candidates: Iterable[Constraint], now_ns: int) -> tuple[list[Constraint], dict[int, dict[str, float]]]:
        """Return admissible candidates plus the transmitter-side predictions used."""
        now_s = now_ns / 1e9
        items = list(candidates)
        predictions: dict[int, dict[str, float]] = {}
        base_order = sorted(items, key=lambda c: c.sequence) if self.policy == "FIFO" else sorted(
            items, key=lambda c: (-self.information_density(c), c.sequence)
        )
        provisional_queue_s = 0.0
        for item in base_order:
            pass1_delay = self.predicted_delay_s(item.payload_bytes, provisional_queue_s, now_s)
            pass1_trust = self.predicted_trust(item, pass1_delay)
            predictions[item.sequence] = {
                "predicted_delay_s": pass1_delay,
                "predicted_trust_tx": pass1_trust,
                "information_density": self.information_density(item),
                "effective_information_score": self.effective_information_score(item),
            }
            provisional_queue_s += lora_airtime_s(item.payload_bytes)
        ordered = base_order
        ranked: list[Constraint] = []
        queue_airtime_s = 0.0
        for item in ordered:
            delay_s = self.predicted_delay_s(item.payload_bytes, queue_airtime_s, now_s)
            trust = self.predicted_trust(item, delay_s)
            predictions[item.sequence].update({"predicted_delay_s": delay_s, "predicted_trust_tx": trust})
            if trust >= self.trust_threshold:
                ranked.append(item)
                queue_airtime_s += lora_airtime_s(item.payload_bytes)
        return ranked, predictions

    def rank(self, candidates: Iterable[Constraint], now_ns: int) -> list[Constraint]:
        """Return admissible candidates in transmission order without touching the budget."""
        return self.rank_with_predictions(candidates, now_ns)[0]

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
