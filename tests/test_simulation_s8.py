from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analysis.simulation.s8 import ARMS, run


def fake_raw(path: Path) -> None:
    """Synthetic S8 table with a known effect: BACS+ (0.30, 6) is 40 % below FIFO in 25 of 30 seeds."""
    rng = np.random.default_rng(0)
    rows = []
    for n in (2, 3, 4, 5):
        for seed in range(10, 40):
            base = 0.3 + rng.normal(0, 0.02)
            better = seed < 35
            for arm, align in (("fifo", base), ("bacs_gated", base * 0.7), ("plus_0.30_6", base * (0.6 if better else 1.1)),
                               ("plus_0.60_5", base * 0.65)):
                rows.append({"n_robots": n, "seed": seed, "arm": arm, "pose_rmse": 0.4 + rng.normal(0, 0.05),
                             "align_rmse": align, "trust_yield": 0.4, "n_delivered": 32})
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_s8_statistics_from_frozen_then_regenerated(tmp_path: Path) -> None:
    fake_raw(tmp_path / "paper_results" / "simulation" / "frozen" / "s8_30seed_raw.csv")
    summary, tests, source = run(tmp_path)
    assert source == "frozen" and set(summary.arm) == set(ARMS)
    row = tests[(tests.n_robots == 5) & (tests.arm_a == "plus_0.30_6") & (tests.arm_b == "fifo")
                & (tests.metric == "align_rmse")].iloc[0]
    assert row.seeds_a_lower == 25 and row.n_pairs == 30 and row.wilcoxon_p < 0.01
    expected = 100 * (1 - (25 * 0.6 + 5 * 1.1) / 30)
    assert row.improvement_pct == pytest.approx(expected, abs=1.0)
    assert -1 <= row.cliffs_delta < 0
    fake_raw(tmp_path / "paper_results" / "s8_30seed_raw.csv")
    assert run(tmp_path)[2] == "regenerated"
