# Hardware experiment v2: measured protocol

This protocol replaces the HWS-002/003/005 dataset (see `REPRODUCIBILITY_ISSUES.md` §4). Every number the paper reports from hardware must come from files this protocol produces. New sessions are named `HWS-1xx-<POLICY>` (for example `HWS-101-FIFO`, `HWS-102-BACS`, `HWS-103-BACS+`) so they can't be confused with the old ones.

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

## 3. Candidate interface

`bacs_sender` consumes `std_msgs/String` JSON on `/bacs/candidates`, one inter-robot constraint candidate per message:

```json
{"seq": 17, "robot_i": "limo01", "robot_j": "limo02", "t_gen_ns": 1790000000000000000,
 "predicted_trust": 0.82, "information_score": 0.41, "pair_constraints": 3,
 "dx": 1.23, "dy": -0.40, "dtheta": 0.05, "var_x": 0.01, "var_y": 0.01, "var_theta": 0.002}
```

- `seq` must be unique per robot within a run.
- A robot only transmits candidates whose `robot_i` is itself.
- The payload (sequence, robot indices, relative pose, variances, trust, information and generation time) is packed into 39 bytes and sent as 52 base64 characters, so the on-air size is exactly 52 bytes.

**Prerequisite:** the candidate generator (the inter-robot loop-closure front-end that publishes this topic) must exist and run on the robots. It isn't in this repository.

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
  /odom/limo02 /vicon/limo01/pose /vicon/limo02/pose /bacs/candidates /bacs/scheduler /bacs/received /map &
ros2 run bacs_scheduler bacs_receiver --ros-args -p session:=HWS-101-FIFO -p run:=1 -p port:=/dev/ttyUSB0
python3 scripts/repro/log_fused_poses.py --ros-args -p session:=HWS-101-FIFO \
  -p out:=fused_HWS-101-FIFO_run01.csv      # live, no sim time
```
On each robot:
```bash
ros2 run bacs_scheduler bacs_sender --ros-args -p session:=HWS-101-FIFO -p run:=1 -p policy:=FIFO \
  -p robot:=limo01 -p address:=1 -p port:=/dev/ttyUSB0
```

Start the nodes, then drive for 720 s, then stop in reverse order (senders first, so pending candidates are logged as `PENDING_AT_END`). Don't edit, trim or re-run a file after the fact. A failed run is recorded as failed in the run sheet and repeated as a new run number.

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
python scripts/reproduce_physical.py && python scripts/reproduce_statistics.py && python scripts/update_report.py
```

## 7. Acceptance checklist, before any hardware number enters the paper

- [ ] `radio_config_*.json` shows SF7 / 125 kHz / CR 4/5 on all three modules.
- [ ] Clock offset < 1 ms at start and end of every run.
- [ ] Every `SENT` row has a matching `AT+SEND` / `+OK` pair in the serial transcript.
- [ ] RSSI/SNR appear only on received packets; the loss rate is reported.
- [ ] The fused-pose sanity gate passes for every session.
- [ ] Every row of `REPRODUCIBILITY_REPORT.md` is recomputed from the new sessions, and the manuscript uses those values.
