"""Revision-v3 baselines in bacs_sim.schedulers: ordering and airtime budget."""
from types import SimpleNamespace

import numpy as np
import pytest

from bacs_sim.config import LoRaConfig, SchedulerConfig
from bacs_sim.lora import time_on_air
from bacs_sim.schedulers import BASELINES, POLICIES, schedule

LORA = LoRaConfig()


def cand(i, t, theta, info, payload=52):
    return SimpleNamespace(i=i, t_created=float(t), theta_hat=float(theta), info_hat=float(info),
                           payload_bytes=payload)


def pool():
    # t_created, theta_hat, info_hat, payload. Candidates 1 and 4 fall below the
    # bacs_gated trust gate (0.05).
    spec = [(10, 0.90, 0.20, 52), (20, 0.01, 0.95, 52), (30, 0.50, 0.60, 76),
            (40, 0.70, 0.10, 52), (50, 0.02, 0.80, 52), (60, 0.30, 0.40, 52)]
    return [cand(i, *s) for i, s in enumerate(spec)]


def run(policy, cands, budget, seed=0):
    return schedule(cands, budget, SchedulerConfig(policy=policy), LORA, np.random.default_rng(seed))


def airtime(chosen):
    return sum(time_on_air(c.payload_bytes, LORA) for c in chosen)


BUDGET = 3.2 * time_on_air(52, LORA)  # room for three 52-byte packets


def test_baselines_registered():
    assert set(BASELINES) <= set(POLICIES)


@pytest.mark.parametrize("policy", BASELINES + ["fifo", "bacs_gated"])
def test_budget_respected(policy):
    for budget in (0.0, BUDGET, 0.5 * BUDGET, 10 * BUDGET):
        for seed in range(5):
            chosen = run(policy, pool(), budget, seed)
            assert airtime(chosen) <= budget + 1e-12
            assert len({c.i for c in chosen}) == len(chosen)


def test_unlimited_budget_admits_everything_for_every_baseline():
    for policy in BASELINES:
        assert sorted(c.i for c in run(policy, pool(), 1e9)) == list(range(6))


def test_lifo_newest_first():
    chosen = run("lifo", pool(), BUDGET)
    assert [c.i for c in chosen] == [5, 4, 3]           # newest three 52-byte packets
    everything = run("lifo", pool(), 1e9)
    assert [c.t_created for c in everything] == sorted((c.t_created for c in pool()), reverse=True)


def test_lifo_is_reverse_of_fifo_order():
    fifo = [c.i for c in run("fifo", pool(), 1e9)]
    assert [c.i for c in run("lifo", pool(), 1e9)] == fifo[::-1]


def test_trust_only_ranks_by_predicted_trust_without_gate():
    everything = run("trust_only", pool(), 1e9)
    assert [c.theta_hat for c in everything] == sorted((c.theta_hat for c in pool()), reverse=True)
    # 0 and 3 fit; the 76-byte candidate 2 does not fit the remaining 1.2 slots, so 5 does
    assert [c.i for c in run("trust_only", pool(), BUDGET)] == [0, 3, 5]
    # below-gate candidates are still admitted when the budget allows
    assert {1, 4} <= {c.i for c in everything}


def test_info_only_ranks_by_information_density_without_gate():
    density = lambda c: c.info_hat / time_on_air(c.payload_bytes, LORA)  # noqa: E731
    everything = run("info_only", pool(), 1e9)
    assert [density(c) for c in everything] == sorted((density(c) for c in pool()), reverse=True)
    chosen = [c.i for c in run("info_only", pool(), BUDGET)]
    assert chosen[:2] == [1, 4]                         # the gate would have dropped both
    assert not {1, 4} & {c.i for c in run("bacs_gated", pool(), BUDGET)}


def test_info_only_equals_bacs_gated_when_gate_is_inactive():
    trusted = [c for c in pool() if c.theta_hat >= 0.05]
    assert [c.i for c in run("info_only", trusted, BUDGET)] == [c.i for c in run("bacs_gated", trusted, BUDGET)]


def test_random_is_seeded_and_uniform():
    a = [c.i for c in run("random", pool(), 1e9, seed=7)]
    b = [c.i for c in run("random", pool(), 1e9, seed=7)]
    assert a == b and sorted(a) == list(range(6))
    orders = {tuple(c.i for c in run("random", pool(), 1e9, seed=s)) for s in range(50)}
    assert len(orders) > 10                              # not a fixed order
    first = [run("random", pool(), 1e9, seed=s)[0].i for s in range(3000)]
    counts = np.bincount(first, minlength=6)
    assert counts.min() > 400 and counts.max() < 600     # ~500 each if uniform


def test_greedy_packing_skips_what_does_not_fit_and_continues():
    # Budget fits one 76-byte packet plus one 52-byte one, but not two 76-byte ones.
    big = [cand(0, 1, 0.9, 0.9, 76), cand(1, 2, 0.8, 0.8, 76), cand(2, 3, 0.7, 0.1, 52)]
    budget = time_on_air(76, LORA) + time_on_air(52, LORA) + 1e-9
    assert [c.i for c in run("trust_only", big, budget)] == [0, 2]
