# Paper traceability

## Physical claims (the complete list)

The physical evidence is the three logged sessions `hardware/raw/HWS-002-FIFO`,
`HWS-003-BACS` and `HWS-005-BACS+` (10 runs of 720 s each, two LIMO robots, RYLR998
at SF7/125 kHz/CR 4/5, 52-byte payloads). The paper may make **only** these physical claims:

| Claim | FIFO (HWS-002) | BACS (HWS-003) | BACS+ (HWS-005) | Derived CSV (column) |
|---|---|---|---|---|
| Median scheduling deferral of transmitted constraints | 153.5 s | 141.9 s | 166.1 s | `paper_results/physical/timing_summary.csv` (`deferral_sent_s`, `median`) |
| Median channel delay (t_rx − t_tx) | 0.170 s | 0.170 s | 0.171 s | `timing_summary.csv` (`channel_delay_s`, `median`) |
| Deferral / channel-delay ratio | 902 | 835 | 973 | ratio of the two medians above |
| Constraints transmitted per session | 141 | 139 | 137 | `paper_results/physical/session_counts.csv` (`packets_sent_per_session`) |
| Airtime as fraction of the 1 % duty-cycle budget | ≈10 % (mean 10.1 %) | ≈10 % (mean 10.0 %) | ≈10 % (mean 9.8 %) | `paper_results/physical/radio_summary.csv` (`airtime_fraction_of_duty_budget`) |

Input: the scheduler logs `hardware/raw/HWS-00*/bacs_scheduler_log_*.csv`, with
`config/lora.yaml` (duty cycle 0.01). Code: `analysis/physical/pipeline.py`
(`physical_analysis`).

Commands:

```bash
python scripts/revision/check_physical_claims.py   # re-runs the pipeline, checks every claim above
```

Output: `paper_results/revision/physical/physical_claims_check.csv` (all 18 checks match)
and `reproduction_status.txt`. The regenerated `timing_summary.csv`, `radio_summary.csv`,
`session_counts.csv`, `timing_per_packet.csv` and `radio_per_run.csv` are byte-identical to
the committed ones in `paper_results/physical/`.

**Physical map-alignment RMSE is not available.** The HWS-002/003/005 bags contain only
`/bacs/scheduler`, `/odom/*`, `/scan/*`, `/tf` and `/vicon/*/pose`
(`hardware/validation/db3_topics.csv`). They contain no fused (server-side) pose estimates,
so map alignment against Vicon can't be computed. No proxy (trajectory variance,
Vicon range, etc.) is substituted. `scripts/repro/compute_map_alignment.py` is the CLI for
`analysis/physical/map_alignment.py` and will produce the metric once fused-pose CSVs are
recorded under the V2 protocol (`docs/HARDWARE_EXPERIMENT_V2.md`).

**Planned rerun configuration is not evidence.** The repository now carries the requested
follow-up rerun settings in `config/hardware_experiment_profiles.yaml` and the V2 protocol,
including `/fused_poses` bag logging, a 0.05 trust gate, information-density ranking, a
surplus-candidate profile, and interleaved 12-minute policy blocks. Those settings are
implementation/configuration artifacts only until new bags and logs are recorded.

**Synthetic fixtures are not evidence.** The former `hardware/raw/HWS-101-*` … `HWS-130-*`
sessions, and the `map_alignment_*.csv` and `hardware_metrics.csv` files derived from them,
are synthetic. They are now in `synthetic_test_fixtures/`
(see `synthetic_test_fixtures/README.md`) and must not be cited.

## Simulation results

| Paper result | Input evidence | Configuration | Derived CSV | Figure | Command |
|---|---|---|---|---|---|
| S8 (Figs 5-9), S7-C, S9 | `bacs_sim` simulator | Seeds 10-39, N=2-5 | `paper_results/simulation/frozen/s8_30seed_raw.csv`, `paper_results/simulation/s8_*.csv` | `sim_s8_*.png` | `python -c "from pathlib import Path; from analysis.simulation.s8 import run; run(Path('.'))"` |
| Revision v3: extra baselines (S8 protocol) | `bacs_sim` | Seeds 10-39, N=2-5, 480 s, deferral-derived γ | `paper_results/revision/baselines/*.csv` | `fig_baselines.png` | `python scripts/revision/run_baselines.py` |
| Revision v3: decay rules (S9, 30 seeds) | `bacs_sim` | Seeds 10-39, N=2-5, 720 s | `paper_results/revision/decay/*.csv` | `fig_decay.png` | `python scripts/revision/run_decay.py` |

Details, numbers and discrepancies: `paper_results/revision/REPORT.md`.

## Public multi-robot dataset replay

The repository also contains a reproducible offline replay path for the public UTIAS MRCLAM
dataset (`docs/PUBLIC_DATASET_REPLAY.md`, `analysis/public_dataset/`,
`scripts/repro/replay_public_dataset.py`). It is separate from the physical evidence above:
dataset replay outputs are generated locally from a user-supplied public dataset copy and are
not claimed as hardware measurements.
