# Observability- and Bandwidth-Aware Constraint Scheduling for Trust-Weighted Multi-Robot Map Fusion under Duty-Cycle-Limited Wireless Links

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![ROS 2 Humble](https://img.shields.io/badge/ROS2-Humble-orange.svg)](https://docs.ros.org/en/humble/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Official reproducibility repository for **Observability- and Bandwidth-Aware Constraint Scheduling (BACS / BACS+)** in trust-weighted multi-robot SLAM map fusion. This repository contains the complete ROS 2 workspace, physical robot experimental datasets, deterministic simulation suite, statistical analysis scripts, generated figures, and reviewer-facing traceability matrices.

---

## 📌 Key Research Contributions

1. **Bandwidth-Aware Knapsack Scheduling (BACS)**: Formulates inter-robot constraint selection under regulatory wireless airtime ceilings (1% EU868 LoRa sub-band) as a constrained utility-density knapsack optimization problem.
2. **Observability Deficit Integration (BACS+)**: Incorporates a pair observability deficit term $O_{ij} = \exp(-n_{ij} / n_{\text{ref}})$ into the surrogate information gain, preventing airtime starvation between robot pairs whose relative spatial transform remains under-constrained.
3. **Trust-Weighted Admissibility**: Implements trust pre-gating ($\hat{\theta}_{ij} \ge 0.05$) combined with temporal freshness decay ($\gamma$) to filter low-trust inter-robot constraints before pose-graph optimization.
4. **Controlled EMRMF-to-BACS+ Bridge Evaluation**: Evaluates published predecessor EMRMF (*Enhanced Multi-Robot Map Fusion*, Saber et al. 2026) against final frozen BACS+ (`plus_0.30_6`) under 100% identical worlds, channels, and metrics, demonstrating a **27.1%** reduction in map-alignment RMSE ($p < 0.001$).

---

## 🏗️ Repository Structure

```
.
├── bacs_sim/                   # Core deterministic multi-robot simulator package
│   ├── config.py               # Simulation configuration parameters & channel models
│   ├── simulator.py            # Precompute engine, SE(2) pose-graph solver & alignment metrics
│   ├── schedulers.py           # FIFO, EMRMF reference, BACS, BACS+ policy implementations
│   ├── trust.py                # Temporal decay & trust admissibility estimators
│   └── experiments.py          # Preregistered multi-arm experiment runners
├── ros2_ws/src/bacs_scheduler/ # ROS 2 Humble C++/Python package for hardware deployment
│   ├── bacs_scheduler/         # Sender, receiver, fusion, and candidate node nodes
│   └── package.xml             # Package metadata and dependencies
├── hardware/                   # Physical robot validation data
│   ├── raw/                    # Immutable raw scheduler CSV logs & Vicon ground-truth
│   └── validation/             # Schema validation and timestamp verification scripts
├── paper_results/              # Reproducible experiment outputs and CSV tables
│   ├── physical/               # Physical deployment timing, radio, and alignment statistics
│   ├── simulation/             # Frozen S8 multi-seed simulation data
│   └── revision/               # EMRMF-to-BACS+ Bridge V2 experiment artifacts
├── scripts/                    # Reproduction pipelines and figure generators
│   ├── reproduce_all.py        # End-to-end master reproduction script
│   ├── reproduce_physical.py   # Physical experiment log parser & metrics processor
│   ├── reproduce_simulation.py # Simulation benchmark aggregator
│   ├── generate_figures.py     # Publication figure rendering pipeline
│   └── revision/               # Preregistered bridge experiment execution & analysis
├── docs/                       # Platform specs, metrics definitions, and runbooks
├── tests/                      # Pytest unit & integration test suite
├── README.md                   # Repository guide
├── PAPER_TRACEABILITY.md       # Manuscript claim-to-evidence traceability matrix
└── REPRODUCIBILITY_REPORT.md   # Benchmark match/mismatch verification report
```

---

## 🧪 Experimental Validation

### 1. Physical Robot Deployment ($N=2$)
- **Hardware Platform**: Two AgileX LIMO differential-drive robots (LIMO-01 and LIMO-02) equipped with EAI T-mini Pro 2D LiDAR, Orbbec DaBai RGB-D camera, and Intel NUC i7 compute units.
- **Wireless Links**: REYAX RYLR998 LoRa modules operating at 868 MHz (SF7, BW 125 kHz, CR 4/5) under a strict 1% regulatory duty-cycle ceiling over rolling 60 s windows.
- **Ground Truth**: Vicon optical motion capture system providing sub-millimeter trajectory references.

### 2. Multi-Robot Simulation Benchmark ($N=2\text{--}5$)
- **World & Path Generation**: Deterministic boustrophedon sweep patterns with dead-reckoning drift realizations ($\sigma_d = 0.08\text{ m/m}$).
- **Wireless Channel Models**: Evaluated under ideal transmission (L0), 10% i.i.d. packet loss (L1), 30% i.i.d. packet loss (L2), and 30% Gilbert-Elliot burst loss with 0.2 s delay (L3).
- **Preregistered Evaluation**: Paired Wilcoxon signed-rank tests over fresh seeds 100–129 ($n=480$ paired runs per policy).

---

## 🚀 Reproduction & Setup

### Environment Setup
Python 3.10+ and standard numerical libraries are required:

```bash
git clone https://github.com/MagyElbanhawy/BACS-ROS2-SLAM.git
cd BACS-ROS2-SLAM
python -m pip install -r requirements.txt
```

### Running Tests
Execute the pytest suite to verify simulator determinism, scheduler rules, and metrics calculation:

```bash
python -m pytest tests/test_scheduler.py tests/test_simulation_s8.py tests/test_analysis.py tests/test_emrmf_bacs_bridge.py
```

### Full Reproduction Pipeline
To reproduce all physical analyses, simulation benchmarks, and publication figures from raw evidence:

```bash
python scripts/reproduce_all.py
```

### EMRMF vs. BACS+ Bridge V2 Experiment
To run the preregistered EMRMF-to-BACS+ bridge experiment:

```bash
python scripts/revision/run_emrmf_bridge_v2.py --jobs 8
```

Outputs will be saved directly to `paper_results/revision/emrmf_bridge_v2/`, including `prereg.md`, `raw.csv`, `summary.csv`, `primary.csv`, `secondary.csv`, `decomposition.csv`, `fig_bridge.png`, and `REPORT.md`.

---

## 📋 Documentation & Traceability

- **[PAPER_TRACEABILITY.md](PAPER_TRACEABILITY.md)**: Maps every numerical claim, table, and figure in the manuscript to its underlying raw data file and processing script.
- **[REPRODUCIBILITY_REPORT.md](REPRODUCIBILITY_REPORT.md)**: Live verification matrix comparing draft manuscript values against recomputed raw data statistics.
- **[docs/METRIC_DEFINITIONS.md](docs/METRIC_DEFINITIONS.md)**: Mathematical definitions of map-alignment RMSE, pose RMSE, trust yield, and airtime utilization.
- **[docs/EMRMF_TO_BACS_CROSSWALK.md](docs/EMRMF_TO_BACS_CROSSWALK.md)**: Detailed methodological crosswalk comparing EMRMF and BACS/BACS+ formulations.

---

## 📄 License

This repository is licensed under the [MIT License](LICENSE).
