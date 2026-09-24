# Simulation

## Status: the committed runner can't regenerate the manuscript's tables and figures

`simulation/run.py` (via `scripts/reproduce_simulation.py`) runs only a candidate-selection step. It writes one outcome column, `mean_information`, which is the mean information score of the selected candidates.

### Why N = 2–5 give identical values

In `experiment()`, the random draws (`rng.random()`, `rng.randrange`) don't depend on `robots`. The team size only changes the `robot_j` label (`f"r{i % robots}"`), and `Scheduler.select` never reads that label. So for a given seed, every team size gets the same candidates and the same selection. The identical rows in `simulation_summary.csv` are the correct output of this code, not a CSV-writing bug.

### What Tables 4–7 and Figs 2–9 need

Manuscript Sec. 5.1 describes a much fuller pipeline:

- ground-truth world generation and boustrophedon trajectories (14.0 × 10.5 m, 0.30 m/s, a pose every 2 s)
- odometry drift
- candidate generation from co-location, with outliers
- LoRa airtime and packet loss
- trust prediction
- information and observability scoring
- a weighted SE(2) Gauss–Newton back-end

It also relies on modules the manuscript cites that aren't in this repo (`experiments.s7c_incremental_validation`, `paper_results/s7c_incremental_validation.csv`, `s7c_paired.csv`). The tables and figures need per-(N, seed, policy) values of:

- map-alignment RMSE, pose RMSE and delivered-constraint count (S8, Figs 5–8)
- per-seed Spearman ρ of the base and observability surrogates against exact incremental information (S7-C)
- temporal-decay and observability-weight ablations (S9, Fig. 9)

Adding columns to `run.py` won't produce these values. Only the simulator that produced the manuscript numbers can. That simulator has to be committed here with a single entry point that writes one row per (N, seed, policy) to `paper_results/simulation/raw/`. Otherwise the simulation results must be regenerated with a new simulator, and the manuscript updated to whatever that produces.

### Commands (current runner)

```bash
python scripts/reproduce_simulation.py   # writes paper_results/simulation/{raw,summary}/
```
