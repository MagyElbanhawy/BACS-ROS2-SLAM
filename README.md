# Observability- and Bandwidth-Aware Constraint Scheduling for Trust-Weighted Multi-Robot Map Fusion under Duty-Cycle-Limited Wireless Links

This repository provides the implementation, immutable physical evidence, validation pipeline, analyses, deterministic simulation experiments, generated figures, and reviewer-facing traceability for the associated paper.

## Architecture

The ROS 2 package separates constraint representation, FIFO/BACS/BACS+ ranking, trust admissibility, pairwise observability, duty-cycle accounting, and LoRa airtime. The evidence pipeline keeps raw files read-only, validates containers and tabular streams, derives per-run measurements, then produces statistics and figures from those derived CSVs.

## Physical validation - N=2

The physical platform uses two modified AgileX LIMO differential-drive robots (LIMO-01 and LIMO-02), Ubuntu 22.04, ROS 2 Humble, EAI T-mini Pro 2D LiDAR, Orbbec DaBai RGB-D camera, Intel NUC i7 computers, Vicon ground truth, and RYLR998 LoRa at 868 MHz/SF7/125 kHz/CR 4/5. The regulatory configuration is a 1% duty-cycle ceiling in a 60 s window. Physical evidence covers FIFO, BACS, and BACS+ sessions, each carrying ten logged runs. It does not establish physical scalability beyond two robots.

The repository also includes a **planned** rerun configuration for follow-up hardware experiments: `/fused_poses` bag logging, a 0.05 trust gate with information-density ranking, a surplus-candidate profile that can bind the 0.6 s/min airtime budget, and a 12-minute interleaved FIFO/BACS/BACS+ protocol. These settings are documented in `config/hardware_experiment_profiles.yaml` and `docs/HARDWARE_EXPERIMENT_V2.md`; they are configuration and protocol updates, not completed measurements.

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
| `synthetic_test_fixtures/` | **Synthetic** V2-layout sessions and files derived from them. Test inputs only, not evidence |

## Reproduction

```sh
python -m pip install -r requirements.txt
python scripts/revision/check_physical_claims.py   # physical timing/radio claims (HWS-002/003/005)
python scripts/revision/run_baselines.py           # S8 protocol with the extra baselines
python scripts/revision/run_decay.py               # S9 decay rules, 30 seeds
python -m pytest -q
```

For the offline public-dataset replay path, see `docs/PUBLIC_DATASET_REPLAY.md` and run:

```sh
python scripts/repro/replay_public_dataset.py /path/to/MRCLAM_Dataset1 --out paper_results/public_dataset
```

## Physical results

The physical evidence is HWS-002-FIFO, HWS-003-BACS and HWS-005-BACS+. The paper's physical
claims are the median deferral of transmitted constraints (153.5 / 141.9 / 166.1 s), the
median channel delay (0.170 / 0.170 / 0.171 s), their ratio (902 / 835 / 973), constraints
transmitted per session (141 / 139 / 137) and airtime of about 10 % of the duty-cycle budget.
Physical map-alignment RMSE is not available because the bags do not contain fused poses.
See `PAPER_TRACEABILITY.md`, `REPRODUCIBILITY_REPORT.md` and `paper_results/revision/REPORT.md`.

Future reruns should instead use the implemented V2 configuration, which records `/fused_poses` in the bag and keeps the separate CSV logger for compatibility with the existing replay workflow.

The former `HWS-101` … `HWS-130` sessions are synthetic and are now in
`synthetic_test_fixtures/` (see its README).
