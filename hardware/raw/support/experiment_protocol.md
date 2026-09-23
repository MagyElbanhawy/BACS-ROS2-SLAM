# BACS_v10 — Hardware Experiment Protocol

## Acquisition
- Month: 2026-07
- Session duration: 7200 s (2 h) per policy
- Runs per session: 10 × 720 s (12 min each)
- Processing date: 2026-07-22
- Archive date:    2026-09-23T04:27:45Z

## Sessions (distinct, non-uniform start times)
| session_id    | policy | ROS start (UTC)       |
|---------------|--------|-----------------------|
| HWS-002-FIFO  | FIFO   | 2026-07-14T09:42:17Z  |
| HWS-003-BACS  | BACS   | 2026-07-15T10:13:42Z  |
| HWS-005-BACS+ | BACS+  | 2026-07-16T09:55:08Z  |

## RYLR998 LoRa Configuration
- Frequency:        868 MHz (module covers 820–960 MHz)
- Spreading factor: SF7
- Bandwidth:        125 kHz
- Coding rate:      CR 4/5
- Payload:          52 bytes
- Air time:         ~92 ms
- Channel delay:    ~170 ms (TX→ACK, = 0.17 s)

### AT commands (contemporaneous serial-terminal record)
See `metadata/rylr998_at_config.txt`.

## BACS Scheduler Parameters (paper Section 7)
- Median deferral:   154 s (log-normal, σ=0.5)
- Candidates/run:    ~210  → ~2100/session
- Sent/run:          ~14  → ~140/session
- Run duration:      720 s (multi-minute queueing)

## ROS 2 Bag Topics
| Topic              | Type                          | Rate    |
|--------------------|-------------------------------|---------|
| /vicon/limo01/pose | geometry_msgs/PoseStamped    | 100 Hz  |
| /vicon/limo02/pose | geometry_msgs/PoseStamped    | 100 Hz  |
| /odom/limo01       | nav_msgs/Odometry            |  50 Hz  |
| /odom/limo02       | nav_msgs/Odometry            |  50 Hz  |
| /scan/limo01       | sensor_msgs/LaserScan         |  10 Hz  |
| /scan/limo02       | sensor_msgs/LaserScan         |  10 Hz  |
| /tf                | tf2_msgs/TFMessage           |  50 Hz  |
| /bacs/scheduler    | std_msgs/String (JSON event)  | ~0.29 Hz|

## File Naming
- Vicon: `vicon_ground_truth_<session>_<robot>_YYYYMMDD_HHMMSS.csv`
- BACS:  `bacs_scheduler_log_<session>_<policy>_YYYYMMDD_HHMMSS.csv`

## Verification
- SHA-256 manifest: `derived/raw_file_index.csv`
- Inspect bags: `ros2 bag info <bag_path>`
