# Experiment protocol

The physical evidence consists of FIFO (`HWS-002-FIFO`), BACS (`HWS-003-BACS`), and BACS+ (`HWS-005-BACS+`) sessions. Each session manifest specifies ten 720-second runs. Run segmentation is taken from the `run` field of the immutable scheduler logs; it is not inferred from a periodic partition.

Raw data are never rewritten. Validation and analysis write only to `hardware/validation/` and `paper_results/`. A map-alignment RMSE is calculated only when a fused-map or estimated-trajectory input is present; Vicon alone is insufficient.

The follow-up rerun protocol is planned, not executed, and is captured separately in
`config/hardware_experiment_profiles.yaml` and `docs/HARDWARE_EXPERIMENT_V2.md`. That V2
configuration adds `/fused_poses` bag logging, surplus-candidate settings intended to make the
0.6 s/min airtime budget bind, and 12-minute interleaved FIFO/BACS/BACS+ blocks with rotation
metadata and resets.
