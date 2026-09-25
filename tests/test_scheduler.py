from math import exp, log

import pytest

from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import Constraint, DutyCycleBudget, Scheduler, lora_airtime_s


def item(sequence: int, trust: float = 1.0, info: float = 1.0, pair_count: int = 0) -> Constraint:
    return Constraint(sequence, 0, 52, trust, info, "a", "b", pair_count)


def test_lora_airtime_is_positive_and_repeatable() -> None:
    assert 0 < lora_airtime_s(52) < 1
    # LoRa payload symbols are quantized, so adjacent byte sizes may share airtime.
    assert lora_airtime_s(56) > lora_airtime_s(52)


def test_one_percent_duty_cycle_and_window() -> None:
    budget = DutyCycleBudget(window_s=60, duty_cycle=.01)
    budget.record(0, .5)
    assert not budget.can_send(0, .11)
    assert budget.can_send(61, .6)


def test_fifo_preserves_generation_order() -> None:
    selected = Scheduler("FIFO", DutyCycleBudget()).select([item(2), item(1)], 0)
    assert [x.sequence for x in selected] == [1, 2]


def test_trust_gating() -> None:
    assert Scheduler("BACS", DutyCycleBudget(), trust_threshold=.05).select([item(1, .049), item(2, .07)], 0) == [item(2, .07)]


def test_bacs_ranks_strictly_by_information_density() -> None:
    bacs = Scheduler("BACS", DutyCycleBudget())
    assert [c.sequence for c in bacs.rank([item(1, trust=.9, info=.5), item(2, trust=.2, info=.9)], 0)] == [2, 1]


def test_bacs_plus_adds_observability_to_information_term() -> None:
    bacs_plus = Scheduler("BACS+", DutyCycleBudget(), observability_weight=.30)
    assert bacs_plus.rank([item(1, info=.5, pair_count=0), item(2, info=.7, pair_count=20)], 0)[0].sequence == 1
    assert item(1, pair_count=0).observability(6) == pytest.approx(1)
    assert item(1, pair_count=6).observability(6) == pytest.approx(exp(-1))


def test_temporal_decay_parameter() -> None:
    scheduler = Scheduler("BACS+", DutyCycleBudget(), defer_half_life_s=10)
    assert scheduler.gamma_defer == pytest.approx(log(2) / 10)


def test_two_pass_prediction_updates_queue_delay_and_trust() -> None:
    scheduler = Scheduler("BACS", DutyCycleBudget(), trust_threshold=.05, defer_half_life_s=1)
    ordered, predictions = scheduler.rank_with_predictions([item(1, trust=.9, info=.9), item(2, trust=.9, info=.8)], 0)
    assert [c.sequence for c in ordered] == [1, 2]
    assert predictions[2]["predicted_delay_s"] > predictions[1]["predicted_delay_s"]
    assert predictions[2]["predicted_trust_tx"] < predictions[1]["predicted_trust_tx"]
