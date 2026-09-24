# Reproducibility Report

## Status Summary
All simulation and physical hardware results presented in the manuscript are now fully reproducible from the data and scripts provided in this repository.

| Metric | Status | Output File / Script |
| :--- | :--- | :--- |
| **Simulation: 30-seed Map Alignment (Table 4)** | ✅ COMPUTABLE | `paper_results/simulation/s8_30seed_summary.csv` |
| **Simulation: Temporal Decay Calibration (Table 2)** | ✅ COMPUTABLE | `paper_results/simulation/s9_deferral_gamma.csv` |
| **Simulation: Surrogate Fidelity (Table 3)** | ✅ COMPUTABLE | `paper_results/simulation/s7c_paired.csv` |
| **Physical: Map-Alignment RMSE (Table 6)** | ✅ COMPUTABLE | `paper_results/physical/map_alignment_summary.csv` |
| **Physical: Wilcoxon Test & Cliff's δ (Sec 7.3)** | ✅ COMPUTABLE | `paper_results/physical/map_alignment_statistics.csv` |
| **Physical: Network & Delay Metrics (Table 6)** | ✅ COMPUTABLE | `paper_results/physical/hardware_metrics.csv` |
| **Physical: Radio +OK Calibration (V2 Protocol)** | ✅ COMPUTABLE | `calibration/calibration_summary.txt` |

## Physical Validation Data (Section 7 & Table 6)
The physical validation evidence consists of 30 matched runs (10 blocks of 3 policies: FIFO, BACS, BACS+) recorded under the V2 protocol. 

The raw session logs, including clock synchronization files, candidate logs, and serial radio logs, are stored in:
`hardware/raw/HWS-101-FIFO/` through `hardware/raw/HWS-130-BACS+/`

### Extracted Physical Results
The final metrics matching the manuscript are found in `paper_results/physical/`:
- `map_alignment_per_run.csv`: The raw RMSE for each of the 30 individual runs.
- `map_alignment_summary.csv`: Aggregated mean and standard deviation (FIFO: 0.48±0.15m, BACS+: 0.27±0.09m).
- `map_alignment_statistics.csv`: Paired Wilcoxon p-value (9.77×10⁻⁴) and Cliff's δ (-0.81).
- `hardware_metrics.csv`: Median deferral (154s), channel delay (0.17s), and airtime utilization (97-98%).
