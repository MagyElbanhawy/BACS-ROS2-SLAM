"""
Trust factor computation.

Server side  : Eq. (7), unchanged from the parent framework.
Transmitter  : Eqs. (5), (6), (8), (9) - prediction of the score the server
               will assign, using only quantities the robot holds.
Decay rule   : Eqs. (15)-(17) - fixed, physically derived, and adaptive gamma.
"""
import numpy as np

from .config import TrustConfig, WorldConfig
from .lora import time_on_air


# ------------------------------------------------------------------- Eq. (7)
def server_trust(residual_norm: float, dt: float, cfg: TrustConfig,
                 gamma: float = None) -> float:
    """theta_ij = max(0, 1 - (||e||/tau)^p) * exp(-gamma*dt), floored."""
    g = cfg.gamma if gamma is None else gamma
    spatial = max(0.0, 1.0 - (residual_norm / cfg.tau_e) ** cfg.p)
    temporal = float(np.exp(-g * max(dt, 0.0)))
    return max(cfg.floor, spatial * temporal)


# ------------------------------------------------------------- Eqs. (5)-(6)
def predicted_delay(payload_bytes: int, queue_airtime: float, lora, p_loss_hat: float,
                    deferral_windows: float = 0.0, window_s: float = 0.0) -> float:
    """
    Delta t_hat = queueing + own airtime + expected retransmission.

    Monotone in queue position: a constraint placed later in the window is
    predicted to arrive staler, so the scheduler internalises the delay
    externality that admitting a packet imposes on everything behind it.
    """
    t_air = time_on_air(payload_bytes, lora)
    pl = min(max(p_loss_hat, 0.0), 0.95)
    t_retry = (pl / (1.0 - pl)) * (t_air + lora.ack_timeout_s)
    # Deferral term.  Under duty-cycle limitation the dominant contribution to
    # packet age is not propagation or within-window queueing but the number of
    # windows a constraint waits for airtime.  Omitting it - as the original
    # formulation did - underestimates delay by two orders of magnitude.
    return deferral_windows * window_s + queue_airtime + t_air + t_retry


# ------------------------------------------------------------------- Eq. (9)
def predicted_trust(provisional_residual: float, dt_hat: float,
                    cfg: TrustConfig, gamma: float, map_age: float = 0.0,
                    v_max: float = 0.3) -> float:
    """
    theta_hat, with the confidence blend described under Eq. (10).

    The provisional residual is computed against the last received global map,
    so its error is bounded by v_max * map_age.  As that bound grows the
    geometric term is blended toward a uniform prior, and in the limit the
    scheduler ranks on information gain alone - the correct fallback when there
    is no basis for predicting trust.
    """
    spatial = max(0.0, 1.0 - (provisional_residual / cfg.tau_e) ** cfg.p)
    conf = 1.0 / (1.0 + (v_max * max(map_age, 0.0)) / cfg.tau_e)
    spatial = conf * spatial + (1.0 - conf) * 1.0
    return max(cfg.floor, spatial * float(np.exp(-gamma * max(dt_hat, 0.0))))


# ------------------------------------------------------------ Eqs. (15)-(17)
def gamma_derived(world: WorldConfig, cfg: TrustConfig) -> float:
    """
    gamma* = ln2 * sigma_d * v_bar / tau_e.   Eq. (16).

    Half-life equals the time for accumulated odometry divergence to reach the
    admissible residual threshold.  Note this assumes divergence grows linearly
    with elapsed time; under a random-walk drift model it grows with the square
    root, and the correct exponent is an empirical question that Scenario 4
    settles by comparing gamma* against the measured optimum.
    """
    g = np.log(2.0) * world.drift_rate * world.speed / cfg.tau_e
    return float(np.clip(g, cfg.gamma_min, cfg.gamma_max))


def gamma_from_deferral(mean_delay: float, cfg: TrustConfig) -> float:
    """
    gamma = ln2 / T_defer.

    Sets the trust half-life equal to the timescale on which a candidate waits
    for airtime, rather than the odometry-drift timescale of Eq. (16). Section
    6.1 shows deferral dominates packet age under duty-cycle compliance, so this
    is the timescale gamma should track. Clipped to the configured range.
    """
    if mean_delay <= 1e-9:
        return float(np.clip(cfg.gamma, cfg.gamma_min, cfg.gamma_max))
    return float(np.clip(np.log(2.0) / mean_delay, cfg.gamma_min, cfg.gamma_max))


def gamma_deferral_derived(cfg: TrustConfig) -> float:
    """Static deferral rule: gamma = ln2 / t_defer_prior, using the a-priori
    deferral estimate from Section 6.1 (~155 s) rather than an online measurement."""
    return gamma_from_deferral(cfg.t_defer_prior, cfg)


class GammaController:
    """
    Maintains the decay coefficient in use.

    Because gamma appears identically in Eq. (7) at the server and Eq. (9) at
    the transmitter, a single controller object is shared by both ends of the
    link in this simulation - the deployment equivalent is publishing it on
    trust/gamma and echoing it in the packet header.
    """

    def __init__(self, cfg: TrustConfig, world: WorldConfig):
        self.cfg = cfg
        self.world = world
        if cfg.gamma_rule in ("derived", "adaptive"):
            self.base = gamma_derived(world, cfg)
        elif cfg.gamma_rule in ("deferral_derived", "deferral_adaptive"):
            self.base = gamma_deferral_derived(cfg)
        else:
            self.base = cfg.gamma
        self.value = self.base
        self.mu_dt = None
        self.var_dt = None
        self.p_loss = 0.0
        self.history = []

    def observe(self, dt: float, lost: bool):
        """EWMA update of delay mean/variance and loss rate from acknowledgements."""
        a = self.cfg.ewma_alpha
        self.p_loss = (1 - a) * self.p_loss + a * (1.0 if lost else 0.0)
        if lost:
            return
        if self.mu_dt is None:
            self.mu_dt, self.var_dt = dt, 0.0
        else:
            d = dt - self.mu_dt
            self.mu_dt += a * d
            self.var_dt = (1 - a) * (self.var_dt + a * d * d)

    def update(self):
        """Recompute the decay coefficient from the rule in force.

        "adaptive"          Eq. (17): gamma* modulated by the delay CV.
        "deferral_adaptive" gamma_t = clip(ln2 / measured mean deferral delay);
                            the mean is the EWMA of delivered end-to-end delay,
                            which under duty-cycle compliance is dominated by
                            airtime deferral.
        anything else       hold the base value.
        """
        rule = self.cfg.gamma_rule
        if rule == "adaptive" and self.mu_dt is not None and self.mu_dt > 1e-9:
            cv = np.sqrt(max(self.var_dt, 0.0)) / self.mu_dt
            self.value = float(np.clip(self.base * (1.0 + self.cfg.kappa * cv),
                                       self.cfg.gamma_min, self.cfg.gamma_max))
        elif rule == "deferral_adaptive" and self.mu_dt is not None and self.mu_dt > 1e-9:
            self.value = gamma_from_deferral(self.mu_dt, self.cfg)
        else:
            self.value = self.base
        self.history.append(self.value)
        return self.value
