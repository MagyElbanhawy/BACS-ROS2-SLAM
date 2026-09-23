# Data dictionary

## Scheduler log

| Field | Unit | Meaning |
|---|---:|---|
| `session`, `run`, `seq`, `policy`, `robot` | N/A | Session, logged run, sequence, policy, and originating robot |
| `t_gen_ns`, `t_selected_ns`, `t_tx_ns`, `t_rx_ns` | ns | Generation, selection, transmit, and receive timestamps |
| `deferral_ns` | ns | `t_selected_ns - t_gen_ns` |
| `channel` | N/A | Configured radio channel |
| `rssi_dbm`, `snr_db` | dBm, dB | Logged radio measurements |
| `payload_hex`, `payload_bytes` | hex, bytes | Serialized payload and its size |
| `freq_mhz`, `sf`, `bw_khz`, `cr` | MHz, N/A, kHz, N/A | Radio configuration |
| `sent` | boolean | Whether the candidate was transmitted |

`t_tx_ns` and `t_rx_ns` are zero when not recorded; no channel delay or packet age is inferred for those rows.

## Vicon log

`timestamp_ns` is nanoseconds. `x`, `y`, and `z` are metres; roll, pitch, and yaw are radians; `vx`, `vy`, and `vz` are metres per second.
