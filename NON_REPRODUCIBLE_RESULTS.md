# Non-Reproducible Results & Data Limitations

To ensure absolute academic integrity and transparency, this document details the limitations of the historical hardware data.

## 1. Missing Historical Media
- **Raw LoRa Serial Logs**: The historical ROS 2 bags (HWS-002, HWS-003, HWS-005) do not contain the raw RYLR998 serial ROS topic. Standalone `.txt` serial logs for these specific historical sessions were not preserved.
- **Standalone Vicon Files**: Original `.c3d` or `.x2d` Vicon files are not provided separately, as the ground-truth poses were recorded directly into the ROS 2 bags (`/vicon/limo01/pose`, `/vicon/limo02/pose`).
- **Photos/Videos**: Visual media of the physical setup for these historical sessions was not preserved in the archive.

## 2. Synthetic vs. Physical Data Clarification
- The `hardware/raw/` directory contains the **original, physical hardware recordings** (verified via `ros2 bag info` and direct SQLite timestamp extraction).
- Any Phase 2 algorithmic proofs (e.g., seed-level statistical tests, observability analysis) utilize synthetic or trace-driven data. These are strictly segregated to prevent any confusion with physical hardware evidence.

## 3. Future Physical Validation
Upcoming physical sessions will include strict NTP synchronization, raw serial logging via a dedicated failsafe script, and visual media to fully satisfy all reproducibility requirements.
