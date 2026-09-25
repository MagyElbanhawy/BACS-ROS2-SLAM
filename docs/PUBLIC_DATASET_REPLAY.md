# Public dataset replay

This repository includes an offline replay path for one genuinely public multi-robot dataset:
**UTIAS MRCLAM**. The code does **not** download the dataset and does **not** commit any dataset
copy or derived claim by default; you must point the replay script at a local extracted session.

## Dataset provenance

- Dataset: UTIAS Multi-Robot Cooperative Localization and Mapping (MRCLAM)
- Session layout expected by the adapter: `Barcodes.dat`, `Robot1_Groundtruth.dat`,
  `Robot2_Groundtruth.dat`, `Robot1_Measurement.dat`, `Robot2_Measurement.dat`
- Public reference pages:
  - official UTIAS MRCLAM page: `http://asrl.utias.utoronto.ca/datasets/mrclam/`
  - tooling/mirror reference used for layout cross-checks:
    `https://github.com/aau-cns/UTIAS_MRCLAM_dataset_tools`
- Offline mode: pass the local extracted session path to the replay CLI
- Acquisition metadata to record in your run notes: source URL, session name, archive filename,
  and `sha256sum` of the local archive or extracted directory manifest

## What the replay does

`analysis/public_dataset/mrclam.py` adapts robot-to-robot range/bearing observations into the
same candidate payload shape the ROS sender consumes. `analysis/public_dataset/replay.py` then
replays those candidates through the common FIFO/BACS/BACS+ sender policies with the same duty
cycle, trust threshold, and BACS+ observability augmentation used by the ROS-side scheduler.

The exported metrics are deterministic and include:

- generated and selected candidates
- airtime and airtime fraction of the duty-cycle budget
- selected-candidate relative translation RMSE against ground truth
- per-policy JSON summaries plus combined CSV outputs

These are **public-dataset replay results**, not hardware measurements.

## Run it

```bash
python3 -m scripts.repro.replay_public_dataset /path/to/MRCLAM_Dataset1 \
  --out paper_results/public_dataset
```

Expected outputs:

- `paper_results/public_dataset/mrclam_selected_candidates.csv`
- `paper_results/public_dataset/mrclam_summary.csv`
- `paper_results/public_dataset/mrclam_config.json`
- `paper_results/public_dataset/mrclam_<policy>_summary.json`

## Error handling

- Missing required MRCLAM files raise a clear `FileNotFoundError` naming the missing file.
- Empty or incompatible robot tracks raise a dataset-specific runtime error.
- The adapter is intentionally Python-only and has no ROS 2 dependency.
