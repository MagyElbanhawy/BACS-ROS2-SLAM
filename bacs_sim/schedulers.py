"""
Scheduling policies.  Section 3.6, Eqs. (13)-(14).

Every policy has the same signature so that Scenario 1 can swap them freely.
A policy receives the candidate list for one window and the airtime budget, and
returns the admitted subset in transmission order.
"""
import math

import numpy as np

from .config import SchedulerConfig
from .lora import time_on_air

POLICIES = ["send_all", "fifo", "lifo", "random", "greedy_trust", "greedy_info",
            "trust_only", "info_only", "bacs", "bacs_gated", "bacs_plus"]

# Revision-v3 baselines. Each differs from bacs_gated only in its ranking key:
# same per-window airtime budget, window, expiry (applied by the simulator) and
# greedy packing via _pack_by_key.
BASELINES = ["lifo", "random", "trust_only", "info_only"]

# Ranking v2: rank admitted candidates by the expected *effective* information
# the fusion server will extract, I_tw = 1/2 log(1 + theta * (exp(2 I) - 1)),
# per second of airtime. I is the BACS+ surrogate I_hat_plus. The variants
# differ only in which trust enters I_tw:
#   tw_now          theta at the candidate's current age
#   tw_arrival      theta at its predicted arrival age (Eqs. 8-10)
#   tw_arrival_sub  tw_arrival with diminishing returns inside the greedy loop
# Gate, budget, window, expiry and greedy packing are those of bacs_gated.
TW_POLICIES = ["tw_now", "tw_arrival", "tw_arrival_sub"]
POLICIES += TW_POLICIES


def _fits(chosen, cand, budget, lora):
    used = sum(time_on_air(c.payload_bytes, lora) for c in chosen)
    return used + time_on_air(cand.payload_bytes, lora) <= budget


def _density(c, lora):
    """Information per second of airtime, the bacs_gated ranking key."""
    return c.info_hat / max(time_on_air(c.payload_bytes, lora), 1e-9)


def _pack_by_key(cands, key, budget, lora, unlimited=False):
    """Greedy admission in descending key order, subject to the airtime budget."""
    if unlimited:
        return list(cands)
    order = sorted(cands, key=key, reverse=True)
    chosen, used = [], 0.0
    for c in order:
        t = time_on_air(c.payload_bytes, lora)
        if used + t <= budget:
            chosen.append(c)
            used += t
    return chosen


def tw_info(theta: float, info: float) -> float:
    """Effective information of a trust-weighted constraint.

    A constraint worth `info` nats when fully trusted (theta = 1) has its
    information matrix scaled by theta at the server; for a scalar channel the
    gain becomes 1/2 log(1 + theta * s) with s = exp(2 info) - 1. Monotone
    increasing in theta and info, 0 at theta = 0, equal to info at theta = 1.
    """
    s_c = math.expm1(2.0 * max(info, 0.0))
    return 0.5 * math.log1p(max(theta, 0.0) * s_c)


def theta_now(c, ctx) -> float:
    """Predicted trust at the candidate's current age a_c (decision time)."""
    age = max(ctx["t_now"] - c.t_created, 0.0)
    return max(ctx["trust"].floor, c._spatial * math.exp(-ctx["gamma"] * age))


def predicted_arrival_age(c, ctx) -> float:
    """Eqs. (8)-(10): k_c * W + queue airtime ahead + T_air + expected retry time."""
    lora = ctx["lora"]
    t_air = time_on_air(c.payload_bytes, lora)
    pl = min(max(ctx["p_loss"], 0.0), 0.95)
    t_retry = (pl / (1.0 - pl)) * (t_air + lora.ack_timeout_s)
    return c.deferrals * ctx["window_s"] + c._queue_ahead + t_air + t_retry


def theta_arrival(c, ctx) -> float:
    """Predicted trust at the predicted arrival age (Eq. 9 form, floored)."""
    age = predicted_arrival_age(c, ctx)
    return max(ctx["trust"].floor, c._spatial * math.exp(-ctx["gamma"] * age))


def _info_plus(c, ctx, novelty=None, obs=None) -> float:
    """I_hat_plus from stored components, optionally with updated novelty / O_ij."""
    from .infogain import surrogate_info
    icfg = ctx["infogain"]
    nov = c._nov if novelty is None else novelty
    o = ctx["pair_obs"].score(c.rid_from, c.rid_to) if obs is None else obs
    return surrogate_info(nov, c._deg, c._loop, icfg, observability=0.0) + icfg.w_obs * o


def _tw_score(c, theta, info, lora) -> float:
    return tw_info(theta, info) / max(time_on_air(c.payload_bytes, lora), 1e-9)


def _sub_score(c, ctx, cov, extra, theta):
    """tw_arrival score with provisional pair counts `extra` and coverage `cov`."""
    k = ctx["pair_obs"]._key(c.rid_from, c.rid_to)
    o = math.exp(-(ctx["pair_obs"].count(c.rid_from, c.rid_to) + extra.get(k, 0)) / ctx["pair_obs"].n_ref)
    return _tw_score(c, theta, _info_plus(c, ctx, novelty=cov.novelty(c._xy), obs=o), ctx["lora"])


def _coverage_copy(ctx):
    from .infogain import CoverageMap
    cov = CoverageMap(ctx["infogain"])
    cov.cells = set(ctx["coverage"].cells)
    return cov


def _pack_submodular(cands, budget, lora, ctx):
    """Greedy packing with diminishing returns (tw_arrival_sub).

    After each selection the pair counter n_ij is provisionally incremented and
    the candidate's location marked in a copy of the coverage map, then the
    remaining candidates are re-scored and re-ranked. Trust is not re-scored.
    """
    cov = _coverage_copy(ctx)
    extra = {}                                   # pair key -> provisional count
    theta = {id(c): theta_arrival(c, ctx) for c in cands}
    remaining, chosen, used = list(cands), [], 0.0
    while remaining:
        fitting = [c for c in remaining if used + time_on_air(c.payload_bytes, lora) <= budget]
        if not fitting:
            break
        best = max(fitting, key=lambda c: _sub_score(c, ctx, cov, extra, theta[id(c)]))  # first on ties
        chosen.append(best)
        used += time_on_air(best.payload_bytes, lora)
        remaining.remove(best)
        k = ctx["pair_obs"]._key(best.rid_from, best.rid_to)
        extra[k] = extra.get(k, 0) + 1
        cov.mark(best._xy)
    return chosen


def schedule(cands, budget, cfg: SchedulerConfig, lora, rng: np.random.Generator, ctx=None):
    """
    Dispatch to the configured policy.

    Candidates arrive with theta_hat, info_hat, and utility already populated by
    the simulator, which owns the channel-state estimates those quantities need.
    `ctx` (decision time, gamma, loss estimate, coverage map, pair counter, ...)
    is needed only by the TW_POLICIES.
    """
    if cfg.unlimited_budget or cfg.policy == "send_all":
        return list(cands)

    if cfg.policy == "fifo":
        # The parent framework's behaviour: oldest first, which is precisely the
        # ordering that maximises the temporal penalty on what gets sent.
        return _pack_by_key(cands, lambda c: -c.t_created, budget, lora)

    if cfg.policy == "lifo":
        # Newest candidate first: the mirror image of FIFO.
        return _pack_by_key(cands, lambda c: c.t_created, budget, lora)

    if cfg.policy == "random":
        # Uniform random order. The simulator passes a scheduler-only stream
        # seeded from the experiment seed, so the draws do not perturb the
        # channel or world randomness shared with the other policies.
        u = rng.random(len(cands))
        rank = {id(c): u[i] for i, c in enumerate(cands)}
        return _pack_by_key(cands, lambda c: rank[id(c)], budget, lora)

    if cfg.policy == "trust_only":
        # Predicted trust as the ranking key, no information term.
        return _pack_by_key(cands, lambda c: c.theta_hat, budget, lora)

    if cfg.policy == "info_only":
        # bacs_gated's information-density ranking with the trust gate removed.
        return _pack_by_key(cands, lambda c: _density(c, lora), budget, lora)

    if cfg.policy == "greedy_trust":
        return _pack_by_key(cands, lambda c: c.theta_hat, budget, lora)

    if cfg.policy == "greedy_info":
        return _pack_by_key(cands, lambda c: c.info_hat, budget, lora)

    if cfg.policy == "bacs":
        return _knapsack_greedy(cands, budget, lora)

    if cfg.policy in ("bacs_gated", "bacs_plus"):
        # Predicted trust used as an admissibility filter rather than a ranking
        # key, then ranked by information density.  Motivated by the finding
        # that ranking on theta_hat is self-confirming: it favours constraints
        # agreeing with the robot's current estimate, which are precisely the
        # ones carrying least corrective information.
        #
        # "bacs_plus" uses the identical scheduling mechanism; the difference is
        # in info_hat itself, which carries the observability term (set by the
        # simulator when use_observability is enabled for this policy).
        gate = cfg.trust_gate if cfg.trust_gate > 0 else 0.05
        keep = [c for c in cands if c.theta_hat >= gate] or list(cands)
        return _pack_by_key(keep, lambda c: _density(c, lora), budget, lora)

    if cfg.policy in TW_POLICIES:
        gate = cfg.trust_gate if cfg.trust_gate > 0 else 0.05
        keep = [c for c in cands if c.theta_hat >= gate] or list(cands)
        if cfg.policy == "tw_arrival_sub":
            return _pack_submodular(keep, budget, lora, ctx)
        trust_of = theta_now if cfg.policy == "tw_now" else theta_arrival
        # info_hat already carries the observability term for these policies.
        return _pack_by_key(keep, lambda c: _tw_score(c, trust_of(c, ctx), c.info_hat, lora), budget, lora)

    raise ValueError(f"unknown policy: {cfg.policy}")


def _knapsack_greedy(cands, budget, lora):
    """
    Eq. (14) solved by density-greedy with the single-best-item guard.

    Sorting by utility density and admitting greedily, then returning whichever
    of that set and the single highest-utility candidate carries more value,
    is a 1/2-approximation to the 0/1 knapsack optimum in O(n log n).  In this
    setting the guarantee is pessimistic: individual constraints are small
    relative to the window budget, so the greedy set is normally near-optimal.
    """
    feasible = [c for c in cands if time_on_air(c.payload_bytes, lora) <= budget]
    if not feasible:
        return []

    greedy = _pack_by_key(feasible, lambda c: c.utility, budget, lora)
    val_greedy = sum(c.theta_hat * c.info_hat for c in greedy)

    best_single = max(feasible, key=lambda c: c.theta_hat * c.info_hat)
    val_single = best_single.theta_hat * best_single.info_hat

    return greedy if val_greedy >= val_single else [best_single]


def compute_utility(c, cfg: SchedulerConfig, lora) -> float:
    """
    u_ij = theta_hat * I_hat / T_air, with the ageing multiplier.

    The ablation switches let Scenario 5 remove each factor in turn:
    dropping the cost term converts utility density back to raw utility,
    which should hurt most in the small-budget regime where packet size matters.
    """
    u = 1.0
    if cfg.use_trust_term:
        u *= c.theta_hat
    if cfg.use_info_term:
        u *= c.info_hat
    if cfg.use_cost_term:
        u /= max(time_on_air(c.payload_bytes, lora), 1e-9)
    if cfg.use_ageing:
        u *= (1.0 + cfg.ageing_beta * c.deferrals)
    return float(u)
