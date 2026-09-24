"""
Physical-layer model. Implements Paper A Section 3.1 (airtime budget) and
Section 3.2 (packet cost), plus the channel emulator used to produce the
measured delay the server sees.
"""
import math
import numpy as np

from .config import LoRaConfig, ChannelConfig


# ---------------------------------------------------------------- Eqs. (2)-(4)
def symbol_time(cfg: LoRaConfig) -> float:
    """T_sym = 2^SF / BW.  Eq. (2)."""
    return (2 ** cfg.sf) / cfg.bw


def payload_symbols(payload_bytes: int, cfg: LoRaConfig) -> int:
    """n_pay.  Eq. (3).  Standard LoRa modulation model."""
    de = 1 if cfg.low_data_rate_opt else 0
    ih = 1 if cfg.implicit_header else 0
    crc = 1 if cfg.crc else 0
    num = 8 * payload_bytes - 4 * cfg.sf + 28 + 16 * crc - 20 * ih
    den = 4 * (cfg.sf - 2 * de)
    return 8 + max(math.ceil(num / den) * (cfg.cr + 4), 0)


def time_on_air(payload_bytes: int, cfg: LoRaConfig) -> float:
    """T_air(PL).  Eq. (4).  Step function of payload size."""
    t_sym = symbol_time(cfg)
    t_pre = (cfg.n_preamble + 4.25) * t_sym
    return t_pre + payload_symbols(payload_bytes, cfg) * t_sym


def regulatory_budget(window_s: float, cfg: LoRaConfig) -> float:
    """
    B_reg = delta * W.  Eq. (1).

    The regulatory ceiling is a *per-device* airtime limit: EU868 g1 caps each
    transmitter at delta = 1% occupancy of any window, independent of how many
    other devices share the band.
    """
    return cfg.duty_cycle * window_s


def airtime_budget(window_s: float, cfg: LoRaConfig, n_robots: int = 1) -> float:
    """
    Usable per-robot airtime, B_i = alpha_i * B_reg with sum_i alpha_i <= 1.

    The regulatory limit and the per-robot *usable* budget are distinct. The
    former, B_reg = delta*W, applies to each device. The latter depends on how
    the shared channel is coordinated:

      * "shared_equal" (default): N robots contend for one sub-band with no
        access protocol, so collision avoidance forces a system-level split.
        Equal sharing gives alpha_i = 1/N and B_i = delta*W/N -- the division
        that drives Hypothesis H3. A non-default `cfg.alpha` overrides 1/N.
      * "per_device": orthogonal channels or a TDMA schedule let every robot use
        its full regulatory ceiling, alpha_i = 1, B_i = delta*W.

    Keeping the split explicit avoids conflating the legal duty cycle with the
    coordination assumption, which are separate modelling choices.
    """
    b_reg = regulatory_budget(window_s, cfg)
    share = getattr(cfg, "channel_share", "shared_equal")
    if share == "per_device":
        return b_reg
    alpha = getattr(cfg, "alpha", 0.0)
    if alpha and alpha > 0.0:
        return alpha * b_reg
    return b_reg / max(n_robots, 1)


# ------------------------------------------------------------------- channel
class Channel:
    """
    Emulates loss and delay on the shared link.

    Two loss models are provided.  The independent model matches the assumption
    behind Eq. (6).  The burst model (Gilbert-Elliott) deliberately violates it,
    so that Scenario 3 can measure how optimistic the delay predictor becomes
    when losses are correlated.
    """

    def __init__(self, cfg: ChannelConfig, lora: LoRaConfig, rng: np.random.Generator):
        self.cfg = cfg
        self.lora = lora
        self.rng = rng
        self._bad = False
        # Gilbert-Elliott transition probabilities from the requested stationary
        # occupancy and mean burst length.
        if cfg.ge_mean_burst > 1.0:
            self.p_bad_good = 1.0 / cfg.ge_mean_burst          # bad -> good
        else:
            self.p_bad_good = 1.0
        pb = min(max(cfg.ge_p_bad, 1e-6), 1 - 1e-6)
        self.p_good_bad = self.p_bad_good * pb / (1 - pb)      # good -> bad

    def _step_state(self):
        if self._bad:
            if self.rng.random() < self.p_bad_good:
                self._bad = False
        else:
            if self.rng.random() < self.p_good_bad:
                self._bad = True

    def _drop_prob(self) -> float:
        if self.cfg.loss_model == "burst":
            self._step_state()
            return self.cfg.ge_loss_bad if self._bad else self.cfg.ge_loss_good
        return self.cfg.loss_rate

    def transmit(self, payload_bytes: int, t_ready: float):
        """
        Attempt delivery of one packet offered to the radio at t_ready.

        Returns (delivered, t_recv, airtime_consumed, n_attempts).  Airtime is
        charged for every attempt including failures, because a lost packet
        still occupied the channel and still counts against the duty cycle.
        """
        t_air = time_on_air(payload_bytes, self.lora)
        t = t_ready
        used = 0.0
        for attempt in range(self.cfg.max_retries + 1):
            t += t_air
            used += t_air
            if self.rng.random() >= self._drop_prob():
                return True, t + self.cfg.extra_delay_s, used, attempt + 1
            t += self.lora.ack_timeout_s
        return False, t, used, self.cfg.max_retries + 1
