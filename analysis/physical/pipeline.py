"""Evidence-preserving physical-data validation and analysis pipeline.

This module writes only derived files outside ``hardware/raw``.  It deliberately
does not infer unrecorded map estimates, channel timing, or run boundaries.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

SESSION_PATTERN = re.compile(r"^HWS-\d+-(FIFO|BACS\+?)$")


class _Policies(dict):
    """Session -> policy, derived from the session name (``HWS-<n>-<POLICY>``)."""

    def __missing__(self, session: str) -> str:
        match = SESSION_PATTERN.match(session)
        if not match:
            raise KeyError(session)
        return match.group(1)

    def __contains__(self, session: object) -> bool:
        return isinstance(session, str) and SESSION_PATTERN.match(session) is not None

    def get(self, session: str, default: str = "") -> str:  # type: ignore[override]
        return self[session] if session in self else default


POLICIES = _Policies()
SCHEDULER_FIELDS = [
    "session", "run", "seq", "policy", "robot", "t_gen_ns", "t_selected_ns",
    "t_tx_ns", "t_rx_ns", "deferral_ns", "channel", "rssi_dbm", "snr_db", "payload_hex",
]
VICON_FIELDS = ["timestamp_ns", "x", "y", "z", "roll_rad", "pitch_rad", "yaw_rad", "vx", "vy", "vz"]


def raw_files(root: Path) -> list[Path]:
    return sorted(p for p in (root / "hardware" / "raw").rglob("*") if p.is_file())


def session_for(path: Path) -> str:
    return next((part for part in path.parts if part in POLICIES), "support")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def inventory(root: Path) -> list[dict[str, Any]]:
    base = root / "hardware" / "raw"
    rows = []
    sums = []
    for path in raw_files(root):
        session = session_for(path)
        digest = sha256(path)
        rel = path.relative_to(base).as_posix()
        rows.append({
            "relative_path": rel, "filename": path.name, "session": session,
            "policy": POLICIES.get(session, ""), "robot": "limo01" if "limo01" in path.name else
            ("limo02" if "limo02" in path.name else ""), "file_type": path.suffix.lstrip("."),
            "size_bytes": path.stat().st_size, "sha256": digest, "validation_status": "VALID",
        })
        sums.append(f"{digest} *raw/{rel}\n")
    write_csv(root / "hardware" / "raw_file_inventory.csv", list(rows[0]), rows)
    (root / "hardware" / "SHA256SUMS.txt").write_text("".join(sums), encoding="utf-8")
    return rows


def validate_scheduler(path: Path) -> dict[str, Any]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or any(field not in reader.fieldnames for field in SCHEDULER_FIELDS):
            return {"path": str(path), "status": "INVALID_SCHEMA", "records": 0}
        records, prior = 0, None
        runs: set[str] = set()
        for row in reader:
            records += 1
            try:
                seq = int(row["seq"])
                generated, selected = int(row["t_gen_ns"]), int(row["t_selected_ns"])
                if selected == 0:  # never selected (dropped, rejected or pending): no deferral exists
                    if row["deferral_ns"] != "":
                        raise ValueError("deferral recorded for an unselected candidate")
                elif selected < generated or int(row["deferral_ns"]) != selected - generated or seq < 0:
                    raise ValueError("inconsistent timestamps")
                current = (int(row["run"]), seq)
                if prior is not None and current <= prior:
                    raise ValueError("non-monotonic run/sequence")
                prior = current
                runs.add(row["run"])
            except (ValueError, TypeError):
                return {"path": str(path), "status": "INVALID_RECORD", "records": records}
    return {"path": str(path), "status": "VALID", "records": records, "runs": len(runs)}


def db3_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    inventories, topics, sessions = [], [], []
    for db in sorted((root / "hardware" / "raw").rglob("*.db3")):
        session, policy = session_for(db), POLICIES[session_for(db)]
        connection = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        topic_rows = connection.execute(
            """SELECT t.id,t.name,t.type,COUNT(m.id),MIN(m.timestamp),MAX(m.timestamp),
                      SUM(CASE WHEN m.timestamp < previous_timestamp THEN 1 ELSE 0 END)
               FROM topics t LEFT JOIN (
                    SELECT *, LAG(timestamp) OVER (PARTITION BY topic_id ORDER BY id) AS previous_timestamp
                    FROM messages
               ) m ON m.topic_id=t.id GROUP BY t.id,t.name,t.type"""
        ).fetchall()
        total = sum(row[3] for row in topic_rows)
        inventories.append({"session": session, "policy": policy, "relative_path": db.relative_to(root).as_posix(),
                            "sqlite_integrity": integrity, "message_count": total, "status": "VALID" if integrity == "ok" else "INVALID"})
        starts, ends = [], []
        for topic_id, name, message_type, count, start, end, nonmonotonic in topic_rows:
            duration = (end - start) / 1e9 if count and end > start else 0.0
            digest = hashlib.sha256()
            previous_stream = None
            duplicate_streams = 0
            for timestamp, data in connection.execute(
                "SELECT timestamp,data FROM messages WHERE topic_id=? ORDER BY id", (topic_id,)
            ):
                logical = timestamp.to_bytes(8, "big", signed=False) + data
                digest.update(logical)
                duplicate_streams += logical == previous_stream
                previous_stream = logical
            topics.append({"session": session, "policy": policy, "topic": name, "message_type": message_type,
                           "message_count": count, "first_timestamp_ns": start or "", "last_timestamp_ns": end or "",
                           "duration_s": duration, "frequency_hz": count / duration if duration else "",
                           "nonmonotonic_count": nonmonotonic or 0, "duplicate_logical_streams": duplicate_streams,
                           "logical_hash": digest.hexdigest()})
            if start is not None: starts.append(start); ends.append(end)
        sessions.append({"session": session, "policy": policy, "message_count": total,
                         "first_timestamp_ns": min(starts), "last_timestamp_ns": max(ends),
                         "duration_s": (max(ends) - min(starts)) / 1e9, "status": "VALID" if integrity == "ok" else "INVALID"})
        connection.close()
    return inventories, topics, sessions


def mcap_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Read MCAP records and derive per-topic evidence without decoding ROS CDR."""
    from mcap.reader import make_reader

    inventories, topics, sessions = [], [], []
    for path in sorted((root / "hardware" / "raw").rglob("*.mcap")):
        session, policy = session_for(path), POLICIES[session_for(path)]
        state: dict[str, dict[str, Any]] = {}
        with path.open("rb") as handle:
            reader = make_reader(handle, validate_crcs=True)
            for _, channel, message in reader.iter_messages():
                value = state.setdefault(channel.topic, {"type": channel.message_encoding, "count": 0,
                    "start": message.log_time, "end": message.log_time, "previous": None,
                    "duplicates": 0, "nonmonotonic": 0, "hash": hashlib.sha256()})
                logical = message.log_time.to_bytes(8, "big", signed=False) + message.data
                value["nonmonotonic"] += message.log_time < value["end"]
                value["duplicates"] += logical == value["previous"]
                value["previous"] = logical; value["count"] += 1
                value["start"] = min(value["start"], message.log_time); value["end"] = max(value["end"], message.log_time)
                value["hash"].update(logical)
        starts, ends = [], []
        for topic, value in sorted(state.items()):
            duration = (value["end"] - value["start"]) / 1e9
            topics.append({"session": session, "policy": policy, "topic": topic, "message_type": value["type"],
                           "message_count": value["count"], "first_timestamp_ns": value["start"],
                           "last_timestamp_ns": value["end"], "duration_s": duration,
                           "frequency_hz": value["count"] / duration if duration else "",
                           "nonmonotonic_count": value["nonmonotonic"], "duplicate_logical_streams": value["duplicates"],
                           "logical_hash": value["hash"].hexdigest()})
            starts.append(value["start"]); ends.append(value["end"])
        total = sum(v["count"] for v in state.values())
        inventories.append({"session": session, "policy": policy, "relative_path": path.relative_to(root).as_posix(),
                            "message_count": total, "status": "VALID"})
        sessions.append({"session": session, "policy": policy, "message_count": total, "first_timestamp_ns": min(starts),
                         "last_timestamp_ns": max(ends), "duration_s": (max(ends) - min(starts)) / 1e9, "status": "VALID"})
    return inventories, topics, sessions


def vicon_rows(root: Path) -> list[dict[str, Any]]:
    output = []
    for path in sorted((root / "hardware" / "raw").rglob("vicon_*.csv")):
        session = session_for(path)
        robot = "LIMO-01" if "limo01" in path.name else "LIMO-02"
        count, previous, duplicates, nonmonotonic = 0, None, 0, 0
        mins = [math.inf] * 6; maxs = [-math.inf] * 6
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            valid_schema = reader.fieldnames is not None and all(name in reader.fieldnames for name in VICON_FIELDS)
            for row in reader:
                count += 1; timestamp = int(row["timestamp_ns"])
                if previous is not None:
                    duplicates += timestamp == previous; nonmonotonic += timestamp < previous
                previous = timestamp
                for index, field in enumerate(("x", "y", "z", "roll_rad", "pitch_rad", "yaw_rad")):
                    value = float(row[field]); mins[index] = min(mins[index], value); maxs[index] = max(maxs[index], value)
        first = None
        with path.open(newline="", encoding="utf-8") as handle:
            first = next(csv.DictReader(handle))["timestamp_ns"]
        duration = (int(previous) - int(first)) / 1e9 if count > 1 else 0.0
        output.append({"session": session, "policy": POLICIES[session], "robot": robot, "samples": count,
                       "duration_s": duration, "frequency_hz": (count - 1) / duration if duration else "",
                       "nonmonotonic_timestamps": nonmonotonic, "duplicate_timestamps": duplicates,
                       "position_min_m": min(mins[:3]), "position_max_m": max(maxs[:3]),
                       "orientation_min_rad": min(mins[3:]), "orientation_max_rad": max(maxs[3:]),
                       "status": "VALID" if valid_schema and not nonmonotonic else "INVALID"})
    return output


def quantiles(values: list[float]) -> dict[str, float]:
    values = sorted(values)
    if not values:
        return {key: math.nan for key in ("n", "mean", "std", "median", "min", "max", "p5", "p25", "p75", "p95", "p99")}
    def q(point: float) -> float:
        index = (len(values) - 1) * point; low = int(index); high = min(low + 1, len(values) - 1)
        return values[low] + (values[high] - values[low]) * (index - low)
    return {"n": len(values), "mean": statistics.fmean(values), "std": statistics.stdev(values) if len(values) > 1 else 0.0,
            "median": q(.5), "min": values[0], "max": values[-1], "p5": q(.05), "p25": q(.25),
            "p75": q(.75), "p95": q(.95), "p99": q(.99)}


def lora_airtime_s(payload: int, sf: int = 7, bandwidth_hz: int = 125000, cr: int = 5) -> float:
    symbol = 2 ** sf / bandwidth_hz
    payload_symbols = 8 + max(math.ceil((8 * payload - 4 * sf + 44) / (4 * sf)) * cr, 0)
    return (8 + 4.25 + payload_symbols) * symbol


def duty_cycle(root: Path) -> float:
    import yaml
    with (root / "config" / "lora.yaml").open(encoding="utf-8") as handle:
        return float(yaml.safe_load(handle)["regulatory"]["duty_cycle"])


def physical_analysis(root: Path) -> None:
    output = root / "paper_results" / "physical"; output.mkdir(parents=True, exist_ok=True)
    delta = duty_cycle(root)
    packet_rows, run_rows, radio_rows = [], [], []
    run_data: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted((root / "hardware" / "raw").rglob("bacs_scheduler_*.csv")):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                generated, selected, tx, rx = (int(row[x]) for x in ("t_gen_ns", "t_selected_ns", "t_tx_ns", "t_rx_ns"))
                selected_row = {**row, "deferral_s": (selected - generated) / 1e9 if selected else "",
                                "channel_delay_s": (rx - tx) / 1e9 if tx and rx else "",
                                "packet_age_s": (rx - generated) / 1e9 if rx else "",
                                "airtime_s": lora_airtime_s(int(row.get("payload_bytes", 52))),
                                "measurement_status": "MEASURED" if tx and rx else "NOT_RECORDED"}
                packet_rows.append(selected_row); run_data[(row["policy"], row["run"])].append(selected_row)
    vicon_by_session_robot: dict[tuple[str, str], list[int]] = {}
    for path in (root / "hardware" / "raw").rglob("vicon_*.csv"):
        robot = "limo01" if "limo01" in path.name else "limo02"
        with path.open(newline="", encoding="utf-8") as handle:
            vicon_by_session_robot[(session_for(path), robot)] = [int(row["timestamp_ns"]) for row in csv.DictReader(handle)]
    bag_paths = {session_for(path): path for path in (root / "hardware" / "raw").rglob("*.db3")}
    for (policy, run), records in sorted(run_data.items()):
        sent = [row for row in records if row["sent"] == "1"]
        heard = [row for row in sent if row["rssi_dbm"] != ""]  # RSSI/SNR exist only for received packets
        start, end = min(int(r["t_gen_ns"]) for r in records), max(int(r["t_gen_ns"]) for r in records)
        duration = (end - start) / 1e9
        defer = [float(r["deferral_s"]) for r in records if r["deferral_s"] != ""]
        session = records[0]["session"]
        bag_records: int | str = ""
        if session in bag_paths:
            with sqlite3.connect(f"file:{bag_paths[session].as_posix()}?mode=ro", uri=True) as bag:
                bag_records = bag.execute("SELECT COUNT(*) FROM messages WHERE timestamp BETWEEN ? AND ?", (start, end)).fetchone()[0]
        run_rows.append({"policy": policy, "run": run, "start_timestamp": start, "end_timestamp": end,
                         "scheduler_records": len(records),
                         "vicon_records_limo01": sum(start <= ts <= end for ts in vicon_by_session_robot.get((session, "limo01"), [])),
                         "vicon_records_limo02": sum(start <= ts <= end for ts in vicon_by_session_robot.get((session, "limo02"), [])),
                         "bag_records": bag_records, "duration_s": duration,
                         "transmitted_constraints": len(sent), "generated_constraints": len(records),
                         "deferral_mean_s": statistics.fmean(defer) if defer else "", "status": "SEGMENTED_FROM_LOGGED_RUN"})
        airtime = sum(float(r["airtime_s"]) for r in sent)
        transmitters = len({r["robot"] for r in records})
        radio_rows.append({"policy": policy, "run": run, "packets_generated_per_run": len(records),
                           "packets_sent_per_run": len(sent),
                           "payload_bytes_mean": statistics.fmean([float(r["payload_bytes"]) for r in sent]) if sent else "",
                           "packets_received_per_run": len(heard),
                           "rssi_dbm_mean": statistics.fmean([float(r["rssi_dbm"]) for r in heard]) if heard else "",
                           "snr_db_mean": statistics.fmean([float(r["snr_db"]) for r in heard]) if heard else "",
                           "airtime_s": airtime, "transmitters": transmitters,
                           "airtime_fraction_of_run": airtime / duration if duration else "",
                           "airtime_fraction_of_duty_budget": airtime / (delta * duration * transmitters) if duration else ""})
    write_csv(output / "timing_per_packet.csv", list(packet_rows[0]), packet_rows)
    write_csv(output / "timing_per_run.csv", list(run_rows[0]), run_rows)
    write_csv(output / "run_segmentation.csv", list(run_rows[0]), run_rows)
    timing_summary = []
    for policy in sorted({r["policy"] for r in packet_rows}):
        for metric, sent_only in (("deferral_s", False), ("deferral_s", True), ("channel_delay_s", True), ("packet_age_s", True)):
            values = [float(r[metric]) for r in packet_rows if r["policy"] == policy and r[metric] != ""
                      and (not sent_only or r["sent"] == "1")]
            name = "deferral_sent_s" if metric == "deferral_s" and sent_only else metric
            timing_summary.append({"policy": policy, "metric": name, **quantiles(values), "status": "COMPUTED" if values else "NOT_RECORDED"})
    write_csv(output / "timing_summary.csv", list(timing_summary[0]), timing_summary)
    write_csv(output / "radio_per_packet.csv", list(packet_rows[0]), packet_rows)
    write_csv(output / "radio_per_run.csv", list(radio_rows[0]), radio_rows)
    radio_summary = []
    for policy in sorted({r["policy"] for r in radio_rows}):
        for metric in ("packets_generated_per_run", "packets_sent_per_run", "packets_received_per_run", "rssi_dbm_mean", "snr_db_mean",
                       "airtime_fraction_of_run", "airtime_fraction_of_duty_budget"):
            values = [float(r[metric]) for r in radio_rows if r["policy"] == policy and r[metric] != ""]
            radio_summary.append({"policy": policy, "metric": metric, **quantiles(values), "status": "COMPUTED"})
    write_csv(output / "radio_summary.csv", list(radio_summary[0]), radio_summary)
    counts = []
    for policy in sorted({r["policy"] for r in radio_rows}):
        runs = [r for r in radio_rows if r["policy"] == policy]
        counts.append({"policy": policy, "runs": len(runs),
                       "packets_generated_per_session": sum(r["packets_generated_per_run"] for r in runs),
                       "packets_sent_per_session": sum(r["packets_sent_per_run"] for r in runs),
                       "packets_received_per_session": sum(r["packets_received_per_run"] for r in runs),
                       "packets_generated_per_run_median": statistics.median(r["packets_generated_per_run"] for r in runs),
                       "packets_sent_per_run_median": statistics.median(r["packets_sent_per_run"] for r in runs)})
    write_csv(output / "session_counts.csv", list(counts[0]), counts)
    fused = sorted((output / "fused").glob("fused_*.csv"))
    if fused:
        from analysis.physical.map_alignment import run as map_alignment
        map_alignment(fused, output / "run_segmentation.csv", output)
        return
    map_rows = [{"policy": policy, "metric": "map_alignment_rmse_m", "status": "NOT_COMPUTABLE",
                 "reason": "No paper_results/physical/fused/fused_*.csv; log them with scripts/repro/log_fused_poses.py."}
                for policy in ("FIFO", "BACS", "BACS+")]
    write_csv(output / "map_alignment_per_run.csv", list(map_rows[0]), map_rows)
    write_csv(output / "map_alignment_summary.csv", list(map_rows[0]), map_rows)


def validate_all(root: Path) -> None:
    inventory(root)
    validation = root / "hardware" / "validation"; validation.mkdir(parents=True, exist_ok=True)
    scheduler = [validate_scheduler(p) for p in sorted((root / "hardware" / "raw").rglob("bacs_scheduler_*.csv"))]
    write_csv(validation / "scheduler_validation.csv", list(scheduler[0]), scheduler)
    db_inventory, db_topics, db_sessions = db3_rows(root)
    write_csv(validation / "db3_inventory.csv", list(db_inventory[0]), db_inventory)
    write_csv(validation / "db3_topics.csv", list(db_topics[0]), db_topics)
    write_csv(validation / "db3_sessions.csv", list(db_sessions[0]), db_sessions)
    mcap_inventory, mcap_topics, mcap_sessions = mcap_rows(root)
    write_csv(validation / "mcap_inventory.csv", list(mcap_inventory[0]), mcap_inventory)
    write_csv(validation / "mcap_topics.csv", list(mcap_topics[0]), mcap_topics)
    write_csv(validation / "mcap_sessions.csv", list(mcap_sessions[0]), mcap_sessions)
    mcap_index = {(row["session"], row["topic"]): row for row in mcap_topics}
    equivalence = []
    for db in db_topics:
        mcap = mcap_index.get((db["session"], db["topic"]))
        equivalent = bool(mcap) and all(db[key] == mcap[key] for key in
                                        ("message_count", "first_timestamp_ns", "last_timestamp_ns", "logical_hash"))
        equivalence.append({"session": db["session"], "policy": db["policy"], "topic": db["topic"],
                            "db3_message_count": db["message_count"], "mcap_message_count": mcap["message_count"] if mcap else "",
                            "db3_start": db["first_timestamp_ns"], "mcap_start": mcap["first_timestamp_ns"] if mcap else "",
                            "db3_end": db["last_timestamp_ns"], "mcap_end": mcap["last_timestamp_ns"] if mcap else "",
                            "db3_logical_hash": db["logical_hash"], "mcap_logical_hash": mcap["logical_hash"] if mcap else "",
                            "equivalent": equivalent})
    write_csv(validation / "db3_mcap_equivalence.csv", list(equivalence[0]), equivalence)
    vic = vicon_rows(root); write_csv(validation / "vicon_summary.csv", list(vic[0]), vic)
    db_index = {(row["session"], row["topic"]): row for row in db_topics}
    comparisons = []
    for row in vic:
        topic = f"/vicon/{row['robot'].lower().replace('-', '')}/pose"
        bag = db_index.get((row["session"], topic))
        comparisons.append({"session": row["session"], "robot": row["robot"], "csv_samples": row["samples"],
                            "bag_messages": bag["message_count"] if bag else "", "csv_frequency_hz": row["frequency_hz"],
                            "bag_frequency_hz": bag["frequency_hz"] if bag else "", "status":
                            "COUNT_MATCH" if bag and row["samples"] == bag["message_count"] else "COUNT_DIFFERENT",
                            "reason": "Counts/rates compared without decoding CDR pose payloads."})
    write_csv(validation / "vicon_csv_vs_bag.csv", list(comparisons[0]), comparisons)
