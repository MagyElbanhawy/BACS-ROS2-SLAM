# Synthetic test fixtures — NOT physical evidence

**Everything in this directory is synthetic. None of it was recorded on the LIMO
robots, the RYLR998 radios, or the Vicon system, and none of it may be cited as
physical/hardware evidence in the paper.**

These files were previously stored under `hardware/raw/HWS-101-*` … `HWS-130-*`
and `paper_results/physical/`, where they could be mistaken for measured data.
They were moved here in revision v3.

## Why they are known to be synthetic

| Check | Finding (all 30 sessions) |
|---|---|
| Duration of `fused_HWS-1xx-*.csv` | exactly 9.9 s each (a real run is 720 s) |
| limo02 pose estimate vs Vicon | `est_x == vicon_x` and `est_y == vicon_y` for every sample |
| Channel delay `rx_time - tx_time` in `candidates_*.csv` | the constant 0.170 s for every transmitted packet |

## Contents

| Path | What it is |
|---|---|
| `hardware_v2/HWS-101-FIFO` … `HWS-130-BACS+` | synthetic session folders in the V2 layout (candidate/serial/clock logs, `fused_*.csv`) |
| `derived/map_alignment_per_run.csv`, `map_alignment_summary.csv`, `map_alignment_statistics.csv` | "map-alignment RMSE" computed from the synthetic fused files |
| `derived/hardware_metrics.csv` | "Table 6" metrics computed from the synthetic candidate logs |
| `derived/synthetic_run_segmentation.csv` | run list needed to re-run the synthetic script |
| `scripts/compute_map_alignment_synthetic.py` | the script that produced the `map_alignment_*` files (formerly `scripts/repro/compute_map_alignment.py`) |
| `scripts/parse_hardware_metrics_synthetic.py` | the script that produced `hardware_metrics.csv` (formerly `scripts/parse_hardware_metrics.py`) |

Revision-v3 corrections to the synthetic statistics: Cliff's δ is now computed
from the data (−0.76 for BACS+ vs FIFO, −0.74 for BACS vs FIFO; it used to be
hard-coded as −0.81 for both), and the Wilcoxon column is labelled
`wilcoxon_p_two_sided` because `scipy.stats.wilcoxon` was called with its default
two-sided alternative (p = 0.00195). The previous label said one-sided.

They are kept only as parser/pipeline test inputs. Regenerate the synthetic statistics with

```bash
python synthetic_test_fixtures/scripts/compute_map_alignment_synthetic.py --poses unused \
  --segmentation synthetic_test_fixtures/derived/synthetic_run_segmentation.csv \
  --out synthetic_test_fixtures/derived
```

## Physical evidence

The only physical sessions are `hardware/raw/HWS-002-FIFO`, `HWS-003-BACS` and
`HWS-005-BACS+`. The physical claims they support are listed in
`PAPER_TRACEABILITY.md`.
