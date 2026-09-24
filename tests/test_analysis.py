import csv
from pathlib import Path

from analysis.physical.pipeline import SCHEDULER_FIELDS, VICON_FIELDS, quantiles, validate_scheduler, vicon_rows, write_csv
from analysis.statistics.metrics import cliffs_delta, paired_wilcoxon


def test_scheduler_schema_and_timing_validation(tmp_path: Path) -> None:
    path = tmp_path / "log.csv"
    row = dict.fromkeys(SCHEDULER_FIELDS, "")
    row.update({"session": "S", "run": "1", "seq": "0", "policy": "FIFO", "robot": "limo01",
                "t_gen_ns": "1", "t_selected_ns": "2", "t_tx_ns": "0", "t_rx_ns": "0",
                "deferral_ns": "1", "channel": "0", "rssi_dbm": "-90", "snr_db": "2", "payload_hex": "00"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCHEDULER_FIELDS); writer.writeheader(); writer.writerow(row)
    assert validate_scheduler(path)["status"] == "VALID"


def test_quantiles_and_statistics() -> None:
    assert quantiles([1, 2, 3])["median"] == 2
    assert cliffs_delta([3, 4], [1, 2]) == 1
    assert 0 <= paired_wilcoxon([1, 2, 3], [2, 3, 4])["p_value"] <= 1


def test_vicon_schema_validation(tmp_path: Path) -> None:
    raw = tmp_path / "hardware" / "raw" / "HWS-002-FIFO"; raw.mkdir(parents=True)
    path = raw / "vicon_ground_truth_HWS-002-FIFO_limo01.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=VICON_FIELDS); writer.writeheader()
        writer.writerow(dict(zip(VICON_FIELDS, [1, 0, 0, 0, 0, 0, 0, 0, 0, 0])))
        writer.writerow(dict(zip(VICON_FIELDS, [2, 1, 1, 1, 0, 0, 0, 0, 0, 0])))
    assert vicon_rows(tmp_path)[0]["status"] == "VALID"
