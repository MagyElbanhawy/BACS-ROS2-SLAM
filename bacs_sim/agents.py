"""
Agent behaviour.

Paper A assumes every robot is honest, so the default behaviour is a no-op and
the results below are unaffected by this module.  It exists because Paper B
extends the same backbone with adversarial robots, and the extension points are
easier to get right if they are defined before they are needed.

Two hooks are provided:

  on_report(constraint, ...)   applied to a constraint before it is measured
                               into the candidate set - the place where a robot
                               falsifies what it claims to have seen.

  on_declare(constraint, ...)  applied to the scheduling scores a robot reports
                               about its own candidate - the place where a robot
                               inflates its claim on shared airtime.

The second hook is the one the scheduler newly exposes.  A robot that overstates
its predicted trust or novelty captures a disproportionate share of a shared
duty cycle, which is a denial-of-service vector that the unscheduled parent
framework does not present.  Quantifying that is a Paper B result.
"""
import numpy as np

BEHAVIORS = ["honest", "drift_injection", "false_closure", "airtime_greedy", "colluding"]


class Agent:
    """Base: honest. Returns its inputs unchanged."""

    def __init__(self, rid: int, params: dict, rng: np.random.Generator):
        self.rid = rid
        self.params = params or {}
        self.rng = rng

    def on_report(self, c):
        return c

    def on_declare(self, theta_hat: float, info_hat: float):
        return theta_hat, info_hat


class DriftInjection(Agent):
    """
    Adds a small, consistent bias to every reported constraint.

    The defining property is that each individual measurement stays inside the
    admissible residual threshold, so the per-constraint trust factor of Eq. (7)
    accepts it.  Only the accumulation across many constraints reveals the
    attack, which is why per-agent reputation is needed and per-packet trust is
    not sufficient.
    """

    def on_report(self, c):
        b = self.params.get("bias", 0.15)
        ang = self.params.get("angle", 0.0)
        c.z = c.z + np.array([b * np.cos(ang), b * np.sin(ang), 0.0])
        c.tampered = True
        return c


class FalseClosure(Agent):
    """Occasional large fabricated closure; the classic outlier attack."""

    def on_report(self, c):
        if self.rng.random() < self.params.get("rate", 0.10):
            mag = self.params.get("magnitude", 2.5)
            ang = self.rng.uniform(0, 2 * np.pi)
            c.z = c.z + np.array([mag * np.cos(ang), mag * np.sin(ang),
                                  self.rng.normal(0, 0.5)])
            c.tampered = True
        return c


class AirtimeGreedy(Agent):
    """
    Reports inflated scheduling scores to capture shared airtime.

    Attacks the scheduler rather than the map. Measured by the share of the
    channel this robot wins relative to its honest entitlement.
    """

    def on_declare(self, theta_hat, info_hat):
        f = self.params.get("inflate", 3.0)
        return min(1.0, theta_hat * f), min(1.0, info_hat * f)


class Colluding(DriftInjection):
    """
    Drift injection with a shared bias direction across a coalition.

    Consistent bias between two robots mutually corroborates, defeating
    pairwise consistency checks that assume independent errors.
    """
    pass


_REGISTRY = {
    "honest": Agent,
    "drift_injection": DriftInjection,
    "false_closure": FalseClosure,
    "airtime_greedy": AirtimeGreedy,
    "colluding": Colluding,
}


def make_agent(rid: int, acfg, rng: np.random.Generator) -> Agent:
    cls = _REGISTRY.get(acfg.behavior, Agent)
    return cls(rid, acfg.params, rng)
