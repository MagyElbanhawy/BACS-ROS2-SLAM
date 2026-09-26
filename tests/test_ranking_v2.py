"""Ranking-v2 scheduler variants: trust-weighted gain and submodular packing."""
import itertools

import numpy as np
import pytest

from bacs_sim.config import InfoGainConfig, LoRaConfig, SchedulerConfig
from bacs_sim.infogain import CoverageMap, surrogate_info
from bacs_sim.lora import time_on_air
from bacs_sim.observability import PairObservability
from bacs_sim.schedulers import _pack_submodular, arrival_trust, schedule, trust_weighted_info
from bacs_sim.world import Constraint

LORA = LoRaConfig()
ICFG = InfoGainConfig()


def cand(rid_to, xy, theta=0.8, payload=40, t=0.0):
    c = Constraint(rid_from=0, rid_to=rid_to, idx_from=0, idx_to=0, z=np.zeros(3),
                   t_created=t, payload_bytes=payload)
    c.xy_from, c.degree_from, c.loop_len = np.asarray(xy, float), 0, 30.0
    c.theta_hat = theta
    return c


def ctx():
    return dict(coverage=CoverageMap(ICFG), pair_obs=PairObservability(6.0), infogain=ICFG,
                gamma=np.log(2) / 155.0, t_now=0.0)


def fill_info(cands, c):
    for x in cands:
        x.info_hat = (surrogate_info(c["coverage"].novelty(x.xy_from), x.degree_from, x.loop_len, ICFG)
                      + ICFG.w_obs * c["pair_obs"].score(x.rid_from, x.rid_to))


def test_itw_zero_when_theta_zero():
    for info in (0.0, 0.3, 1.0, 1.6):
        assert trust_weighted_info(info, 0.0) == 0.0


def test_itw_equals_info_at_full_trust():
    for info in (0.0, 0.3, 1.0, 1.6):
        assert trust_weighted_info(info, 1.0) == pytest.approx(info)


def test_itw_monotone_in_theta_and_info():
    grid = np.linspace(0.0, 1.0, 21)
    infos = np.linspace(0.0, 1.6, 21)
    for info in infos[1:]:
        vals = [trust_weighted_info(info, th) for th in grid]
        assert all(b > a for a, b in zip(vals, vals[1:]))
    for th in grid[1:]:
        vals = [trust_weighted_info(i, th) for i in infos]
        assert all(b > a for a, b in zip(vals, vals[1:]))


def test_submodular_update_lowers_same_pair_scores():
    c = ctx()
    pair_a = [cand(1, (0.0, 0.0)), cand(1, (0.3, 0.2))]   # same pair, overlapping support
    other = cand(2, (40.0, 40.0))                           # different pair, far away
    fill_info(pair_a + [other], c)
    before = {id(x): trust_weighted_info(x.info_hat, x.theta_hat) for x in pair_a + [other]}

    budget = time_on_air(40, LORA) * 1.5                    # room for exactly one pick
    chosen = _pack_submodular(pair_a + [other], budget, LORA, c)
    assert len(chosen) == 1 and chosen[0].rid_to == 1

    # Rescore after the provisional update the loop applies.
    c2 = ctx()
    c2["pair_obs"].mark(0, 1)
    c2["coverage"].mark(chosen[0].xy_from)
    rest = [x for x in pair_a if x is not chosen[0]]
    fill_info(rest + [other], c2)
    for x in rest:
        assert trust_weighted_info(x.info_hat, x.theta_hat) < before[id(x)]
    assert trust_weighted_info(other.info_hat, other.theta_hat) == pytest.approx(before[id(other)])
    # The live state passed in ctx is left untouched.
    assert c["pair_obs"].count(0, 1) == 0 and not c["coverage"].cells


def test_submodular_changes_order_vs_static_ranking():
    # Two near-duplicate candidates on one pair and a lower-trust one on
    # another pair elsewhere: the static rank takes both duplicates, the
    # submodular loop diversifies.
    c = ctx()
    dup = [cand(1, (0.0, 0.0), theta=0.9), cand(1, (0.1, 0.0), theta=0.9)]
    fresh = cand(2, (40.0, 40.0), theta=0.6)
    fill_info(dup + [fresh], c)
    budget = time_on_air(40, LORA) * 2.5
    static = schedule(dup + [fresh], budget, SchedulerConfig(policy="plus_tw"), LORA, None, ctx=c)
    assert all(x is not fresh for x in static)
    sub = schedule(dup + [fresh], budget, SchedulerConfig(policy="plus_tw_sub"), LORA, None, ctx=c)
    assert any(x is fresh for x in sub) and len(sub) == 2


@pytest.mark.parametrize("policy", ["bacs_tw", "plus_tw", "plus_tw_sub", "plus_tw_sub_relgate",
                                    "plus_tw_arr", "plus_tw_arr_sub"])
def test_budget_respected(policy):
    rng = np.random.default_rng(1)
    c = ctx()
    cands = [cand(int(rng.integers(1, 4)), rng.uniform(0, 14, 2), theta=float(rng.uniform(0, 1)),
                  payload=int(rng.integers(28, 70)), t=float(i)) for i in range(60)]
    fill_info(cands, c)
    for budget in (0.05, 0.2, 0.6, 3.0):
        cfg = SchedulerConfig(policy=policy, rel_gate=0.5)
        chosen = schedule(cands, budget, cfg, LORA, rng, ctx=c)
        assert sum(time_on_air(x.payload_bytes, LORA) for x in chosen) <= budget + 1e-12
        assert len({id(x) for x in chosen}) == len(chosen)


def test_gates():
    c = ctx()
    cands = [cand(1, (i, 0.0), theta=th) for i, th in enumerate((0.01, 0.2, 0.4, 0.8))]
    fill_info(cands, c)
    big = 10.0
    abs_gated = schedule(cands, big, SchedulerConfig(policy="plus_tw"), LORA, None, ctx=c)
    assert {x.theta_hat for x in abs_gated} == {0.2, 0.4, 0.8}
    # median 0.3 -> threshold 0.15 at g=0.5
    rel = schedule(cands, big, SchedulerConfig(policy="plus_tw_sub_relgate", rel_gate=0.5), LORA, None, ctx=c)
    assert {x.theta_hat for x in rel} == {0.2, 0.4, 0.8}
    rel = schedule(cands, big, SchedulerConfig(policy="plus_tw_sub_relgate", rel_gate=2.0), LORA, None, ctx=c)
    assert {x.theta_hat for x in rel} == {0.8}


def test_submodular_first_pick_matches_static():
    rng = np.random.default_rng(3)
    c = ctx()
    cands = [cand(int(rng.integers(1, 4)), rng.uniform(0, 14, 2), theta=float(rng.uniform(0.1, 1)))
             for _ in range(30)]
    fill_info(cands, c)
    budget = time_on_air(40, LORA) * 1.2
    a = schedule(cands, budget, SchedulerConfig(policy="plus_tw"), LORA, None, ctx=c)
    b = schedule(cands, budget, SchedulerConfig(policy="plus_tw_sub"), LORA, None, ctx=c)
    assert [id(x) for x in a] == [id(x) for x in b]


def test_arrival_trust_discounts_accumulated_age():
    g = np.log(2) / 155.0
    assert arrival_trust(0.8, 0.0, g) == pytest.approx(0.8)
    assert arrival_trust(0.8, 155.0, g) == pytest.approx(0.4)
    assert arrival_trust(0.8, -5.0, g) == pytest.approx(0.8)      # not yet created: no discount
    ages = np.linspace(0, 600, 13)
    vals = [arrival_trust(0.8, a, g) for a in ages]
    assert all(b < a for a, b in zip(vals, vals[1:]))


def test_arrival_ranking_demotes_old_candidates():
    # Same information and theta_hat; the old one has waited 300 s. TW ranks
    # by input order (tie), TW-Arrival must prefer the fresh one.
    c = ctx()
    c["t_now"] = 600.0
    old = cand(1, (0.0, 0.0), theta=0.8, t=300.0)
    fresh = cand(2, (40.0, 40.0), theta=0.8, t=600.0)
    fill_info([old, fresh], c)
    budget = time_on_air(40, LORA) * 1.2
    tw = schedule([old, fresh], budget, SchedulerConfig(policy="plus_tw"), LORA, None, ctx=c)
    arr = schedule([old, fresh], budget, SchedulerConfig(policy="plus_tw_arr"), LORA, None, ctx=c)
    assert tw[0] is old and arr[0] is fresh
    sub = schedule([old, fresh], budget, SchedulerConfig(policy="plus_tw_arr_sub"), LORA, None, ctx=c)
    assert sub[0] is fresh


def test_arrival_equals_tw_when_nothing_has_aged():
    rng = np.random.default_rng(5)
    c = ctx()
    cands = [cand(int(rng.integers(1, 4)), rng.uniform(0, 14, 2), theta=float(rng.uniform(0.1, 1)),
                  t=float(rng.uniform(0, 60))) for _ in range(40)]
    fill_info(cands, c)
    for budget in (0.1, 0.5):
        a = schedule(cands, budget, SchedulerConfig(policy="plus_tw"), LORA, None, ctx=c)
        b = schedule(cands, budget, SchedulerConfig(policy="plus_tw_arr"), LORA, None, ctx=c)
        assert [id(x) for x in a] == [id(x) for x in b]


def test_diagnostics_do_not_change_results():
    from bacs_sim.experiments import s8_config
    from bacs_sim.simulator import precompute, run
    cfg = s8_config("plus_tw_arr_sub", seed=1, n_robots=3, session_s=180.0)
    pre = precompute(cfg)
    a = run(cfg, precomputed=pre)
    b = run(cfg, precomputed=pre, collect_diag=True)
    assert (a.align_rmse, a.pose_rmse, a.n_delivered) == (b.align_rmse, b.pose_rmse, b.n_delivered)
    rows = b.extras["diag"]
    assert len(rows) == b.n_sent and sum(r["delivered"] for r in rows) == b.n_delivered
    for r in rows:
        if r["delivered"]:
            assert r["age_arrival"] >= r["age_send"] >= 0
            assert 0 <= r["retention"] <= 1 + 1e-9
