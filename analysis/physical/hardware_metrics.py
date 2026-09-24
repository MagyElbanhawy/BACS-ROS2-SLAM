"""Table 6 metrics per policy from measured hardware sessions (docs/METRIC_DEFINITIONS.md).

Per session ``hardware/raw/<session>/`` this reads the joined scheduler log
(``bacs_scheduler_log_*.csv`` from scripts/join_radio_logs.py) and the per-run folders
``logs/run_XX/`` (clock snapshots, ``fusion_edges.csv``); map-alignment RMSE comes from
``paper_results/physical/map_alignment_per_run.csv``.

Definitions (delivered = sent and received by the server):
  packet age      t_rx - t_gen            (delivered packets, median)
  deferral        t_selected - t_gen      (delivered packets, median)
  channel delay   t_rx - t_tx             (delivered packets, median; t_tx = AT+SEND write)
  airtime util.   sent_r * T_air / (duty_cycle * duration_r), per robot r and run, averaged;
                  duration_r is the sender's measured lifetime (clock snapshots)
  server trust    mean theta_ij over every inter-robot edge the fusion server added
  overhead        time to rank the queue at each transmission
Sessions without a measured ``received`` column (the HWS-002/003/005 dataset) are reported as
NOT_MEASURED_LEGACY and get no values.
"""

from __future__ import annotations

import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import lora_airtime_s

SESSION = re.compile(r"^HWS-\d+-(FIFO|BACS\+?)$")


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _median(values: list[float]) -> float | str:
    return statistics.median(values) if values else ""


def _snapshot_ns(path: Path) -> int | None:
    if not path.exists():
        return None
    first = path.read_text(encoding="utf-8").splitlines()[0]
    return int(first.split("=", 1)[1]) if first.startswith("time_ns=") else None


def session_metrics(session_dir: Path, duty_cycle: float) -> dict[str, Any]:
    policy = SESSION.match(session_dir.name).group(1)
    logs = sorted(session_dir.glob("bacs_scheduler_log_*.csv"))
    base = {"policy": policy, "session": session_dir.name}
    rows = [r for path in logs for r in _rows(path)]
    if not rows or "received" not in rows[0]:
        return {**base, "status": "NOT_MEASURED_LEGACY"}
    delivered = [r for r in rows if r["received"] == "1"]
    age = [(int(r["t_rx_ns"]) - int(r["t_gen_ns"])) / 1e9 for r in delivered]
    deferral = [(int(r["t_selected_ns"]) - int(r["t_gen_ns"])) / 1e9 for r in delivered]
    channel = [(int(r["t_rx_ns"]) - int(r["t_tx_ns"])) / 1e9 for r in delivered]
    after_ok = [(int(r["t_rx_ns"]) - int(r["t_ok_ns"])) / 1e9 for r in delivered if r.get("t_ok_ns")]
    overhead = [float(r["rank_time_us"]) / 1000 for r in rows if r.get("rank_time_us")]

    by_run: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_run[r["run"]].append(r)
    airtime = lora_airtime_s(52)
    utilisation, fraction, duration_sources = [], [], set()
    generated_per_run, sent_per_run = [], []
    for run, records in by_run.items():
        generated_per_run.append(len(records)); sent_per_run.append(sum(r["sent"] == "1" for r in records))
        run_dir = session_dir / "logs" / f"run_{int(run):02d}"
        for robot in sorted({r["robot"] for r in records}):
            mine = [r for r in records if r["robot"] == robot]
            start, end = _snapshot_ns(run_dir / f"clock_{robot}_start.txt"), _snapshot_ns(run_dir / f"clock_{robot}_end.txt")
            if start and end and end > start:
                duration = (end - start) / 1e9; duration_sources.add("clock_snapshots")
            else:
                times = [int(r[k]) for r in mine for k in ("t_gen_ns", "t_tx_ns") if r[k] not in ("", "0")]
                duration = (max(times) - min(times)) / 1e9; duration_sources.add("log_span")
            used = sum(r["sent"] == "1" for r in mine) * airtime
            utilisation.append(used / (duty_cycle * duration)); fraction.append(used / duration)

    thetas = [float(r["theta"]) for path in sorted(session_dir.glob("logs/run_*/fusion_edges.csv"))
              for r in _rows(path) if r.get("status") == "ADDED"]
    return {**base, "runs": len(by_run), "delivered_packets": len(delivered),
            "median_packet_age_s": _median(age), "median_deferral_s": _median(deferral),
            "median_channel_delay_s": _median(channel), "median_rx_after_ok_s": _median(after_ok),
            "generated_per_session": len(rows), "transmitted_per_session": sum(r["sent"] == "1" for r in rows),
            "received_per_session": len(delivered),
            "generated_per_run_median": _median(generated_per_run), "transmitted_per_run_median": _median(sent_per_run),
            "delivery_ratio": len(delivered) / max(1, sum(r["sent"] == "1" for r in rows)),
            "mean_server_trust": statistics.fmean(thetas) if thetas else "", "server_trust_edges": len(thetas),
            "airtime_utilisation_pct": 100 * statistics.fmean(utilisation) if utilisation else "",
            "airtime_fraction_of_run_pct": 100 * statistics.fmean(fraction) if fraction else "",
            "run_duration_source": "+".join(sorted(duration_sources)),
            "scheduler_overhead_ms_mean": statistics.fmean(overhead) if overhead else "",
            "scheduler_overhead_ms_p95": statistics.quantiles(overhead, n=20)[-1] if len(overhead) > 1 else "",
            "status": "MEASURED"}


def add_map_alignment(rows: list[dict[str, Any]], per_run: Path) -> None:
    if not per_run.exists():
        return
    values: dict[str, list[float]] = defaultdict(list)
    for r in _rows(per_run):
        if r.get("status") == "COMPUTED":
            values[r["policy"]].append(float(r["map_alignment_rmse_m"]))
    for row in rows:
        v = values.get(row["policy"], [])
        if row["status"] == "MEASURED" and v:
            row["map_alignment_rmse_mean_m"] = statistics.fmean(v)
            row["map_alignment_rmse_sd_m"] = statistics.stdev(v) if len(v) > 1 else 0.0
            row["map_alignment_runs"] = len(v)


def hardware_metrics(raw: Path, map_per_run: Path, out: Path, duty_cycle: float = 0.01) -> list[dict[str, Any]]:
    rows = [session_metrics(d, duty_cycle) for d in sorted(raw.iterdir()) if d.is_dir() and SESSION.match(d.name)]
    add_map_alignment(rows, map_per_run)
    fields: list[str] = []
    for row in rows:
        fields += [k for k in row if k not in fields]
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    return rows
