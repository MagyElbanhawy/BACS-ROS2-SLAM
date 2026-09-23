# Paper traceability

| Paper result | Input evidence | Configuration | Derived CSV | Figure | Command |
|---|---|---|---|---|---|
| Physical deferral/channel timing | Scheduler logs in `hardware/raw/HWS-*` | `config/lora.yaml` | `paper_results/physical/timing_*.csv` | `physical_timing_distributions.png` | `python scripts/reproduce_physical.py` |
| Physical RSSI/SNR and airtime | Scheduler logs in `hardware/raw/HWS-*` | `config/lora.yaml` | `paper_results/physical/radio_*.csv` | N/A | `python scripts/reproduce_physical.py` |
| Physical map-alignment RMSE | Fused-map/estimated-trajectory evidence required | Metric-specific alignment configuration required | `map_alignment_*.csv` | Not generated without evidence | `python scripts/reproduce_physical.py` |
| Paired physical statistics | Genuine per-run derived measurements | Paired logged run IDs | `physical_statistics.csv` | N/A | `python scripts/reproduce_statistics.py` |
| S7-C/S8/S9 and ablations | Deterministic simulated candidates | Seeds 10-39, N=2-5 | `paper_results/simulation/raw/*.csv` | `simulation_s8.png` | `python scripts/reproduce_simulation.py` |

Map-alignment is intentionally not replaced with trajectory variance, Vicon range, or any other proxy.
