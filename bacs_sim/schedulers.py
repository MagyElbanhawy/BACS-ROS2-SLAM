"""
Scheduling policies.  Section 3.6, Eqs. (13)-(14).

Every policy has the same signature so that Scenario 1 can swap them freely.
A policy receives the candidate list for one window and the airtime budget, and
returns the admitted subset in transmission order.
"""
import copy
import math

import numpy as np

from .config import SchedulerConfig
from .infogain import surrogate_info
from .lora import time_on_air

POLICIES = ["send_all", "fifo", "lifo", "random", "greedy_trust", "greedy_info",
            "trust_only", "info_only", "bacs", "bacs_gated", "bacs_plus",
            "bacs_tw", "plus_tw", "plus_tw_sub", "plus_tw_sub_relgate",
            "plus_tw_arr", "plus_tw_arr_sub"]

# Ranking-v2 variants whose info_hat carries the BACS+ observability term.
OBS_POLICIES = ("bacs_plus", "plus_tw", "plus_tw_sub", "plus_tw_sub_relgate",
                "plus_tw_arr", "plus_tw_arr_sub")
# Variants that rank on trust predicted at arrival (see _rank_trust).
ARRIVAL_POLICIES = ("plus_tw_arr", "plus_tw_arr_sub")
SUB_POLICIES = ("plus_tw_sub", "plus_tw_sub_relgate", "plus_tw_arr_sub")

# Revision-v3 baselines. Each differs from bacs_gated only in its ranking key:
# same per-window airtime budget, window, expiry (applied by the simulator) and
# greedy packing via _pack_by_key.
BASELINES = ["lifo", "random", "trust_only", "info_only"]


def _fits(chosen, cand, budget, lora):
    used = sum(time_on_air(c.payload_bytes, lora) for c in chosen)
    return used + time_on_air(cand.payload_bytes, lora) <= budget


def _density(c, lora):
    """Information per second of airtime, the bacs_gated ranking key."""
    return c.info_hat / max(time_on_air(c.payload_bytes, lora), 1e-9)


def trust_weighted_info(info_hat: float, theta_hat: float) -> float:
    """I_tw = 0.5*log(1 + theta*(exp(2I) - 1)).

    Reads I_hat as a Gaussian gain 0.5*log(1 + s) with SNR s = exp(2I) - 1 and
    scales that SNR by the predicted trust, i.e. the constraint's information
    matrix is down-weighted by theta_hat. I_tw = I_hat at theta = 1, 0 at
    theta = 0, and increasing in both arguments.
    """
    s = math.expm1(2.0 * max(info_hat, 0.0))
    return 0.5 * math.log1p(max(theta_hat, 0.0) * s)


def arrival_trust(theta_hat: float, age: float, gamma: float) -> float:
    """theta_hat discounted by the age the candidate has already accumulated.

    theta_hat = spatial * exp(-gamma * dt_hat) covers only the delay still ahead
    (deferral, queueing, airtime, retries), whereas the server decays trust over
    the full age t_recv - t_created. Multiplying by exp(-gamma * age) gives
    spatial * exp(-gamma * (age + dt_hat)), the predicted trust at arrival.
    """
    return theta_hat * math.exp(-gamma * max(age, 0.0))


def _rank_trust(c, cfg: SchedulerConfig, ctx):
    """Trust used inside I_tw: arrival-time for the *_arr policies, else theta_hat."""
    if cfg.policy in ARRIVAL_POLICIES:
        return arrival_trust(c.theta_hat, ctx["t_now"] - c.t_created, ctx["gamma"])
    return c.theta_hat


def _tw_density(c, lora, theta):
    return trust_weighted_info(c.info_hat, theta) / max(time_on_air(c.payload_bytes, lora), 1e-9)


def _gate(cands, cfg: SchedulerConfig):
    """Absolute gate as in bacs_gated, or a gate relative to the window median."""
    if cfg.policy == "plus_tw_sub_relgate":
        thr = cfg.rel_gate * float(np.median([c.theta_hat for c in cands])) if cands else 0.0
    else:
        thr = cfg.trust_gate if cfg.trust_gate > 0 else 0.05
    return [c for c in cands if c.theta_hat >= thr] or list(cands)


def _pack_submodular(cands, budget, lora, ctx, trust=lambda c: c.theta_hat):
    """Greedy packing with diminishing returns inside the window.

    After each pick for pair (i, j) the pair count n_ij is provisionally
    incremented and the pick's location marked in a copy of the coverage map;
    I_hat_plus and I_tw are then recomputed for the remaining candidates before
    the next pick. Node degree and trust are left at their window values. The
    live coverage map and pair counter are not modified.
    """
    icfg = ctx["infogain"]
    cov = copy.deepcopy(ctx["coverage"])
    obs = copy.deepcopy(ctx["pair_obs"])
    remaining = list(cands)
    chosen, used = [], 0.0

    def score(c):
        ig = surrogate_info(cov.novelty(c.xy_from), c.degree_from, c.loop_len, icfg)
        ig += icfg.w_obs * obs.score(c.rid_from, c.rid_to)
        return trust_weighted_info(ig, trust(c)) / max(time_on_air(c.payload_bytes, lora), 1e-9)

    while remaining:
        remaining = [c for c in remaining if used + time_on_air(c.payload_bytes, lora) <= budget]
        if not remaining:
            break
        # max() keeps the first of equal scores, matching the stable sort of
        # _pack_by_key, so the first pick is identical to plus_tw's.
        best = max(remaining, key=score)
        chosen.append(best)
        used += time_on_air(best.payload_bytes, lora)
        remaining = [c for c in remaining if c is not best]
        obs.mark(best.rid_from, best.rid_to)
        cov.mark(best.xy_from)
    return chosen


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


def schedule(cands, budget, cfg: SchedulerConfig, lora, rng: np.random.Generator,
             ctx=None):
    """
    Dispatch to the configured policy.

    Candidates arrive with theta_hat, info_hat, and utility already populated by
    the simulator, which owns the channel-state estimates those quantities need.
    `ctx` (coverage map, pair counter, InfoGainConfig) is needed only by the
    submodular variants, which recompute info_hat inside the greedy loop.
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

    if cfg.policy in ARRIVAL_POLICIES + SUB_POLICIES and ctx is None:
        raise ValueError(f"{cfg.policy} needs ctx (coverage, pair_obs, infogain, gamma, t_now)")

    if cfg.policy in ("bacs_tw", "plus_tw", "plus_tw_arr"):
        # Ranking v2: bacs_gated's gate, budget and packing, ranked by the
        # trust-weighted gain I_tw per second of airtime. plus_tw differs only
        # in info_hat, which carries the observability term; plus_tw_arr only
        # in the trust inside I_tw (arrival-time). The gate stays on theta_hat.
        return _pack_by_key(_gate(cands, cfg),
                            lambda c: _tw_density(c, lora, _rank_trust(c, cfg, ctx)), budget, lora)

    if cfg.policy in SUB_POLICIES:
        return _pack_submodular(_gate(cands, cfg), budget, lora, ctx,
                                trust=lambda c: _rank_trust(c, cfg, ctx))

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
