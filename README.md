# Observability- and Bandwidth-Aware Constraint Scheduling for Trust-Weighted Multi-Robot Map Fusion under Duty-Cycle-Limited Wireless Links

This repository provides the implementation, immutable physical evidence, validation pipeline, analyses, deterministic simulation experiments, generated figures, and reviewer-facing traceability for the associated paper.

## Architecture

The ROS 2 package separates constraint representation, FIFO/BACS/BACS+ ranking, trust admissibility, pairwise observability, duty-cycle accounting, and LoRa airtime. The evidence pipeline keeps raw files read-only, validates containers and tabular streams, derives per-run measurements, then produces statistics and figures from those derived CSVs.

## Physical validation - N=2

The physical platform uses two modified AgileX LIMO differential-drive robots (LIMO-01 and LIMO-02), Ubuntu 22.04, ROS 2 Humble, EAI T-mini Pro 2D LiDAR, Orbbec DaBai RGB-D camera, Intel NUC i7 computers, Vicon ground truth, and RYLR998 LoRa at 868 MHz/SF7/125 kHz/CR 4/5. The regulatory configuration is a 1% duty-cycle ceiling in a 60 s window. Physical evidence covers FIFO, BACS, and BACS+ sessions, each carrying ten logged runs. It does not establish physical scalability beyond two robots.

## Simulation validation - N=2-5

The simulation is deterministic and explicitly separate from physical evidence. It runs seeds 10-39 for N=2-5 plus S7-C-style incremental, S9 temporal-decay, and policy-ablation outputs. Simulation output must not be interpreted as a physical measurement.

## Layout

| Path | Contents |
|---|---|
| `hardware/raw/` | Immutable, session-organized physical evidence |
| `hardware/validation/` | Container, schema, timestamp, and cross-representation validation |
| `ros2_ws/src/bacs_scheduler/` | ROS 2 Humble scheduler package |
| `analysis/` | Physical and statistical analysis |
| `simulation/` | Deterministic simulated experiments |
| `paper_results/` | Generated CSV outputs |
| `figures/extract/` | Extracted figures |
| `docs/` | Platform, protocol, data dictionary, and reproduction guidance |

## Reproduction

```sh
python -m pip install -r requirements.txt
python scripts/validate_hardware.py
python scripts/reproduce_physical.py
python scripts/reproduce_statistics.py
python scripts/reproduce_simulation.py
python scripts/generate_figures.py
python scripts/update_report.py
python -m pytest -q
```

Or run `python scripts/reproduce_all.py`. See [REPRODUCIBILITY_REPORT.md](REPRODUCIBILITY_REPORT.md) for result status and [PAPER_TRACEABILITY.md](PAPER_TRACEABILITY.md) for the claim-to-evidence chain.

