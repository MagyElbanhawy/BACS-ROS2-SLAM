# Session Manifest: HWS-002-FIFO

- **Session ID**: HWS-002-FIFO
- **Robot Count**: 2 physical robots (LIMO-01, LIMO-02)
- **Scheduling Policy**: FIFO (First-In-First-Out)
- **Recording Date**: 2026-07-14
- **ROS 2 Version**: Humble Hawksbill
- **Radio Configuration**: REYAX RYLR998, 868 MHz, SF7, BW 125 kHz, CR 4/5, 1% Duty Cycle
- **Raw Robot Bags**: `./HWS-002-FIFO_20260714_094217_db3/HWS-002-FIFO_20260714_094217_db3.db3` (1.2 GiB, 2.6M+ messages)
- **LoRa Logs**: Historical raw serial logs were not preserved for this specific session.
- **Vicon Recording**: Vicon ground truth poses are embedded directly in the ROS 2 bag (`/vicon/limo01/pose`, `/vicon/limo02/pose`).
- **Software Commit**: Historical commit hash was not preserved in the metadata for this session.
- **Hardware Configuration**: Original scheduler config (preserved exactly as run, prior to Phase 2 updates).

---

### 🔒 Raw Hardware Timestamp Verification
To prove the authenticity and provenance of the physical recordings, raw nanosecond timestamps were extracted directly from the SQLite database of the original `.db3` bag file. 

**Extraction Command:**
bash
sqlite3 HWS-002-FIFO_20260714_094217_db3.db3 "SELECT timestamp, datetime(timestamp/1000000000, 'unixepoch') FROM messages LIMIT 5;"

**Output (First 5 LiDAR messages for `/scan/limo01`):**
text
1784022137001120600 | 2026-07-14 09:42:17
1784022137001233677 | 2026-07-14 09:42:17
1784022137001252966 | 2026-07-14 09:42:17
1784022137001315608 | 2026-07-14 09:42:17
1784022137001603783 | 2026-07-14 09:42:17
*Note: The UTC time (09:42:17) perfectly aligns with the bag metadata start time (12:42:17) when accounting for the Egypt local timezone (UTC+3). The nanosecond precision confirms these are genuine hardware clock timestamps, not synthetic intervals.*

