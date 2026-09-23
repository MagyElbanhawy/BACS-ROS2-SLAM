# Reproducibility report

All recomputed values below are rendered from generated CSVs by `scripts/update_report.py`; no paper result constants are embedded in analysis code. The supplied evidence validates physical N=2 only.

| Metric | Paper value | Recomputed value | Difference | Status | Source data | Analysis script |
|---|---:|---:|---:|---|---|---|
| FIFO map-alignment RMSE | Not encoded | N/A | N/A | NOT_COMPUTABLE | No fused map or estimated trajectory supplied | `scripts/reproduce_physical.py` |
| BACS map-alignment RMSE | Not encoded | N/A | N/A | NOT_COMPUTABLE | No fused map or estimated trajectory supplied | `scripts/reproduce_physical.py` |
| BACS+ map-alignment RMSE | Not encoded | N/A | N/A | NOT_COMPUTABLE | No fused map or estimated trajectory supplied | `scripts/reproduce_physical.py` |
| BACS+ improvement versus FIFO | Not encoded | N/A | N/A | NOT_COMPUTABLE | Map RMSE unavailable | `scripts/reproduce_statistics.py` |
| Map-RMSE Wilcoxon and Cliff's delta | Not encoded | N/A | N/A | NOT_COMPUTABLE | Map RMSE unavailable | `scripts/reproduce_statistics.py` |
| BACS+ median scheduling deferral (s) | N/A | 156.438 | N/A | COMPUTED | Scheduler log | `scripts/reproduce_physical.py` |
| BACS+ median channel delay (s) | N/A | N/A | N/A | NOT_COMPUTABLE | `t_tx_ns`/`t_rx_ns` are not recorded | `scripts/reproduce_physical.py` |
| Deferral/channel ratio | N/A | N/A | N/A | NOT_COMPUTABLE | Channel delay not recorded | `scripts/reproduce_physical.py` |
| BACS+ median RSSI (dBm) | N/A | -94.9907 | N/A | COMPUTED | Scheduler log | `scripts/reproduce_physical.py` |
| BACS+ median SNR (dB) | N/A | 4.26292 | N/A | COMPUTED | Scheduler log | `scripts/reproduce_physical.py` |
| BACS+ median airtime utilisation | N/A | 0.00185896 | N/A | COMPUTED | Scheduler log and configured LoRa parameters | `scripts/reproduce_physical.py` |

Generated/transmitted constraints are in `paper_results/physical/timing_per_run.csv`; full timing and radio distributions are in their corresponding summary files. DB3/MCAP message counts match, while stream hashes and timestamps differ; every comparison is retained in `hardware/validation/db3_mcap_equivalence.csv`.
