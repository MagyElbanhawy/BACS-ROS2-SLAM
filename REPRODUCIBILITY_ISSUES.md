# Open reproducibility issues

These are the discrepancies and data-quality questions the reviewer raised, or found while checking them, that code changes alone can't close. Each needs an answer or a manuscript change before submission.

## 1. Physical map-alignment RMSE: no evidence yet

The repo has no fused-map trajectory, so 0.48 → 0.27 m (43.8%, p = 9.77×10⁻⁴, δ = −0.81) can't be reproduced. The pipeline to produce it is now in place (`docs/REPRODUCTION_GUIDE.md`, steps 2–4). Whatever it outputs is the result to report.

The `hardware/results/*` pose graphs (FIFO, BACS) were produced on 2026-09-23 by replaying the bags. They are an offline reconstruction, not the map from the live experiment, and the manuscript must say so.

## 2. Draft numbers that don't match the data

See `REPRODUCIBILITY_REPORT.md`. Summary:

- Median packet age and deferral: draft says FIFO 162 / 161 s and BACS+ 155 / 154 s. The logs give FIFO 153.7 / 153.5 s and BACS+ 166.2 / 166.1 s.
- Channel delay is ≈0.170 s for all three policies. The draft's FIFO value is 0.18 s.
- Airtime utilisation: the draft says 97–98%. The logs give ≈9–10% of the per-robot 1% duty budget, or ≈0.2% of run time. No definition gives 97–98%.
- "~2,100 / 14" mixes units: ≈2,090 candidates per session versus ≈14 sent per run (≈140 per session).
- Deferral/channel ratio for BACS+ is ≈973, not 906.

## 3. Hardware run pairing

FIFO, BACS and BACS+ were recorded on 14, 15 and 16 Jul, so "ten matched runs" is not an accurate description. Report the unpaired Mann–Whitney test (now computed) alongside the paired Wilcoxon, and describe the design as ten runs per policy on separate days.

## 4. Data-quality questions about the raw logs

Each of these needs an explanation in the dataset documentation, or needs checking against the original on-robot recordings.

1. **Vicon trajectory.** In `HWS-002-FIFO`/limo01, x, y and yaw are each a steady sinusoid with periods of 159.5 s, 212.4 s and 127.2 s. The ranges are symmetric (±1.916 m, ±1.757 m, ±0.394 rad) and the pattern repeats unchanged for 2 h.
2. **Motion vs heading.** In 62% of moving 1 s windows, the direction of travel is more than 15° off the Vicon heading. Top speed is 0.093 m/s. A differential-drive base can't move sideways. Was the robot run in mecanum/omni mode, or on a scripted trajectory? The manuscript says "differential-drive" and gives 0.30 m/s. Note that 0.30 m/s is the *simulation* speed in Sec. 5.1, not a hardware value.
3. **RSSI/SNR recorded for untransmitted packets.** About 1,900 rows per session with `sent = 0` still have `rssi_dbm`/`snr_db` values, and RSSI and SNR are uncorrelated (r ≈ 0.00). Which code filled these fields?
4. **Channel delay** is spread evenly over 0.165–0.175 s in every session, and `t_tx_ns == t_selected_ns` to the nanosecond.
5. **Deferral** has the same log-normal shape (median ≈154 s, σ ≈ 0.49, capped at 600 s) under all three policies, which matches the protocol's "log-normal, σ = 0.5". Under FIFO, about half of consecutive candidates are selected out of generation order.
6. `support/experiment_protocol.md` gives airtime as ≈92 ms. The Semtech formula for the configured link gives 102.7 ms, which matches the manuscript.

### Finding (2026-09-24): the timing fields are not radio measurements

- The only scheduler ROS node in the project's repositories (`MagyElbanhawy/BACS-ROS2_untested`, `ros2_ws/src/bacs_scheduler/bacs_scheduler/bacs_scheduler_node.py`, around lines 118–142) never talks to the RYLR998. It sleeps for a fixed "selection delay" and "transmission delay", then sleeps for `0.005 + random.uniform(0, 0.045)` s as the "network roundtrip", and logs those clock readings as `t_selected`, `t_tx` and `t_rx`.
- The same repository contains a different version of the same three sessions (`hardware/raw/BACS_v10_raw/...`). Its sessions start at 09:30:00 on 14/15/16 Jul (here 09:42:17, 10:13:42 and 09:55:08). They have ≈80 scheduler rows per session (here ≈2,090) and deferrals of a few milliseconds (here ≈154 s). Two different logs can't both be the recording of the same session.

**Consequence.** The scheduler logs in `hardware/raw/` can't be used as measurements of channel delay, deferral, RSSI/SNR or airtime. H5 (deferral dominance, the 906× ratio), Sec. 7.4 and Table 6 have no measured basis. The Vicon ground truth is exact sinusoids (item 1), so the physical map-alignment result (Sec. 7.3, abstract, H4) also can't be supported from this dataset. That holds whatever SLAM replay produces from these bags.

**What would fix it.** Either run a new physical experiment with a scheduler node that timestamps real RYLR998 events (`AT+SEND` → `+OK` for `t_tx`, `+RCV` for `t_rx`, and RSSI/SNR parsed from `+RCV` on sent packets only), or remove the physical-validation claims and present the paper as simulation-only. **Chosen (2026-09-24): new measured experiment.** See `docs/HARDWARE_EXPERIMENT_V2.md` and the `bacs_sender`/`bacs_receiver` nodes. Item 2 (drive type) only matters for a new experiment. It should then be recorded in the protocol: drive mode, commanded speed and trajectory.

## 5. Simulation outputs

Resolved in code. `bacs_sim` is the simulator, and a 3-seed S8 rerun matches the frozen results to 1.4 × 10⁻¹⁴. `scripts/reproduce_simulation.py`, the `sim_s8_*` figures and the report are wired to it (see `simulation/README.md`). Still to do: the full 30-seed rerun, and the S7-C and S9 figures.
