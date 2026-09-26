"""Residual-gated ranking (rgate / plus_rgate): gate, bootstrap, alpha, budget, equivalence."""
from types import SimpleNamespace

import numpy as np
import pytest

from bacs_sim.config import LoRaConfig, SchedulerConfig
from bacs_sim.experiments import _mk, s8_config
from bacs_sim.lora import time_on_air
from bacs_sim.schedulers import RGATE_POLICIES, POLICIES, residual_gate, schedule
from bacs_sim.simulator import precompute, run

LORA = LoRaConfig()


def cand(i, res, theta=0.8, info=0.5, pair_n=10, payload=52, t=0.0):
    return SimpleNamespace(i=i, _res=res, theta_hat=theta, info_hat=info, _pair_n=pair_n,
                           payload_bytes=payload, t_created=t)


def cfg(policy="plus_rgate", **kw):
    return SchedulerConfig(policy=policy, **kw)


def sched(cands, budget=1e9, **kw):
    return [c.i for c in schedule(cands, budget, cfg(**kw), LORA, np.random.default_rng(0))]


def test_registered():
    assert set(RGATE_POLICIES) <= set(POLICIES)


def test_gate_rejects_large_residuals_and_keeps_small():
    pool = [cand(0, 0.1), cand(1, 0.49), cand(2, 0.51), cand(3, 1.3)]
    assert sorted(sched(pool, residual_gate=0.5)) == [0, 1]


def test_gate_has_no_fallback():
    assert sched([cand(0, 2.0), cand(1, 3.0)], residual_gate=0.5) == []


def test_bootstrap_exempts_unconstrained_pairs():
    pool = [cand(0, 2.0, pair_n=0), cand(1, 2.0, pair_n=2), cand(2, 2.0, pair_n=3)]
    assert sorted(sched(pool, residual_gate=0.5, gate_min_pair=3)) == [0, 1]
    assert sched(pool, residual_gate=0.5, gate_min_pair=0) == []


def test_trust_gate_still_applies_after_residual_gate():
    pool = [cand(0, 0.1, theta=0.01), cand(1, 0.1, theta=0.5)]
    assert [c.i for c in residual_gate(pool, cfg(residual_gate=0.5))] == [1]
    # all survivors below the trust gate -> fall back to the residual survivors, as bacs_gated does
    pool = [cand(0, 0.1, theta=0.01), cand(1, 0.9, theta=0.01)]
    assert [c.i for c in residual_gate(pool, cfg(residual_gate=0.5))] == [0]


def test_alpha_zero_is_information_density_and_alpha_breaks_ties_by_trust():
    pool = [cand(0, 0.1, theta=0.2, info=0.6), cand(1, 0.1, theta=0.9, info=0.5)]
    assert sched(pool, trust_alpha=0.0) == [0, 1]          # density only
    assert sched(pool, trust_alpha=1.0) == [1, 0]          # 0.5*0.9 > 0.6*0.2
    even = [cand(0, 0.1, theta=0.2), cand(1, 0.1, theta=0.9)]
    assert sched(even, trust_alpha=0.2) == [1, 0]          # equal density: trust decides
    assert sched(even, trust_alpha=0.0) == [0, 1]          # stable order when alpha = 0


@pytest.mark.parametrize("policy", RGATE_POLICIES)
def test_budget_respected(policy):
    rng = np.random.default_rng(3)
    pool = [cand(i, rng.uniform(0, 2), theta=rng.uniform(0, 1), info=rng.uniform(0, 1),
                 pair_n=int(rng.integers(0, 6)), payload=int(rng.integers(52, 68))) for i in range(60)]
    for budget in (0.0, 0.15, 0.3, 0.6):
        for gate, alpha, k in ((0.5, 0.0, 0), (1.0, 0.3, 3), (float("inf"), 0.3, 0)):
            chosen = schedule(pool, budget, cfg(policy, residual_gate=gate, trust_alpha=alpha, gate_min_pair=k),
                              LORA, np.random.default_rng(0))
            assert sum(time_on_air(c.payload_bytes, LORA) for c in chosen) <= budget + 1e-12


@pytest.mark.parametrize("policy,ref", [("rgate", "bacs_gated"), ("plus_rgate", "plus_0.30_6")])
def test_infinite_gate_alpha_zero_reproduces_reference(policy, ref):
    base = _mk(seed=3, n_robots=3)
    base.world.session_s = 240.0
    pre = precompute(base)
    a = run(s8_config(ref, 3, 3, 240.0), precomputed=pre)
    c = s8_config(ref, 3, 3, 240.0)
    c.scheduler.policy = policy
    b = run(c, precomputed=pre)
    assert b.align_rmse == a.align_rmse and b.pose_rmse == a.pose_rmse and b.n_delivered == a.n_delivered
    assert b.extras["gate_counts"]["outlier_rejected"] == 0 and b.extras["gate_counts"]["inlier_rejected"] == 0


def test_gate_counts_and_rejection_in_simulation():
    base = _mk(seed=3, n_robots=2)
    base.world.session_s = 240.0
    pre = precompute(base)
    c = s8_config("plus_0.30_6", 3, 2, 240.0)
    c.scheduler.policy, c.scheduler.residual_gate, c.scheduler.gate_min_pair = "plus_rgate", 1.0, 0
    g = run(c, precomputed=pre).extras["gate_counts"]
    assert g["outlier_eval"] > 0 and g["inlier_eval"] > 0
    assert g["outlier_rejected"] / g["outlier_eval"] > g["inlier_rejected"] / g["inlier_eval"]
