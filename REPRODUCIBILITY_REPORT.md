# Reproducibility Report

Revision v3 (2026-09-25). This replaces the earlier report, which presented synthetic
fixtures (`HWS-101` … `HWS-130`) as physical evidence. Those files are now in
`synthetic_test_fixtures/` and are **not** physical evidence.

## Status summary

| Result | Status | Output file / script |
| :--- | :--- | :--- |
| Simulation: S8 30-seed map alignment | Frozen copy, recomputable | `paper_results/simulation/frozen/s8_30seed_raw.csv`, `analysis/simulation/s8.py` |
| Simulation: S9 decay-rule comparison | Frozen (5 seeds); 30-seed revision run | `paper_results/simulation/frozen/s9_deferral_gamma.csv`, `paper_results/revision/decay/` |
| Simulation: S7-C surrogate fidelity | Frozen | `paper_results/simulation/frozen/s7c_paired.csv` |
| Simulation: extra baselines (LIFO, random, trust-only, info-only) | New in revision v3 | `paper_results/revision/baselines/` |
| Physical: deferral, channel delay, ratio, packets sent, airtime | **Reproduced** (byte-identical) | `paper_results/physical/timing_summary.csv`, `radio_summary.csv`, `session_counts.csv`; `scripts/revision/check_physical_claims.py` |
| Physical: map-alignment RMSE | **Not available.** The bags contain no fused poses | none |
| Physical: Wilcoxon / Cliff's δ on map alignment | **Not available** (no map-alignment data) | none |
| Planned hardware rerun configuration | **Implemented as config/docs only; not executed** | `config/hardware_experiment_profiles.yaml`, `docs/HARDWARE_EXPERIMENT_V2.md` |
| Public dataset candidate replay (MRCLAM) | **Pipeline implemented; dataset copy not committed** | `analysis/public_dataset/`, `scripts/repro/replay_public_dataset.py`, `docs/PUBLIC_DATASET_REPLAY.md` |

## Physical results (HWS-002-FIFO, HWS-003-BACS, HWS-005-BACS+)

Each session has 10 runs of 720 s. Recomputed with `python scripts/revision/check_physical_claims.py`:

| Metric | FIFO | BACS | BACS+ |
|---|---|---|---|
| Median deferral of transmitted constraints | 153.5 s | 141.9 s | 166.1 s |
| Median channel delay | 0.170 s | 0.170 s | 0.171 s |
| Deferral / channel ratio | 902 | 835 | 973 |
| Constraints transmitted per session | 141 | 139 | 137 |
| Airtime / duty budget, per-run mean (median) | 10.1 % (10.4 %) | 10.0 % (10.0 %) | 9.8 % (9.3 %) |

All values reproduce from the raw scheduler logs through `analysis/physical/pipeline.py`.
The regenerated summaries are byte-identical to the committed ones.

Physical map-alignment RMSE is not available because the HWS-002/003/005 bags do not contain
fused poses. The recorded topics are `/bacs/scheduler`, `/odom/*`, `/scan/*`, `/tf` and
`/vicon/*/pose`. No physical map-alignment, Wilcoxon or Cliff's δ value may be reported.

The follow-up hardware rerun configuration now records `/fused_poses` alongside those topics,
but no rerun bag has been committed and no new physical result is claimed here.

### Checkout note

The Vicon CSVs and the `.db3`/`.mcap` bags are stored with Git LFS. Without `git lfs pull`
they are pointer files. `analysis/physical/pipeline.py` now skips LFS pointers when counting
Vicon samples and bag messages per run (`timing_per_run.csv` columns `vicon_records_*`,
`bag_records`). These counts do not enter any claim above.

## Synthetic fixtures (not evidence)

`synthetic_test_fixtures/README.md` lists what was moved and why: every fused file spans
9.9 s, the limo02 estimate equals Vicon, and the channel delay is exactly 0.170 s. The former
headline numbers (FIFO 0.48 ± 0.15 m, BACS+ 0.27 ± 0.09 m, p = 9.77×10⁻⁴, δ = −0.81) came
from these fixtures. δ = −0.81 was hard-coded; computed from the fixtures it is −0.76. The
p-value column was labelled one-sided but held the two-sided value 0.00195.

## Public dataset replay

`scripts/repro/replay_public_dataset.py` replays one public multi-robot dataset through the
same FIFO/BACS/BACS+ sender policies used by the ROS stack. The repository does not commit a
dataset copy or claim a result from one; instead it provides an offline path that accepts a
local extracted dataset directory and writes deterministic CSV/JSON outputs under
`paper_results/public_dataset/`.
