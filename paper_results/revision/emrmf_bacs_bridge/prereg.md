# Preregistration: Controlled EMRMF vs. BACS+ Bridge Experiment

**Experiment Identifier**: `emrmf_bacs_bridge`  
**Date of Preregistration**: September 27, 2026  
**Status**: FROZEN (Defined prior to experiment execution)  

---

## 1. Objective & Primary Hypothesis

### 1.1 Objective
The goal of this experiment is to perform a scientifically controlled, paired head-to-head evaluation comparing the published predecessor method **EMRMF** (*Extended Multi-Robot Map Fusion*) against the final frozen successor method **BACS+** (*Observability- and Bandwidth-Aware Constraint Scheduling*, configuration `plus_0.30_6`).

Both arms are evaluated under 100% identical simulated environments, ground-truth trajectories, odometry drift realizations, candidate constraint pools, physical LoRa channel dynamics, pose-graph optimizers, and evaluation metrics.

### 1.2 Hypotheses
- **Primary Null Hypothesis ($H_0$)**: The median paired difference in map-alignment RMSE between BACS+ and EMRMF reference is zero:
  $$\text{median}(\text{RMSE}_{\text{BACS}+} - \text{RMSE}_{\text{EMRMF\_ref}}) = 0$$
- **Primary Alternative Hypothesis ($H_1$)**: BACS+ produces a statistically significant reduction in median map-alignment RMSE compared to EMRMF reference:
  $$\text{median}(\text{RMSE}_{\text{BACS}+} - \text{RMSE}_{\text{EMRMF\_ref}}) < 0$$

---

## 2. Experimental Protocol & Parameters

### 2.1 Fixed Evaluation Parameters
- **Seed Range**: 70 to 99 (30 independent random seeds).
- **Robot Team Sizes ($N$)**: $N \in \{2, 3, 4, 5\}$.
- **Session Duration**: 480 seconds (8 minutes) per session.
- **LoRa Physical Configuration**: Spreading Factor SF7, Bandwidth 125 kHz, Coding Rate 4/5, EU868 1% regulatory duty-cycle ceiling (`channel_share="shared_equal"`).

### 2.2 Channel Conditions (C0–C3)
Reuse frozen condition definitions:
- **C0 (Ideal)**: `loss_model="independent"`, `loss_rate=0.0`, `extra_delay_s=0.0`
- **C1 (Mild Loss)**: `loss_model="independent"`, `loss_rate=0.10`, `extra_delay_s=0.0`
- **C2 (Heavy Loss)**: `loss_model="independent"`, `loss_rate=0.30`, `extra_delay_s=0.0`
- **C3 (Severe Burst & Delay)**: `loss_model="burst"`, `loss_rate=0.30`, `extra_delay_s=0.20`, `ge_p_bad=0.30`, `ge_mean_burst=4.0`

### 2.3 Paired Factorial Structure
$$\text{Total Paired Cases per Arm} = 30 \text{ seeds} \times 4 \text{ robot counts} \times 4 \text{ conditions} = 480 \text{ paired runs}$$

---

## 3. Evaluated Arms

1. **`emrmf_reference` (Primary Control Arm)**:
   - Scheduling Policy: FIFO (oldest candidate first, `-c.t_created`).
   - Decay Coefficient: Original published drift-derived rule ($\gamma^* = \ln 2 \cdot \sigma_d \cdot \bar{v} / \tau_e \approx 0.033$).
   - Trust Pre-Gating: None (`trust_gate = 0.0`).
   - Observability Term: Disabled (`w_obs = 0.0`).
   - Airtime Knapsack: Disabled (sequential arrival filling).

2. **`bacs_plus` (Primary Treatment Arm — Frozen `plus_0.30_6`)**:
   - Scheduling Policy: Gated density ranking (`bacs_plus`).
   - Trust Pre-Gating: Active (`trust_gate = 0.05`).
   - Decay Coefficient: Deferral-derived rule ($\gamma = \ln 2 / T_{\text{defer}} \approx 0.0045$).
   - Observability Term: Active ($w_{\text{obs}} = 0.30$, $n_{\text{ref}} = 6.0$).
   - Airtime Knapsack: Active utility-density greedy packing.

3. **`fifo` (Secondary Baseline)**: Compliant FIFO with deferral-derived decay.
4. **`random` (Secondary Baseline)**: Random candidate selection.
5. **`bacs_gated` (Secondary Ablation)**: BACS scheduler without observability term.

---

## 4. Endpoints & Statistical Analysis Plan

### 4.1 Primary Endpoint
- **Map-Alignment RMSE (`align_rmse`)**: Inter-robot frame alignment error measured on ground-truth co-location overlap pairs.

### 4.2 Secondary Endpoints
- **Per-step Pose RMSE (`pose_rmse`)**: Anchor-aligned trajectory position error.
- **Trust Yield (`trust_yield`)**: Mean server trust $\theta_{ij}$ over delivered constraints.
- **Acceptance Rate (`accept_rate`)**: Fraction of delivered constraints exceeding threshold $\theta > 0.10$.
- **Airtime Utilization (`airtime_util`)**: Transmitted airtime over available window budget.
- **Outlier Rejection Efficiency**: Outliers transmitted vs. outliers rejected.
- **Catastrophic Failure Rate**: Percentage of runs with $\text{align\_rmse} > 0.50\text{ m}$.

### 4.3 Statistical Testing
- **Primary Hypothesis Test**: Two-sided paired Wilcoxon signed-rank test on $\Delta = \text{RMSE}_{\text{BACS}+} - \text{RMSE}_{\text{EMRMF\_ref}}$ across all 480 paired runs ($\alpha = 0.05$).
- **Condition-Specific Tests**: Separate paired Wilcoxon tests per condition (C0, C1, C2, C3) with Holm-Bonferroni p-value adjustment.
- **Scalability Analysis**: Paired comparisons per team size ($N=2, 3, 4, 5$).
- **Effect Size Metrics**: Mean paired difference with 95% Confidence Interval, median paired difference, Cliff's delta effect size, win/tie/loss counts.

---

## 5. Scientific Integrity & Freeze Rules

1. **Protocol Freeze**: This protocol is frozen prior to execution.
2. **Zero Selective Exclusion**: No run or seed may be removed post-hoc regardless of outcome.
3. **No Retuning**: Hyperparameters of `bacs_plus` ($w_{\text{obs}}=0.30, n_{\text{ref}}=6.0, \text{gate}=0.05$) are frozen from prior work and must not be adjusted based on bridge experiment results.
4. **Controlled Input Sharing**: Both arms MUST consume identical precomputed world trajectories and candidate constraint pools via `simulator.precompute()`.
