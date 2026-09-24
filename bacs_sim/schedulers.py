"""
Scheduling policies.  Section 3.6, Eqs. (13)-(14).

Every policy has the same signature so that Scenario 1 can swap them freely.
A policy receives the candidate list for one window and the airtime budget, and
returns the admitted subset in transmission order.
"""
import numpy as np

from .config import SchedulerConfig
from .lora import time_on_air

POLICIES = ["send_all", "fifo", "random", "greedy_trust", "greedy_info",
            "bacs", "bacs_gated", "bacs_plus"]


def _fits(chosen, cand, budget, lora):
    used = sum(time_on_air(c.payload_bytes, lora) for c in chosen)
    return used + time_on_air(cand.payload_bytes, lora) <= budget


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


def schedule(cands, budget, cfg: SchedulerConfig, lora, rng: np.random.Generator):
    """
    Dispatch to the configured policy.

    Candidates arrive with theta_hat, info_hat, and utility already populated by
    the simulator, which owns the channel-state estimates those quantities need.
    """
    if cfg.unlimited_budget or cfg.policy == "send_all":
        return list(cands)

    if cfg.policy == "fifo":
        # The parent framework's behaviour: oldest first, which is precisely the
        # ordering that maximises the temporal penalty on what gets sent.
        return _pack_by_key(cands, lambda c: -c.t_created, budget, lora)

    if cfg.policy == "random":
        shuffled = list(cands)
        rng.shuffle(shuffled)
        return _pack_by_key(shuffled, lambda c: 0.0, budget, lora)

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
        return _pack_by_key(keep, lambda c: c.info_hat / max(time_on_air(c.payload_bytes, lora), 1e-9),
                            budget, lora)

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
