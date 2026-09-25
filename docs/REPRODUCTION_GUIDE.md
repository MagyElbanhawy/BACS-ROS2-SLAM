# Reproduction guide

## A. Offline analysis (Python only)

1. Create an isolated Python environment and install `requirements.txt`. Run `git lfs pull` to fetch the bags and Vicon CSVs (≈7.2 GB).
2. Run `python scripts/validate_hardware.py`. Review `hardware/validation/` and stop if any status is invalid.
3. Run `python scripts/reproduce_physical.py`, then `python scripts/reproduce_statistics.py`, then `python scripts/update_report.py`.
4. Run `python scripts/reproduce_simulation.py`. Its outputs are simulated; see `simulation/README.md` for its limits.
5. Run `python scripts/generate_figures.py` and `python -m pytest -q`.

Results marked `NOT_COMPUTABLE` are evidence limitations, not imputed values. Metric definitions are in `docs/METRIC_DEFINITIONS.md`.

The implemented follow-up hardware rerun configuration is documented in
`config/hardware_experiment_profiles.yaml` and `docs/HARDWARE_EXPERIMENT_V2.md`. It is a plan
for future sessions, not a claimed result in this repository.

## B. Fused poses and map-alignment RMSE (ROS 2 Humble)

Map-alignment RMSE needs the fused-map pose of each robot, which the bags don't contain. You produce it by replaying each bag through the same SLAM/fusion stack while `scripts/repro/log_fused_poses.py` records `map -> <robot>/base_link` next to Vicon at 10 Hz.

### Step 1: check what the bag provides

```bash
ros2 bag info hardware/raw/HWS-002-FIFO/HWS-002-FIFO_20260714_094217_mcap
```

Confirm the topic names (`/scan/limo0X`, `/odom/limo0X`, `/tf`, `/vicon/limo0X/pose`). Then check the frame names in `/tf` and that your SLAM launch remaps to them. Every node needs `use_sim_time:=true`.

### Step 2: sanity gate on a short replay (do this before logging everything)

Terminal 1:
```bash
ros2 bag play hardware/raw/HWS-002-FIFO/HWS-002-FIFO_20260714_094217_mcap --clock
```
Terminal 2: your SLAM/fusion launch, with `use_sim_time:=true`.

Terminal 3, for about 2 minutes, then Ctrl-C:
```bash
python3 scripts/repro/log_fused_poses.py --ros-args -p use_sim_time:=true \
  -p session:=HWS-002-FIFO -p out:=/tmp/gate_HWS-002-FIFO.csv
python3 scripts/repro/check_fused_poses.py /tmp/gate_HWS-002-FIFO.csv
```

For each robot, the check prints speed and motion-vs-heading alignment for both the estimate and Vicon, and ends in PASS or FAIL:

- **Estimate FAIL, Vicon PASS**: the fused-map or `base_link` convention is wrong. Check which way `base_link` +x points and which broadcaster publishes `map`.
- **Both FAIL on heading**: the robot isn't moving along its heading in the ground truth itself (see `REPRODUCIBILITY_ISSUES.md` §4). That is a dataset question, not a TF bug.
- **Speed-ratio FAIL**: localisation isn't tracking (wrong `/scan` or `/odom` topics, or a missing `use_sim_time`).

The logger's frame and topic names are parameters: `map_frame`, `robots`, `base_frame_format` (default `{robot}/base_link`) and `vicon_topic_format` (default `/vicon/{robot}/pose`).

### Step 3: log every session (full 2 h replay each)

Run the whole replay for each session, starting the logger **before** playback so the first run isn't missed. Restart SLAM between sessions so each session starts from an empty map.

```bash
mkdir -p paper_results/physical/fused
for bag in hardware/raw/HWS-002-FIFO/*_mcap hardware/raw/HWS-003-BACS/*_mcap "hardware/raw/HWS-005-BACS+"/*_mcap; do
  sess=$(basename "$(dirname "$bag")")
  # (start the SLAM/fusion stack for this session here)
  python3 scripts/repro/log_fused_poses.py --ros-args -p use_sim_time:=true \
    -p session:="$sess" -p out:="paper_results/physical/fused/fused_${sess}.csv" &
  logger=$!
  sleep 3
  ros2 bag play "$bag" --clock
  kill -INT $logger; wait $logger
  # (stop the SLAM/fusion stack here)
done
python3 scripts/repro/check_fused_poses.py 'paper_results/physical/fused/fused_*.csv'
```

### Step 4: compute and report

```bash
python3 scripts/repro/compute_map_alignment.py \
  --poses 'paper_results/physical/fused/fused_*.csv' \
  --segmentation paper_results/physical/run_segmentation.csv \
  --out paper_results/physical
python3 scripts/update_report.py
```

Once the fused CSVs exist, `scripts/reproduce_physical.py` also runs this step automatically.

The outputs are `map_alignment_per_run.csv`, `map_alignment_summary.csv` (mean ± SD, t-based 95% CI, median and IQR per policy) and `map_alignment_statistics.csv` (paired Wilcoxon, Mann–Whitney and Cliff's δ for each policy pair). `REPRODUCIBILITY_REPORT.md` marks each draft-paper claim MATCH or MISMATCH. Wherever it says MISMATCH, update the manuscript to the recomputed value.

## C. Public dataset replay (Python only)

Use `docs/PUBLIC_DATASET_REPLAY.md` for the dataset layout and provenance notes. The replay is
offline-only: the repository does not download or commit the public dataset for you.

```bash
python3 scripts/repro/replay_public_dataset.py /path/to/MRCLAM_Dataset1 \
  --out paper_results/public_dataset
```

This writes deterministic CSV/JSON outputs for FIFO, BACS and BACS+ under
`paper_results/public_dataset/`. Those outputs are separate from the physical evidence and must
be labelled as public-dataset replay results.
