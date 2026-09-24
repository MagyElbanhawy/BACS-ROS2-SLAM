# Paper traceability

| Paper result | Input evidence | Configuration | Derived CSV | Figure | Command |
|---|---|---|---|---|---|
| Physical deferral/channel timing | Scheduler logs in `hardware/raw/HWS-*` | `config/lora.yaml` | `paper_results/physical/timing_*.csv` | `physical_timing_distributions.png` | `python scripts/reproduce_physical.py` |
| Physical RSSI/SNR and airtime | Scheduler logs in `hardware/raw/HWS-*` | `config/lora.yaml` | `paper_results/physical/radio_*.csv` | N/A | `python scripts/reproduce_physical.py` |
| Physical map-alignment RMSE | `paper_results/physical/fused/fused_<session>.csv` from bag replay + Vicon | Co-location radius 0.5 m, one rotation per session (`docs/METRIC_DEFINITIONS.md`) | `map_alignment_*.csv` | Not generated yet | `python scripts/repro/compute_map_alignment.py` |
| Paired physical statistics | Genuine per-run derived measurements | Paired logged run IDs | `physical_statistics.csv` | N/A | `python scripts/reproduce_statistics.py` |
| S8 (Figs 5-9), S7-C, S9 | `bacs_sim` simulator | Seeds 10-39, N=2-5 | `paper_results/s8_30seed_raw.csv` (frozen copy in `paper_results/simulation/frozen/`), `paper_results/simulation/s8_*.csv` | `sim_s8_*.png` | `python scripts/reproduce_simulation.py` |

Map-alignment is intentionally not replaced with trajectory variance, Vicon range, or any other proxy. Draft-paper values and their match status: `REPRODUCIBILITY_REPORT.md`; open questions: `REPRODUCIBILITY_ISSUES.md`.
