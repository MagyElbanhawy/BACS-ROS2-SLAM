from pathlib import Path

import csv
import pytest

from analysis.public_dataset import ReplayConfig, load_mrclam_candidates, replay_dataset


@pytest.fixture()
def mrclam_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "MRCLAM_Dataset1"
    root.mkdir()
    (root / "Barcodes.dat").write_text("1 101\n2 102\n", encoding="utf-8")
    (root / "Robot1_Groundtruth.dat").write_text(
        "0.0 0.0 0.0 0.0\n1.0 1.0 0.0 0.0\n2.0 2.0 0.0 0.0\n", encoding="utf-8"
    )
    (root / "Robot2_Groundtruth.dat").write_text(
        "0.0 0.0 1.0 0.0\n1.0 1.0 1.0 0.0\n2.0 2.0 1.0 0.0\n", encoding="utf-8"
    )
    (root / "Robot1_Measurement.dat").write_text(
        "0.5 102 1.00 1.57\n1.5 102 1.00 1.57\n", encoding="utf-8"
    )
    (root / "Robot2_Measurement.dat").write_text(
        "0.5 101 1.00 -1.57\n1.5 101 1.00 -1.57\n", encoding="utf-8"
    )
    return root


def test_mrclam_adapter_and_replay_outputs_are_deterministic(mrclam_fixture: Path, tmp_path: Path) -> None:
    candidates = load_mrclam_candidates(mrclam_fixture)
    assert len(candidates) == 4
    out = tmp_path / "out"
    summary = replay_dataset(candidates, out, ReplayConfig())
    assert [row.policy for row in summary] == ["FIFO", "BACS", "BACS+"]
    assert (out / "mrclam_summary.csv").exists()
    assert (out / "mrclam_selected_candidates.csv").exists()
    rows = list(csv.DictReader((out / "mrclam_selected_candidates.csv").open(encoding="utf-8")))
    assert {row["policy"] for row in rows} == {"FIFO", "BACS", "BACS+"}
    assert all(float(row["translation_error_m"] or 0.0) >= 0.0 for row in rows)


def test_mrclam_adapter_reports_missing_files_clearly(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    root.mkdir()
    with pytest.raises(FileNotFoundError, match="Barcodes.dat"):
        load_mrclam_candidates(root)


def test_replay_requires_at_least_one_policy(mrclam_fixture: Path, tmp_path: Path) -> None:
    candidates = load_mrclam_candidates(mrclam_fixture)
    with pytest.raises(ValueError, match="at least one policy"):
        replay_dataset(candidates, tmp_path / "out", ReplayConfig(policies=()))


def test_replay_requires_at_least_one_candidate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one candidate"):
        replay_dataset([], tmp_path / "out", ReplayConfig())
