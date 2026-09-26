# Hardware experiment v2: measured protocol

This protocol replaces the HWS-002/003/005 dataset (see `REPRODUCIBILITY_ISSUES.md` §4). Every number the paper reports from hardware must come from files this protocol produces. New sessions are named `HWS-1xx-<POLICY>` (for example `HWS-101-FIFO`, `HWS-102-BACS`, `HWS-103-BACS+`) so they can't be confused with the old ones.

The concrete rerun parameters and bag-topic manifest are versioned in
`config/hardware_experiment_profiles.yaml`. Treat that file as the checklist for what must be
recorded; do not describe any of it as measured until new sessions exist.

## 1. What runs where

| Machine | Nodes | Radio address |
|---|---|---|
| LIMO-01 (NUC) | SLAM front-end, candidate generator, `bacs_sender` (`robot:=limo01`) | 1 |
| LIMO-02 (NUC) | same, with `robot:=limo02` | 2 |
| Fusion server | `bacs_receiver`, trust-weighted pose-graph fusion, `ros2 bag record`, Vicon bridge | 100 |

Build the package on every machine: `colcon build --packages-select bacs_scheduler`. It needs `pyserial` (`sudo apt install python3-serial`).

## 2. One-time setup and checks

1. **Radio settings.** Set on all three modules; the nodes do this at start.
   - `AT+NETWORKID=18`, `AT+BAND=868000000`, `AT+PARAMETER=7,7,1,8` (SF7, **BW code 7 = 125 kHz**, CR 4/5, 8 preamble symbols), `AT+CRFOP=14`.
   - The old config used `AT+PARAMETER=7,0,1,7`. The second field is a bandwidth *code*, and `0` is not 125 kHz.
   - Configure and verify each module once with `python3 scripts/hw/rylr998_setup.py --port /dev/ttyUSB0 --address <1|2|100> --out radio_setup_<name>.json`. It must print PASS.
   - The nodes repeat this at every start, save `radio_config_*.json`, and refuse to run if any read-back differs (for example `+PARAMETER=7,0,1,7`).
2. **Transmit power.** The g1 sub-band (868.0–868.6 MHz, 1% duty cycle) allows 25 mW ERP (14 dBm). Subtract your antenna gain from `power_dbm` if it is above 0 dBi.
3. **Clocks.** Run chrony on both NUCs, using the server as the time source. Each node writes `clock_*_start.txt` and `clock_*_end.txt` (`chronyc tracking` output). Accept a run only if |offset| < 1 ms on both robots.
   - Channel delay is `t_rcv` (server clock) − `t_cmd` (robot clock), so it is only as good as this synchronisation.
4. **Calibrate what `+OK` means** (once, about 18 min). Connect two modules to one computer, about 1 m apart, and run
   `python3 scripts/hw/calibrate_ok_timing.py --tx-port /dev/ttyUSB0 --rx-port /dev/ttyUSB1 --count 100 --out calibration/`.
   Both timestamps then come from one clock. The script compares command→`+OK` with the 102.7 ms time-on-air (and with the ≈6 ms needed to clock the command through the UART) and reports `OK_AFTER_TRANSMISSION`, `OK_ON_ACCEPT` or `AMBIGUOUS`. It also measures command→`+RCV`, which is the channel delay free of clock-sync error.
   Commit `calibration/` with the dataset. Then define channel delay in the paper from the verdict:
   - `OK_AFTER_TRANSMISSION`: `+OK` marks the end of transmission, so `t_rcv − t_ok` is the receive-side delay.
   - `OK_ON_ACCEPT`: `t_rcv − t_cmd` includes the airtime.
5. **Drive mode.** Record which mode each LIMO runs in (differential, mecanum, Ackermann or track), the commanded speed and the trajectory type. The paper must describe the platform exactly as recorded.

## 3. Candidate generation (`bacs_candidates`, on each robot)

Inter-robot candidates come from **keyframe scan matching**, using only the robot's own LiDAR and its own local pose (its SLAM/odometry TF). Vicon is never an input.

1. Every `keyframe_period_s` (2 s, as in the paper), if the robot has moved ≥ 5 cm or turned ≥ 5°, the latest scan is moved into `base_link` and stored as keyframe `kf`.
2. **Place recognition (shortlist only).** The keyframe gets a 60-byte range-profile descriptor (median range per 6° sector). The descriptor is published on the Wi-Fi side channel `/bacs/kf_desc`. Each new keyframe is compared with the other robot's stored descriptors over all rotations. At most the 3 closest with distance < 0.12 are shortlisted. Each keyframe pair is examined once, by the robot that created the later keyframe.
3. **On-demand points.** For a shortlisted pair, the robot requests that keyframe's points (`/bacs/kf_request` → `/bacs/kf_points`, float16).
4. **Geometric verification.** 2-D point-to-point ICP starts from the descriptor's yaw. It is accepted only if it converges with ≥ 80% inliers (within 0.15 m) and inlier RMSE ≤ 0.05 m. Descriptors alone are ambiguous in a room this size, so ICP decides.
   - On the synthetic test room, these thresholds recover 221/260 true pairs < 1 m apart.
   - 38 of 488 accepted pairs (7.8%) are wrong by > 0.1 m or > 3°. That is an outlier rate for the trust-weighted back-end to handle, and it must be measured on the real data (§7).
5. An accepted pair becomes one candidate on `/bacs/candidates`: the pose of `kf_j` (other robot) in `kf_i`'s frame, with the ICP covariance. The robot's own `bacs_sender` then schedules it over LoRa.

**Sensor-derived scores (report these definitions in the paper):**
- `predicted_trust = inlier_ratio × exp(−rmse / 0.05 m)`
- `information_score = 1 / (1 + sqrt(σ²x + σ²y) / 0.05 m)`, from the ICP covariance
- `pair_constraints` = the number of candidates this robot has already generated for that robot pair

**Disclosure.** Descriptors and on-demand keyframe points travel over the lab Wi-Fi, not LoRa. Only scheduled constraints go over LoRa to fusion. `sidechannel_<robot>.csv` logs the size of every side-channel message, so the paper can state the exact bytes per run.

**Freeze parameters before the evaluation runs.** Tune thresholds on a separate pilot session (not `HWS-1xx`) if needed, then commit them before block 1. Every attempt is logged, including rejects and why, in `candidate_attempts_<robot>.csv`. Keyframe poses go in `keyframes_<robot>.csv`.

Message format (also accepted from any other front-end):

```json
{"seq": 17, "robot_i": "limo01", "robot_j": "limo02", "kf_i": 120, "kf_j": 87, "t_gen_ns": 1790000000000000000,
 "predicted_trust": 0.82, "information_score": 0.41, "pair_constraints": 3,
 "dx": 1.23, "dy": -0.40, "dtheta": 0.05, "var_x": 0.0004, "var_y": 0.0005, "var_theta": 0.00002}
```

`seq` is 16-bit and must be unique per robot within a run. The 39-byte packet (sequence, robot indices, both keyframe IDs, relative pose, half-precision variances, trust and information, generation time) goes on air as exactly 52 base64 characters.

Each keyframe's local pose is also published on `/bacs/keyframes` (Wi-Fi). The fusion server builds the odometry chains from these.

## 3b. Fusion server (`bacs_fusion`)

This implements Eq. (1) and Eq. (6) with GTSAM (`pip install gtsam`), using the same conventions as `bacs_sim`:
- **Odometry edges** between consecutive keyframes have unit weight, σ = 0.04 m / 0.04 m / 0.02 rad.
- **Inter-robot edges** from `/bacs/received` get θ·Ω. By default Ω is the simulator's fixed Ω; `constraint_information:=icp` uses the ICP variances in the packet instead.
- **Trust.** θ = max(0.01, max(0, 1 − (‖e‖/0.5 m)³)·exp(−γΔt)). ‖e‖ is the translational residual against the current fused estimate when the constraint arrives, and Δt = receive time − generation time. γ = ln 2 / `t_defer_s`, with a default of 155 s (0.0045 s⁻¹). **Set `t_defer_s` to the median deferral measured in the pilot session**, not the draft paper's value.
- **Solver.** Gauss–Newton, re-run every second when new edges have arrived.
- **Gauge.** Each robot's first keyframe has a prior at its **start pose, measured from floor marks before the run** (`start_poses`, recorded in the run sheet). LIMO-01's prior is tight; LIMO-02's has σ = 0.10 m / 0.05 rad. This matches the simulator, where all robots start in a common frame. Never set start poses from Vicon during a run.
- **Output.** It broadcasts `map → <robot>/odom`, stamped with the node clock (the bag's `/clock` under `use_sim_time:=true`). `map → <robot>/base_link` then follows through the bag's own `odom → base_link`; broadcasting map → base_link directly would give base_link two parents.
- **Bag topic.** The server also publishes `/fused_poses` (JSON snapshots of the fused map poses) so the bag contains an explicit, easy-to-audit record of the fused trajectory in addition to `/tf`.
- **Logs.** Every inter-robot edge with its residual, age and θ goes to `fusion_edges.csv`; the mean trust goes to `fusion_summary.json`.

It can run live during the experiment (server) or afterwards on the recorded bag:
```bash
ros2 bag play <bag> --clock
ros2 run bacs_scheduler bacs_fusion --ros-args -p use_sim_time:=true -p session:=HWS-101-FIFO -p run:=1 \
  -p start_poses:="[x1, y1, yaw1, x2, y2, yaw2]"
python3 scripts/repro/log_fused_poses.py --ros-args -p use_sim_time:=true -p session:=HWS-101-FIFO \
  -p out:=paper_results/physical/fused/fused_HWS-101-FIFO_run01.csv
```

## 4. Session design: making run pairing defensible

Don't record one policy per day. Record in **blocks**. Each block runs all three policies back to back, in rotating order:

| Block | Order |
|---|---|
| 1, 4, 7, 10 | FIFO → BACS → BACS+ |
| 2, 5, 8 | BACS → BACS+ → FIFO |
| 3, 6, 9 | BACS+ → FIFO → BACS |

Run *k* of each policy then comes from block *k*: same hour, same battery state, same room conditions. That makes the paired Wilcoxon test legitimate. Report the unpaired Mann–Whitney test alongside it anyway; `compute_map_alignment.py` computes both. Use the same trajectory and the same start poses for all three policies in a block.

## 5. Per-run procedure (720 s)

On the server:
```bash
ros2 bag record -s mcap -o HWS-101-FIFO_run01 /tf /tf_static /scan/limo01 /scan/limo02 /odom/limo01 \
  /odom/limo02 /vicon/limo01/pose /vicon/limo02/pose /bacs/candidates /bacs/scheduler /bacs/received /bacs/keyframes /bacs/kf_desc /bacs/kf_request /fused_poses /map &
ros2 run bacs_scheduler bacs_receiver --ros-args -p session:=HWS-101-FIFO -p run:=1 -p port:=/dev/ttyUSB0
python3 scripts/repro/log_fused_poses.py --ros-args -p session:=HWS-101-FIFO \
  -p out:=fused_HWS-101-FIFO_run01.csv      # live, no sim time
```
On each robot:
```bash
ros2 run bacs_scheduler bacs_candidates --ros-args -p session:=HWS-101-FIFO -p run:=1 -p robot:=limo01 &
ros2 run bacs_scheduler bacs_sender --ros-args -p session:=HWS-101-FIFO -p run:=1 -p policy:=FIFO \
  -p robot:=limo01 -p address:=1 -p port:=/dev/ttyUSB0 -p trust_threshold:=0.05
```

Start the nodes, then drive for 720 s, then stop in reverse order (senders first, so pending candidates are logged as `PENDING_AT_END`). Don't edit, trim or re-run a file after the fact. A failed run is recorded as failed in the run sheet and repeated as a new run number.

For the surplus-candidate profile used to stress the duty-cycle limit, lower the keyframe
period and motion thresholds according to `config/hardware_experiment_profiles.yaml`
(`keyframe_period_s=1.0`, `min_motion_m=0.02`, `min_rotation_deg=2.0`, `shortlist=6`,
`place_threshold=0.16`). The target is a surplus stream (≥60 candidates per 10 minutes) while
holding the legal airtime budget at 0.6 s/min.

Each `~/bacs_hw_logs/<session>/run_XX/` folder then holds:
- `candidates_<robot>.csv`: one row per candidate, with final status `SENT`, `RADIO_ERROR`, `RADIO_TIMEOUT`, `REJECTED_TRUST`, `DROPPED_AGE` or `PENDING_AT_END`
- `serial_<robot>.csv` and `serial_server.csv`: every UART line, timestamped
- `received_server.csv`: every `+RCV`, with the module's RSSI and SNR
- `radio_config_*.json` and the `clock_*` snapshots

## 6. After the sessions

```bash
# 1. copy logs unmodified into hardware/raw/<session>/ (plus bag and Vicon CSVs), then:
python scripts/join_radio_logs.py hardware/raw/HWS-101-FIFO/logs \
  hardware/raw/HWS-101-FIFO/bacs_scheduler_log_HWS-101-FIFO_FIFO.csv   # prints sent/received/lost per run
python scripts/validate_hardware.py
python scripts/repro/check_fused_poses.py 'paper_results/physical/fused/fused_*.csv'   # must PASS
python scripts/repro/compute_map_alignment.py --poses 'paper_results/physical/fused/fused_*.csv'
python scripts/parse_hardware_logs.py          # Table 6 -> paper_results/physical/hardware_metrics.csv
python scripts/reproduce_physical.py && python scripts/reproduce_statistics.py && python scripts/update_report.py
```

## 7. Acceptance checklist, before any hardware number enters the paper

- [ ] `radio_config_*.json` shows SF7 / 125 kHz / CR 4/5 on all three modules.
- [ ] Clock offset < 1 ms at start and end of every run.
- [ ] Every `SENT` row has a matching `AT+SEND` / `+OK` pair in the serial transcript.
- [ ] RSSI/SNR appear only on received packets; the loss rate is reported.
- [ ] The fused-pose sanity gate passes for every session.
- [ ] Every row of `REPRODUCIBILITY_REPORT.md` is recomputed from the new sessions, and the manuscript uses those values.
