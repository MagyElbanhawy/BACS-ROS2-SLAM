"""
Configuration objects for the BACS simulation.

Every parameter that appears in Paper A has a home here, named to match the
symbol used in the text so that code and manuscript stay in sync.
"""
from dataclasses import dataclass, field, replace
from typing import Tuple


@dataclass
class LoRaConfig:
    """Physical-layer parameters. Section 3.2, Eqs. (2)-(4)."""
    sf: int = 7                 # spreading factor
    bw: float = 125_000.0       # bandwidth [Hz]
    cr: int = 1                 # coding rate index, 4/(4+cr)
    n_preamble: int = 8
    crc: bool = True
    implicit_header: bool = False
    low_data_rate_opt: bool = False
    duty_cycle: float = 0.01    # delta, regulatory ceiling (EU868 g1)
    ack_timeout_s: float = 0.5  # T_to in Eq. (6)
    # Channel-access assumption used to turn the *per-device* regulatory ceiling
    # into a *per-robot usable* budget (see lora.airtime_budget):
    #   "shared_equal": one sub-band shared by N robots with no coordination,
    #                   equal split alpha_i = 1/N  (the H3 mechanism);
    #   "per_device":   orthogonal channels / TDMA, each robot keeps delta*W.
    channel_share: str = "shared_equal"
    alpha: float = 0.0          # explicit per-robot share; <=0 means auto (1/N)


@dataclass
class ChannelConfig:
    """Emulated link behaviour."""
    loss_model: str = "independent"   # {"independent", "burst"}
    loss_rate: float = 0.0            # p_L
    extra_delay_s: float = 0.0        # fixed propagation/processing delay
    # Gilbert-Elliott parameters, used when loss_model == "burst"
    ge_p_bad: float = 0.30            # long-run fraction of time in bad state
    ge_mean_burst: float = 4.0        # mean consecutive packets lost in bad state
    ge_loss_good: float = 0.01
    ge_loss_bad: float = 0.85
    max_retries: int = 2


@dataclass
class TrustConfig:
    """Trust factor parameters. Section 3.4, Eqs. (7)-(9)."""
    tau_e: float = 0.5          # admissible residual threshold [m]
    p: int = 3                  # shaping exponent
    gamma: float = 0.10         # temporal decay [1/s]
    accept_threshold: float = 0.10
    floor: float = 0.01         # EMRMF never discards entirely
    # gamma_rule:
    #   "fixed"             use `gamma` as given
    #   "derived"           Eq. (16), gamma* from odometry drift (falsified, H1)
    #   "adaptive"          Eq. (17), derived gamma modulated by delay CV
    #   "deferral_derived"  gamma = ln2 / t_defer_prior  (airtime-queueing scale)
    #   "deferral_adaptive" gamma_t = clip(ln2 / measured mean deferral delay)
    gamma_rule: str = "fixed"
    kappa: float = 1.0          # Eq. (17) sensitivity
    # Clip range for derived/adaptive rules. The floor is deliberately below the
    # drift-derived scale: the empirical optimum (~0.003) and the deferral-
    # derived value (ln2/155 ~ 0.0045) both sit under the 0.01 that a drift-
    # calibrated floor would impose, so a floor at 0.01 would hide the very
    # regime Section 6.4 identifies as correct.
    gamma_min: float = 0.001
    gamma_max: float = 2.00
    ewma_alpha: float = 0.2
    # Prior on mean deferral delay [s] for the deferral-derived rule. Defaults to
    # the ~155 s airtime-queueing time measured in Section 6.1; ln2/155 ~ 0.0045,
    # an order of magnitude below Eq. (16)'s gamma*=0.033 and close to the
    # empirical optimum of 0.003.
    t_defer_prior: float = 155.0


@dataclass
class InfoGainConfig:
    """Surrogate information gain. Section 3.5, Eq. (12)."""
    w_novelty: float = 0.50
    w_degree: float = 0.20
    w_loop: float = 0.30
    cell_size: float = 0.5      # coverage bitmap resolution [m]
    support_radius: float = 2.0 # cells within this radius count as covered
    # Observability term (BACS+, Section 4.4 extension). O_ij grows when the
    # robot pair (i, j) is poorly constrained; added to the surrogate only when
    # the scheduler enables it (policy "bacs_plus" or use_observability=True).
    w_obs: float = 0.30
    obs_ref: float = 6.0        # constraints per pair at which O_ij ~ 1/e


@dataclass
class SchedulerConfig:
    """Section 3.6, Eqs. (13)-(14)."""
    policy: str = "bacs"        # see schedulers.POLICIES
    window_s: float = 60.0      # W
    ageing_beta: float = 0.15   # utility multiplier (1 + beta*k)
    expire_below_trust: bool = True
    use_trust_term: bool = True
    use_info_term: bool = True
    use_cost_term: bool = True  # divide by T_air -> utility *density*
    use_ageing: bool = True
    unlimited_budget: bool = False
    trust_gate: float = 0.0     # if >0, theta_hat acts as a filter, not a rank key
    use_observability: bool = False  # add the BACS+ observability term to I_hat


@dataclass
class WorldConfig:
    """Ground-truth motion and observation generation."""
    n_robots: int = 2
    area: Tuple[float, float] = (14.0, 10.5)   # matches the EMRMF office world
    session_s: float = 720.0
    fusion_every_windows: int = 1    # server optimises and republishes this often                   # 12-minute session
    dt: float = 2.0                            # pose node interval [s]
    speed: float = 0.30                        # v_bar [m/s]
    drift_rate: float = 0.08                   # sigma_d, error per metre travelled
    drift_model: str = "linear"                # {"linear", "random_walk"}
    heading_drift: float = 0.010               # rad per metre
    obs_radius: float = 3.0                    # inter-robot observation range [m]
    obs_prob: float = 0.30                     # chance of generating a candidate in range
    meas_sigma_xy: float = 0.04
    meas_sigma_theta: float = 0.02
    outlier_rate: float = 0.12                 # wrong data association fraction
    outlier_offset: float = 1.20               # displacement injected on an outlier [m]
    payload_base_bytes: int = 28               # transform + ids + timestamp
    payload_descriptor_bytes: int = 24
    payload_jitter_bytes: int = 16   # descriptor richness varies per constraint         # descriptor attached for association


@dataclass
class AgentConfig:
    """Behaviour hook. Honest for Paper A; attacker types land here for Paper B."""
    behavior: str = "honest"    # see agents.BEHAVIORS
    params: dict = field(default_factory=dict)


@dataclass
class SimConfig:
    world: WorldConfig = field(default_factory=WorldConfig)
    lora: LoRaConfig = field(default_factory=LoRaConfig)
    channel: ChannelConfig = field(default_factory=ChannelConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    infogain: InfoGainConfig = field(default_factory=InfoGainConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    agents: dict = field(default_factory=dict)   # robot_id -> AgentConfig
    seed: int = 0

    def agent(self, rid: int) -> AgentConfig:
        return self.agents.get(rid, AgentConfig())

    def with_(self, **kw) -> "SimConfig":
        """Shallow override helper: cfg.with_(seed=3)."""
        return replace(self, **kw)
