# Metric definitions

Each metric the manuscript reports has one definition here and one script that produces it. The manuscript text, table captions and CSV column names must use these names.

## Map-alignment RMSE (primary physical endpoint)

Produced by `analysis/physical/map_alignment.py` (CLI: `scripts/repro/compute_map_alignment.py`) from `paper_results/physical/fused/fused_<session>.csv`.

1. Samples are taken at 10 Hz. A sample is used only when both robots have a fused pose (`map -> <robot>/base_link`) and a Vicon pose within 50 ms of it.
2. The inter-robot vectors `d_est = p1_est - p2_est` and `d_vic = p1_vic - p2_vic` are formed. They don't depend on where the map origin sits.
3. One rotation `R` (map to Vicon) is fitted per session over all samples with 2-D Kabsch (no translation, no scale).
4. **Map-alignment RMSE** for a run is `sqrt(mean ||R d_est - d_vic||^2)` over the run's **co-location samples**, meaning samples where `||d_vic|| <= 0.5 m`. A run with fewer than 20 co-location samples is `INSUFFICIENT_COLOCATION` and is excluded.
5. `relative_rmse_all_samples_m` gives the same residual over all samples of the run as a secondary diagnostic.

Run boundaries come from `paper_results/physical/run_segmentation.csv`.

Statistics (`map_alignment_statistics.csv`, one row per policy pair):

- Cliff's delta is computed as candidate vs reference. A negative value means the candidate has lower RMSE.
- The paired Wilcoxon test matches runs by run index. The three sessions were recorded on different days (14, 15 and 16 Jul), so run *k* of one policy is not the same trial as run *k* of another. The manuscript must state this if it reports the paired test.
- The unpaired Mann–Whitney U test doesn't depend on that pairing and should be reported alongside the paired test.
- Both two-sided and one-sided (`less`) p-values are written. Report the one that was pre-specified.

## Timing (per transmitted packet)

Source: scheduler log, via `analysis/physical/pipeline.py`. Output: `timing_summary.csv`.

| Metric | Definition | Packets |
|---|---|---|
| `deferral_s` | `t_selected - t_gen` | all generated candidates |
| `deferral_sent_s` | `t_selected - t_gen` | transmitted only (use this in the packet-age decomposition) |
| `channel_delay_s` | `t_rx - t_tx` | transmitted only |
| `packet_age_s` | `t_rx - t_gen` | transmitted only |

Medians of these three don't add up exactly, because the median of a sum isn't the sum of the medians. The paper should quote them as separate medians.

Channel delay is a property of the radio link. It isn't expected to depend on the scheduling policy, and the text should say so.

## Packet counts

Output: `session_counts.csv` and `radio_per_run.csv`.

- `packets_generated_per_run` and `packets_sent_per_run`: counts within one 720 s run.
- `packets_generated_per_session` and `packets_sent_per_session`: sums over the 10 runs of a session.

Always state which one is meant, for example: "≈2,090 candidates generated per session (≈209 per run), of which ≈14 per run were transmitted."

## Airtime

Output: `radio_per_run.csv` and `radio_summary.csv`. Per-packet time-on-air uses the Semtech formula (SF7, 125 kHz, CR 4/5, 52 bytes, 102.7 ms).

- `airtime_fraction_of_run = sum(airtime of sent packets) / run duration`
- `airtime_fraction_of_duty_budget = sum(airtime of sent packets) / (duty_cycle × run duration × transmitting robots)`

`duty_cycle` comes from `config/lora.yaml` (0.01). The second metric is the one that answers "was the legal budget used?", and it is the one the manuscript should call *airtime utilisation*.

## Fused pose log (`paper_results/physical/fused/fused_<session>.csv`)

| Column | Meaning |
|---|---|
| `session`, `robot` | Session ID and robot name (`limo01`, `limo02`) |
| `stamp_ns` | Sim-time tick at which the sample was taken, the same for both robots |
| `est_x`, `est_y`, `est_yaw` | `map -> <robot>/base_link` (m, rad) |
| `tf_stamp_ns`, `vicon_stamp_ns` | Timestamps of the transform and of the Vicon message used |
| `vicon_x`, `vicon_y`, `vicon_yaw` | Vicon pose (m, rad) |
