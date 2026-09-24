# Simulation

The simulation results come from `bacs_sim` (world generation, odometry drift, candidate generation, LoRa airtime and loss, trust prediction, information and observability scoring, scheduling, and a weighted SE(2) Gauss–Newton back-end). It is imported from `MagyElbanhawy/ros2_BACS_untested` (commit `2473f1b`). The frozen CSVs that back the manuscript are kept unchanged in `paper_results/simulation/frozen/`.

**Reproduction check (2026-09-24):** re-running `scripts/run_s8_30seed.py --lo 10 --hi 13 --counts 2` reproduced the frozen `align_rmse` for all 12 (seed, arm) rows, with a maximum absolute difference of 1.4 × 10⁻¹⁴. Run the full 30-seed set to confirm the rest.

## Commands

```bash
python scripts/reproduce_simulation.py                  # all generators incl. S8 (30 seeds x N=2-5), then statistics
python scripts/reproduce_simulation.py --skip-s8        # S7-C, S9, progression only
python scripts/reproduce_simulation.py --analysis-only  # statistics from existing CSVs (fresh if present, else frozen)
python scripts/generate_figures.py                      # sim_s8_*.png in figures/generated/
python scripts/update_report.py                         # compares every claim with the manuscript
```

The simulator writes `paper_results/*.csv`. `analysis/simulation/s8.py` rebuilds `paper_results/simulation/s8_summary.csv` and `s8_paired_tests.csv` from the per-seed raw table, and `s8_source.txt` records whether the fresh or the frozen table was used.

| Output | Manuscript |
|---|---|
| `sim_s8_alignment.png` | Fig. 5, map-alignment RMSE by N |
| `sim_s8_pose.png` | Fig. 6, pose RMSE |
| `sim_s8_delivered.png` | Fig. 7, delivered constraints |
| `sim_s8_paired_reduction.png` | Fig. 8, per-seed reductions and win counts |
| `sim_s8_observability_ablation.png` | Fig. 9, 0.60/5 vs 0.30/6 |

S7-C and S9 figures are not generated yet. They need the column layout of `s7c_paired.csv` and `s9_deferral_gamma.csv`.
