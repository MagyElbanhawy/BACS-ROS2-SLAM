import csv
import math
from pathlib import Path

import numpy as np
import pytest

from analysis.physical.map_alignment import compare, fit_rotation, load_fused, per_run_rmse, rotate, summarise


def write_session(path: Path, session: str, offset_m: float, map_rotation: float, start_ns: int = 0) -> None:
    """Two robots crossing each other; robot 2's map is shifted by ``offset_m``."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["session", "stamp_ns", "robot", "est_x", "est_y", "est_yaw", "tf_stamp_ns",
                         "vicon_stamp_ns", "vicon_x", "vicon_y", "vicon_yaw"])
        for k in range(200):
            t = start_ns + k * 100_000_000
            s = k / 199
            for robot, vx, vy, shift in (("limo01", -2 + 4 * s, 0.1, 0.0), ("limo02", 2 - 4 * s, -0.1, offset_m)):
                ex, ey = rotate(np.array([[vx + shift, vy]]), -map_rotation)[0] + (5.0, -3.0)
                writer.writerow([session, t, robot, ex, ey, 0, t, t, vx, vy, 0])


def test_fit_rotation_recovers_angle() -> None:
    source = np.array([[1.0, 0.0], [0.0, 2.0], [-1.0, 1.0]])
    assert fit_rotation(source, rotate(source, 0.4)) == pytest.approx(0.4)


def test_rmse_is_invariant_to_map_frame_and_measures_offset(tmp_path: Path) -> None:
    write_session(tmp_path / "a.csv", "HWS-002-FIFO", offset_m=0.2, map_rotation=math.radians(30))
    write_session(tmp_path / "b.csv", "HWS-005-BACS+", offset_m=0.0, map_rotation=math.radians(-70))
    segmentation = [{"policy": p, "run": 1, "start": 0, "end": 10**12} for p in ("FIFO", "BACS+")]
    rows = {r["policy"]: r for r in per_run_rmse(load_fused([tmp_path / "a.csv", tmp_path / "b.csv"]), segmentation)}
    assert rows["BACS+"]["map_alignment_rmse_m"] == pytest.approx(0.0, abs=1e-9)
    assert rows["FIFO"]["map_alignment_rmse_m"] == pytest.approx(0.2, abs=0.02)
    assert rows["FIFO"]["status"] == "COMPUTED" and rows["FIFO"]["colocation_pairs"] > 20


def test_statistics_report_paired_and_unpaired_tests() -> None:
    rows = [{"policy": p, "run": r, "map_alignment_rmse_m": v, "status": "COMPUTED"}
            for p, base in (("FIFO", 0.5), ("BACS", 0.4), ("BACS+", 0.3)) for r, v in
            enumerate(base + 0.01 * np.arange(10), start=1)]
    stats = {(s["reference"], s["candidate"]): s for s in compare(rows)}
    fifo_plus = stats[("FIFO", "BACS+")]
    assert fifo_plus["cliffs_delta"] == -1.0 and fifo_plus["pairs_candidate_lower"] == 10
    assert fifo_plus["wilcoxon_paired_p_one_sided_less"] < 0.01 and fifo_plus["mannwhitney_p_two_sided"] < 0.01
    assert [s["n_runs"] for s in summarise(rows)] == [10, 10, 10]
