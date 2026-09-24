import csv
from pathlib import Path

import pytest

from analysis.physical.hardware_metrics import hardware_metrics
from analysis.physical.radio_join import JOINED_FIELDS
from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import lora_airtime_s

T0 = 1_790_000_000_000_000_000
S = 1_000_000_000


def row(seq: int, sent: bool, received: bool) -> dict:
    gen = T0 + seq * 10 * S
    selected = gen + 150 * S
    return {"session": "HWS-101-FIFO", "run": 1, "seq": seq, "policy": "FIFO", "robot": "limo01", "t_gen_ns": gen,
            "t_selected_ns": selected if sent else 0, "t_tx_ns": selected if sent else 0,
            "t_ok_ns": selected + 103_000_000 if sent else "", "t_rx_ns": selected + 170_000_000 if received else 0,
            "deferral_ns": 150 * S if sent else "", "payload_bytes": 52, "sent": int(sent), "received": int(received),
            "status": "SENT" if sent else "PENDING_AT_END", "rank_time_us": 600 if sent else ""}


def test_table6_metrics_from_a_measured_session(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    session = raw / "HWS-101-FIFO"; run_dir = session / "logs" / "run_01"; run_dir.mkdir(parents=True)
    with (session / "bacs_scheduler_log_HWS-101-FIFO_FIFO.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOINED_FIELDS, extrasaction="ignore"); writer.writeheader()
        writer.writerows([row(0, True, True), row(1, True, True), row(2, True, False), row(3, False, False)])
    (run_dir / "clock_limo01_start.txt").write_text(f"time_ns={T0}\n")
    (run_dir / "clock_limo01_end.txt").write_text(f"time_ns={T0 + 720 * S}\n")
    (run_dir / "fusion_edges.csv").write_text("theta,status\n0.4,ADDED\n0.6,ADDED\n")
    legacy = raw / "HWS-002-FIFO"; legacy.mkdir()
    (legacy / "bacs_scheduler_log_HWS-002-FIFO_FIFO_x.csv").write_text("session,run,sent\nHWS-002-FIFO,1,1\n")
    per_run = tmp_path / "map.csv"
    per_run.write_text("policy,run,map_alignment_rmse_m,status\nFIFO,1,0.3,COMPUTED\nFIFO,2,0.5,COMPUTED\n")

    rows = {r["session"]: r for r in hardware_metrics(raw, per_run, tmp_path / "out.csv")}
    assert rows["HWS-002-FIFO"]["status"] == "NOT_MEASURED_LEGACY"
    m = rows["HWS-101-FIFO"]
    assert m["status"] == "MEASURED" and m["delivered_packets"] == 2
    assert m["median_deferral_s"] == pytest.approx(150) and m["median_packet_age_s"] == pytest.approx(150.17)
    assert m["median_channel_delay_s"] == pytest.approx(0.17) and m["median_rx_after_ok_s"] == pytest.approx(0.067)
    assert (m["generated_per_session"], m["transmitted_per_session"], m["received_per_session"]) == (4, 3, 2)
    assert m["airtime_utilisation_pct"] == pytest.approx(100 * 3 * lora_airtime_s(52) / (0.01 * 720))
    assert m["run_duration_source"] == "clock_snapshots"
    assert m["mean_server_trust"] == pytest.approx(0.5) and m["scheduler_overhead_ms_mean"] == pytest.approx(0.6)
    assert m["map_alignment_rmse_mean_m"] == pytest.approx(0.4)
