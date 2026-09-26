"""Ranking v2 (tw_now / tw_arrival / tw_arrival_sub): score properties and budgets."""
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from bacs_sim.config import InfoGainConfig, LoRaConfig, SimConfig, TrustConfig, SchedulerConfig
from bacs_sim.experiments import _mk
from bacs_sim.infogain import CoverageMap
from bacs_sim.lora import airtime_budget, time_on_air
from bacs_sim.observability import PairObservability
from bacs_sim.schedulers import (TW_POLICIES, _coverage_copy, _sub_score, schedule, theta_arrival, theta_now,
                                 tw_info)
from bacs_sim.simulator import precompute, run

# The four ranking-v2 conditions (scripts/revision/ranking_v2.py BASE_CONDITIONS; gamma is irrelevant here).
CONDITIONS = {"C0": {}, "C1": {"lora.duty_cycle": 0.005, "scheduler.window_s": 120.0},
              "C2": {"lora.sf": 9, "scheduler.window_s": 200.0}, "C3": {"channel.loss_rate": 0.20}}


def apply(cfg, cond):
    for k, v in CONDITIONS[cond].items():
        obj, attr = k.split(".")
        setattr(getattr(cfg, obj), attr, v)
    return cfg


def ctx_for(lora=None, t_now=120.0, gamma=0.0045, p_loss=0.0):
    icfg = InfoGainConfig()
    return dict(t_now=t_now, gamma=gamma, p_loss=p_loss, lora=lora or LoRaConfig(), window_s=60.0,
                trust=TrustConfig(), infogain=icfg, coverage=CoverageMap(icfg), pair_obs=PairObservability(6.0))


def cand(i, rid_from=0, rid_to=1, t=100.0, k=0, spatial=0.9, theta_hat=0.8, nov=1.0, xy=(1.0, 1.0),
         queue=0.0, payload=52, deg=0, loop=30.0, ctx=None):
    c = SimpleNamespace(i=i, rid_from=rid_from, rid_to=rid_to, t_created=float(t), deferrals=k, payload_bytes=payload,
                        theta_hat=theta_hat, _spatial=spatial, _nov=nov, _deg=deg, _loop=loop,
                        _xy=np.array(xy, float), _queue_ahead=queue)
    if ctx is not None:  # info_hat as the simulator sets it for TW policies (I_hat_plus)
        from bacs_sim.infogain import surrogate_info
        c.info_hat = surrogate_info(nov, deg, loop, ctx["infogain"]) + ctx["infogain"].w_obs * ctx["pair_obs"].score(
            rid_from, rid_to)
    return c


def test_tw_info_zero_trust_and_full_trust():
    for info in (0.0, 0.1, 1.0, 5.0):
        assert tw_info(0.0, info) == 0.0
        assert tw_info(1.0, info) == pytest.approx(info)


def test_tw_info_monotone_in_theta_and_info():
    thetas, infos = np.linspace(0, 1, 21), np.linspace(0, 4, 21)
    grid = np.array([[tw_info(t, i) for i in infos] for t in thetas])
    assert np.all(np.diff(grid, axis=0) >= 0) and np.all(np.diff(grid[1:], axis=0)[:, 1:] > 0)
    assert np.all(np.diff(grid, axis=1) >= 0) and np.all(np.diff(grid[1:, :], axis=1) > 0)


def test_arrival_trust_not_above_current_trust():
    rng = np.random.default_rng(0)
    for _ in range(500):
        t_now = 60.0 * rng.integers(1, 12)
        k = int(rng.integers(0, 12))
        # a candidate deferred k windows was created within window (t_now/60 - k)
        t_created = t_now - 60.0 * k + rng.uniform(0, 60.0) if k else t_now + rng.uniform(0, 60.0)
        ctx = ctx_for(t_now=t_now, gamma=rng.uniform(0.001, 0.05), p_loss=rng.uniform(0, 0.3))
        c = cand(0, t=t_created, k=k, spatial=rng.uniform(0, 1), queue=rng.uniform(0, 0.3))
        assert theta_arrival(c, ctx) <= theta_now(c, ctx) + 1e-15


def test_submodular_update_lowers_same_pair_score():
    ctx = ctx_for()
    a = cand(0, rid_from=0, rid_to=1, xy=(1.0, 1.0))
    b = cand(1, rid_from=0, rid_to=1, xy=(1.2, 1.1))      # same pair, overlapping support
    far = cand(2, rid_from=0, rid_to=2, xy=(9.0, 7.0))    # other pair, disjoint support
    cov = _coverage_copy(ctx)
    th = theta_arrival(b, ctx)
    before_b, before_far = _sub_score(b, ctx, cov, {}, th), _sub_score(far, ctx, cov, {}, th)
    cov.mark(a._xy)                                        # a selected
    extra = {ctx["pair_obs"]._key(0, 1): 1}
    assert _sub_score(b, ctx, cov, extra, th) < before_b
    assert _sub_score(far, ctx, cov, extra, th) == pytest.approx(before_far)
    assert ctx["coverage"].cells == set()                  # the real coverage map is untouched


def test_submodular_changes_selection_order():
    ctx = ctx_for()
    a = cand(0, 0, 1, xy=(1.0, 1.0), nov=1.0, ctx=ctx)
    b = cand(1, 0, 1, xy=(1.0, 1.0), nov=1.0, ctx=ctx)     # duplicate of a
    c = cand(2, 0, 2, xy=(9.0, 7.0), nov=0.9, ctx=ctx)     # slightly less novel, other pair
    budget = 2.5 * time_on_air(52, ctx["lora"])
    cfg = lambda p: SchedulerConfig(policy=p)              # noqa: E731
    plain = [x.i for x in schedule([a, b, c], budget, cfg("tw_arrival"), ctx["lora"], None, ctx=ctx)]
    sub = [x.i for x in schedule([a, b, c], budget, cfg("tw_arrival_sub"), ctx["lora"], None, ctx=ctx)]
    assert plain == [0, 1] and sub == [0, 2]


@pytest.mark.parametrize("cond", list(CONDITIONS))
@pytest.mark.parametrize("policy", TW_POLICIES + ["bacs_gated", "random", "fifo"])
def test_scheduled_airtime_within_budget(cond, policy):
    sim = apply(SimConfig(), cond)
    lora, window = sim.lora, sim.scheduler.window_s
    ctx = ctx_for(lora=lora)
    rng = np.random.default_rng(1)
    for n_robots in (2, 3, 4, 5):
        budget = airtime_budget(window, lora, n_robots)
        pool = [cand(i, rid_to=int(rng.integers(1, 5)), t=rng.uniform(0, 120), k=int(rng.integers(0, 3)),
                     spatial=rng.uniform(0, 1), theta_hat=rng.uniform(0, 1), nov=rng.uniform(0, 1),
                     xy=rng.uniform(0, 10, 2), payload=int(rng.integers(52, 68)), ctx=ctx) for i in range(40)]
        chosen = schedule(pool, budget, SchedulerConfig(policy=policy), lora, np.random.default_rng(0), ctx=ctx)
        assert sum(time_on_air(c.payload_bytes, lora) for c in chosen) <= budget + 1e-12


@pytest.mark.parametrize("cond", list(CONDITIONS))
def test_simulated_windows_respect_duty_cycle(cond):
    """Per robot and window, first-attempt airtime of what was scheduled <= delta*W/N,
    and every condition actually transmits.

    Retransmissions (C3) are not budgeted by the existing channel model; their
    extra airtime is measured in the ranking-v2 report, not asserted here.
    """
    for policy in ("tw_arrival_sub", "fifo"):
        c = _mk(seed=1, n_robots=3)
        c.world.session_s = 240.0
        pre = precompute(c)
        c.scheduler.policy = policy
        c.trust.gamma_rule = "deferral_derived"
        apply(c, cond)
        r = run(c, precomputed=pre, collect_tx=True, iexact_fraction=0.0)
        log = pd.DataFrame(r.extras["tx_log"])
        assert len(log)
        per_window = log.groupby(["robot", "t_sched"]).T_air.sum()
        assert (per_window <= airtime_budget(c.scheduler.window_s, c.lora, 3) + 1e-12).all()
        if cond != "C3":
            assert (log.attempts == 1).all()
