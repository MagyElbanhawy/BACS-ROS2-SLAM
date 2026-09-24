# bacs_sim — Bandwidth-Aware Constraint Scheduling simulator

Simulation backbone for Paper A (scheduling) and Paper B (adversarial reputation).
Module layout follows the manuscript so code and equations stay in sync.

| File | Paper section |
|---|---|
| `config.py` | all parameters, named after their symbols |
| `lora.py` | §3.1 airtime budget Eq.(1) (regulatory vs shared split); §3.2 time-on-air Eqs.(2)–(4); channel emulator |
| `trust.py` | §3.3 Eqs.(5)–(6); §3.4 Eqs.(7)–(9); §3.7 Eqs.(15)–(17); deferral-derived γ |
| `infogain.py` | §3.5 Eq.(12) surrogate, Eq.(11) exact MI, rank correlation |
| `observability.py` | BACS+ observability term O_ij (Section 4.4 extension) |
| `schedulers.py` | §3.6 Eqs.(13)–(14), all policies incl. `bacs_plus` |
| `posegraph.py` | SE(2) weighted Gauss-Newton back-end (stands in for g2o) |
| `world.py` | ground truth, odometry drift, candidate generation |
| `simulator.py` | windowed loop with fused-map feedback |
| `agents.py` | honest (Paper A) + attacker hooks (Paper B) |
| `experiments.py` | S1–S9 runners, progression, Wilcoxon, effect size |
| `model.py` | **standalone** comms-layer reference; not on the RMSE path (see its docstring) |

> **Which simulator makes which number?** Every manuscript metric (pose_rmse,
> S1–S9) comes from the canonical full pipeline (`world`→`lora`→`trust`→
> `infogain`/`observability`→`schedulers`→`posegraph`→`simulator`).
> `model.py` is a self-contained communication-layer reference that produces no
> RMSE and is not imported by the pipeline — kept in sync by construction, not
> by shared code.

## Quick start

```python
from bacs_sim import SimConfig, run, precompute

cfg = SimConfig()
cfg.trust.gamma = 0.003          # calibrated; see findings below
cfg.scheduler.policy = "bacs_gated"
pre = precompute(cfg)            # share world data across policies
result = run(cfg, precomputed=pre)
print(result.pose_rmse, result.trust_yield)
```

```python
from bacs_sim.experiments import s1_policy_comparison, s5_ablation, s6_scalability
s5_ablation(seeds=range(6)).to_csv("ablation.csv")
```

Runtime is roughly 4–6 s per run (2 robots, 12-min session); budget accordingly.

## BACS+ and the maturity additions

The scheduler discovered its own limitation — the advantage reverses beyond
three robots — and these additions address it:

- **`bacs_plus` (Observability-Aware BACS).** `observability.py` adds a term
  `O_ij = exp(-n_ij / n_ref)` to the information surrogate, where `n_ij` is the
  number of inter-robot constraints already delivered for pair `(i, j)`. It
  biases airtime toward pairs whose relative transform is not yet determined —
  the coverage/observability tension the base surrogate ignores. Enabled by the
  `bacs_plus` policy or `scheduler.use_observability = True`; weight `w_obs`.
- **Deferral-derived γ.** `trust.gamma_rule = "deferral_derived"` sets
  `γ = ln2 / T_defer` (default `t_defer_prior = 155 s`, the measured
  airtime-queueing scale), giving γ ≈ 0.0045 and recovering near-optimal RMSE
  without hand-tuning — turning the falsified Eq. (16) into a usable rule.
  `"deferral_adaptive"` tracks the online mean delay instead.
- **Regulatory vs shared airtime.** `lora.regulatory_budget` (per-device
  `δW`) is now separate from `lora.airtime_budget` (per-robot
  `α_i · δW`); `lora.channel_share ∈ {"shared_equal", "per_device"}`.

New experiment runners (all in `experiments.py`):

```python
from bacs_sim.experiments import (
    s7c_incremental_validation, # rho(I_hat/I_hat+, incremental MI) -- the correct S7
    s7_surrogate_validation,    # prior- vs posterior-baseline diagnostic
    s8_observability,           # FIFO vs BACS vs BACS+ RMSE across N
    s9_deferral_gamma,          # decay-coefficient rule comparison
    progression,                # EMRMF-original -> compliant FIFO -> BACS -> BACS+
    summary_stats, cliffs_delta,
)
```

## Extending for Paper B

`agents.py` defines two hooks. `on_report` falsifies what a robot claims to have
seen; `on_declare` inflates the scheduling scores it reports about itself. The
second is the vector the scheduler newly creates — a robot overstating its
predicted trust or novelty captures a disproportionate share of a shared duty
cycle. Add reputation state to the server loop in `simulator.py` where
`server_trust` is called, then score detection against the `tampered` flag
already carried on every `Constraint`.

```python
cfg.agents = {1: AgentConfig(behavior="drift_injection", params={"bias": 0.15})}
```

## Findings that revise the manuscript

1. **Staleness is queueing, not propagation.** Under 1% duty cycle, airtime
   deferral contributes ~155 s to packet age; the 0.05–0.2 s channel delays
   studied in the parent framework are three orders of magnitude smaller and
   have no measurable effect. The temporal term of θ matters far more than the
   parent paper claimed, but for a different reason.
2. **Eq. (16) is falsified (H1) — and now corrected.** It predicts γ* = 0.033;
   the empirical optimum is 0.003. The derivation matches γ to the odometry-drift
   timescale when it should be matched to the airtime-queueing timescale. The
   `deferral_derived` rule (γ = ln2 / T_defer ≈ 0.0045) makes that correction and
   recovers near-optimal RMSE without tuning (see S9).
3. **Eq. (13) is structurally unsound.** θ̂ spans two decades while Î spans
   [0,1], so the product is always θ̂-dominated: the multiplicative form returns
   bit-identical results to trust-only ranking. Use θ̂ as an admissibility gate
   and rank by Î / T_air (`bacs_gated`).
4. **Ranking on θ̂ is self-confirming.** It favours constraints agreeing with the
   robot's current estimate, which carry least corrective information. Requires
   the fused map (not raw odometry) for the provisional residual of Eq. (8);
   with odometry the residual is dominated by the transmitter's own drift.
5. **The surrogate is valid, and the observability term sharpens it.** Validated
   correctly (S7-C: incremental information gain against the graph state at
   scheduling time, Jacobian-based, over all candidates), the base surrogate
   correlates positively with true information at every team size (ρ ≈ 0.45–0.62),
   and the observability-augmented surrogate Î⁺ is higher at every N (Δρ ≈ +0.08
   to +0.19). This is the principled justification for `bacs_plus`. **Caution:**
   validating against the *converged posterior* instead of the prior inverts the
   sign (ρ ≈ −0.5) — a classic evaluation trap; see `s7_surrogate_validation`'s
   posterior column, kept only as a diagnostic. The RMSE benefit of BACS+ at
   large N remains noisy (S8) and is not the basis of the claim.
