"""
System model for Bandwidth-Aware Constraint Scheduling (BACS).

Implements the components defined in Paper A, Section 3:
  Eq. (1)      duty-cycle airtime budget
  Eq. (2)-(4)  LoRa time-on-air
  Eq. (5)-(6)  predicted end-to-end delay
  Eq. (7)      server-side trust factor (EMRMF)
  Eq. (8)-(10) provisional residual and predicted trust
  Eq. (11)-(12) information gain and surrogate
  Eq. (16)-(17) gamma design rule and online adaptation

SCOPE NOTE  --  which simulator produces which table
------------------------------------------------------
This repository contains two deliberately separate models. This one,
`bacs_sim.model`, is a SELF-CONTAINED COMMUNICATION-LAYER reference: airtime,
delay, packet loss, trust scores, delivered information, starvation. It does
NOT simulate SLAM and does NOT produce pose RMSE. It exists as a compact,
readable statement of the closed-form quantities of Section 3 (its own
LoRaConfig/TrustParams/Predictor are intentionally standalone and are NOT
imported by the rest of the package), and as the layer a hardware bridge would
mirror.

Every number reported in the manuscript -- every pose_rmse, align_rmse,
trust_yield, and all of Tables/Scenarios S1-S9 -- comes from the CANONICAL
full-pipeline simulator, which is the OTHER set of modules:

    world.py  -> ground truth, odometry drift, candidate generation
    lora.py   -> airtime budget and channel  (Eqs. 1-4)
    trust.py  -> server and predicted trust, gamma rules  (Eqs. 5-9, 15-17)
    infogain.py, observability.py -> Eq. 12 surrogate and the BACS+ term
    schedulers.py -> the policies  (Eqs. 13-14)
    posegraph.py  -> the SE(2) weighted Gauss-Newton back-end
    simulator.py  -> the windowed loop that ties them together and reports RMSE
    experiments.py -> the S1-S9 runners

`bacs_sim.model` and the canonical pipeline share the same equations by
construction but do not share code, so if you change a formula, change it in
both. Nothing here is on the path that generates a manuscript table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

# ---------------------------------------------------------------------------
# LoRa physical layer  --  Eq. (2)-(4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LoRaConfig:
    """Radio configuration. Defaults match RYLR998 @ 868 MHz, SF9/BW125."""

    sf: int = 9                 # spreading factor 7..12
    bw: float = 125_000.0       # bandwidth [Hz]
    cr: int = 1                 # coding rate index 1..4  -> 4/(4+cr)
    preamble: int = 8           # preamble symbols
    crc: int = 1                # CRC enabled
    implicit_header: int = 0    # explicit header
    duty_cycle: float = 0.01    # EU868 g1 sub-band ceiling  -- Eq. (1)

    @property
    def low_data_rate_opt(self) -> int:
        """Mandatory when symbol time > 16 ms (SF11/SF12 at BW125)."""
        return 1 if (2 ** self.sf) / self.bw > 0.016 else 0

    def symbol_time(self) -> float:
        """Eq. (2):  T_sym = 2^SF / BW"""
        return (2 ** self.sf) / self.bw

    def time_on_air(self, payload_bytes: int) -> float:
        """Eq. (3)-(4): packet duration [s] for a payload of PL bytes.

        Step function of payload size -- the property BACS exploits via the
        cost term of the utility density.
        """
        t_sym = self.symbol_time()
        de = self.low_data_rate_opt
        num = (8 * payload_bytes - 4 * self.sf + 28
               + 16 * self.crc - 20 * self.implicit_header)
        den = 4 * (self.sf - 2 * de)
        n_payload = 8 + max(math.ceil(num / den) * (self.cr + 4), 0)
        t_preamble = (self.preamble + 4.25) * t_sym
        return t_preamble + n_payload * t_sym

    def window_budget(self, window_s: float) -> float:
        """Eq. (1):  B(W) = delta * W  [seconds of airtime]"""
        return self.duty_cycle * window_s


# ---------------------------------------------------------------------------
# Candidate constraints
# ---------------------------------------------------------------------------


@dataclass
class Constraint:
    """A candidate inter-robot constraint awaiting a transmission decision."""

    cid: int
    robot: int
    region: int             # for the starvation index
    residual: float         # true ||e_ij|| [m], known only to the server
    payload: int            # serialised size [bytes]
    info_true: float        # latent information gain, ground truth for scoring
    nu: float               # novelty term        -- Eq. (12)
    deg: float              # normalised degree   -- Eq. (12)
    loop: float             # normalised loop len -- Eq. (12)
    born_window: int
    deferrals: int = 0      # windows spent waiting (drives the ageing term)

    # populated during transmission
    delay: float | None = None
    delivered: bool = False
    theta_server: float | None = None


@dataclass
class ConstraintGenerator:
    """Generative model of the candidate stream leaving the SLAM front-end.

    Residuals follow the two-population structure reported in the EMRMF study:
    genuine loop closures below ~0.35 m, false associations above ~0.70 m.

    The surrogate terms nu/deg/loop are generated as NOISY OBSERVATIONS of the
    latent information gain, with the correlation controlled by
    `surrogate_rho`. This makes surrogate fidelity an explicit swept parameter
    rather than an unstated assumption -- see Paper A Section 4.4.
    """

    rng: np.random.Generator
    rate_per_window: float = 40.0    # candidates generated per window per robot
    outlier_frac: float = 0.18
    inlier_scale: float = 0.14       # half-normal scale [m]
    outlier_lo: float = 0.70
    outlier_hi: float = 1.60
    base_bytes: int = 45             # pose + cov + ids + timestamp
    desc_bytes_lo: int = 0
    desc_bytes_hi: int = 72
    n_regions: int = 6
    surrogate_rho: float = 0.75      # target corr(surrogate, latent info)

    def _noisy(self, latent: np.ndarray) -> np.ndarray:
        """Mix latent signal with independent noise to hit a target correlation."""
        rho = float(np.clip(self.surrogate_rho, 0.0, 1.0))
        noise = self.rng.random(latent.shape)
        mixed = rho * latent + math.sqrt(max(1.0 - rho ** 2, 0.0)) * noise
        lo, hi = mixed.min(), mixed.max()
        return (mixed - lo) / (hi - lo + 1e-12)

    def generate(self, window: int, robot: int, next_id: int) -> list[Constraint]:
        n = self.rng.poisson(self.rate_per_window)
        if n == 0:
            return []

        is_out = self.rng.random(n) < self.outlier_frac
        residual = np.where(
            is_out,
            self.rng.uniform(self.outlier_lo, self.outlier_hi, n),
            np.abs(self.rng.normal(0.0, self.inlier_scale, n)),
        )

        payload = self.base_bytes + self.rng.integers(
            self.desc_bytes_lo, self.desc_bytes_hi + 1, n
        )

        # Latent information: larger payloads carry richer descriptors, and
        # outliers carry little real information.
        latent = self.rng.beta(2.0, 3.0, n)
        latent *= (0.35 + 0.65 * (payload - self.base_bytes) /
                   max(self.desc_bytes_hi, 1))
        latent = np.where(is_out, latent * 0.25, latent)
        latent = latent / (latent.max() + 1e-12)

        nu = self._noisy(latent)
        loop = self._noisy(latent)
        deg = 1.0 - self._noisy(latent)   # low degree -> high value

        region = self.rng.integers(0, self.n_regions, n)

        out = []
        for k in range(n):
            out.append(Constraint(
                cid=next_id + k,
                robot=robot,
                region=int(region[k]),
                residual=float(residual[k]),
                payload=int(payload[k]),
                info_true=float(latent[k]),
                nu=float(nu[k]),
                deg=float(deg[k]),
                loop=float(loop[k]),
                born_window=window,
            ))
        return out


# ---------------------------------------------------------------------------
# Channel  --  loss and delay beyond airtime
# ---------------------------------------------------------------------------


@dataclass
class Channel:
    """Independent (Bernoulli) or bursty (Gilbert-Elliott) packet loss."""

    rng: np.random.Generator
    loss: float = 0.0
    burst: bool = False
    p_gb: float = 0.05          # good -> bad
    p_bg: float = 0.35          # bad  -> good
    loss_good: float = 0.01
    loss_bad: float = 0.75
    base_delay: float = 0.0     # fixed network delay beyond airtime [s]
    jitter: float = 0.0         # std of extra delay [s]
    _state_bad: bool = field(default=False, init=False)

    def step_loss(self) -> bool:
        """True if the packet is lost."""
        if not self.burst:
            return bool(self.rng.random() < self.loss)
        if self._state_bad:
            lost = self.rng.random() < self.loss_bad
            if self.rng.random() < self.p_bg:
                self._state_bad = False
        else:
            lost = self.rng.random() < self.loss_good
            if self.rng.random() < self.p_gb:
                self._state_bad = True
        return bool(lost)

    def extra_delay(self) -> float:
        d = self.base_delay
        if self.jitter > 0:
            d += abs(self.rng.normal(0.0, self.jitter))
        return d


# ---------------------------------------------------------------------------
# Trust  --  Eq. (7), (9), (16), (17)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrustParams:
    tau_e: float = 0.50     # admissible residual threshold [m]
    p: int = 3              # shaping exponent
    gamma: float = 0.10     # temporal decay coefficient [1/s]
    accept: float = 0.10    # acceptance threshold on theta


def theta(residual: float, dt: float, tp: TrustParams,
          gamma: float | None = None) -> float:
    """Eq. (7): server-side trust factor."""
    g = tp.gamma if gamma is None else gamma
    spatial = max(0.0, 1.0 - (abs(residual) / tp.tau_e) ** tp.p)
    return spatial * math.exp(-g * max(dt, 0.0))


def gamma_design_rule(drift_rate: float, mean_speed: float,
                      tau_e: float) -> float:
    """Eq. (16):  gamma* = ln2 * sigma_d * v_bar / tau_e

    drift_rate  sigma_d [m of position error per m travelled]
    mean_speed  v_bar   [m/s]
    """
    return math.log(2.0) * drift_rate * mean_speed / tau_e


@dataclass
class AdaptiveGamma:
    """Eq. (17):  gamma_t = gamma* * (1 + kappa * sigma_dt / mu_dt), clipped.

    Mean and standard deviation of observed delay are tracked by EWMA from
    server acknowledgements.
    """

    gamma_star: float
    kappa: float = 0.5
    alpha: float = 0.2                 # EWMA factor
    clip: tuple[float, float] = (0.01, 1.0)
    mu: float = 0.0
    var: float = 0.0
    _init: bool = field(default=False, init=False)

    def update(self, observed_delay: float) -> None:
        if not self._init:
            self.mu, self.var, self._init = observed_delay, 0.0, True
            return
        prev = self.mu
        self.mu += self.alpha * (observed_delay - self.mu)
        self.var = (1 - self.alpha) * (self.var +
                                       self.alpha * (observed_delay - prev) ** 2)

    def value(self) -> float:
        if not self._init or self.mu <= 1e-9:
            return self.gamma_star
        cv = math.sqrt(max(self.var, 0.0)) / self.mu
        g = self.gamma_star * (1.0 + self.kappa * cv)
        return float(np.clip(g, *self.clip))


# ---------------------------------------------------------------------------
# Transmitter-side prediction  --  Eq. (5), (6), (8)-(10), (12)
# ---------------------------------------------------------------------------


@dataclass
class Predictor:
    """Everything the robot can compute before it transmits."""

    radio: LoRaConfig
    tp: TrustParams
    rng: np.random.Generator
    w_nu: float = 0.5
    w_deg: float = 0.2
    w_loop: float = 0.3
    v_max: float = 0.6              # peer speed bound [m/s], for Eq. (10)
    loss_ewma: float = 0.0
    timeout: float = 1.0            # T_to [s]

    def info_surrogate(self, c: Constraint) -> float:
        """Eq. (12): weighted surrogate for the exact mutual information."""
        return (self.w_nu * c.nu
                + self.w_deg * (1.0 - c.deg)
                + self.w_loop * c.loop)

    def retry_delay(self, payload: int) -> float:
        """Eq. (6): expected retransmission delay under geometric losses."""
        p = min(max(self.loss_ewma, 0.0), 0.95)
        return (p / (1.0 - p)) * (self.radio.time_on_air(payload) + self.timeout)

    def predicted_delay(self, queue_air: float, payload: int) -> float:
        """Eq. (5): queueing + own airtime + expected retransmission."""
        return (queue_air
                + self.radio.time_on_air(payload)
                + self.retry_delay(payload))

    def provisional_residual(self, c: Constraint, map_age: float) -> float:
        """Eq. (8) with the error bound of Eq. (10).

        The peer pose comes from the last received global map, so the
        provisional residual differs from the server's by at most
        v_max * map_age.
        """
        bound = self.v_max * max(map_age, 0.0)
        err = self.rng.uniform(-bound, bound) if bound > 0 else 0.0
        return abs(c.residual + err)

    def map_confidence(self, map_age: float, horizon: float = 8.0) -> float:
        """Confidence in the geometric prediction, decaying with map age.

        At confidence 0 the scheduler falls back to information-only ranking,
        which is the intended behaviour during a server outage.
        """
        return float(np.clip(1.0 - map_age / horizon, 0.0, 1.0))

    def predicted_theta(self, c: Constraint, queue_air: float,
                        map_age: float, gamma: float) -> float:
        """Eq. (9), blended toward a uniform prior as the global map ages."""
        dt_hat = self.predicted_delay(queue_air, c.payload)
        res_hat = self.provisional_residual(c, map_age)
        spatial = max(0.0, 1.0 - (res_hat / self.tp.tau_e) ** self.tp.p)
        conf = self.map_confidence(map_age)
        spatial = conf * spatial + (1.0 - conf) * 1.0
        return spatial * math.exp(-gamma * dt_hat)
