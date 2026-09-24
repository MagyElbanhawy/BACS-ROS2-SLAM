"""Join robot-side candidate logs with the server-side receive log into one scheduler log.

Output uses the columns ``pipeline.py`` reads. Fields are filled only from logged
events: ``t_selected_ns``/``deferral_ns`` only for candidates that were selected,
``t_tx_ns`` = the ``AT+SEND`` write time, ``t_rx_ns``/RSSI/SNR only for packets the
server actually received. Anything that did not happen stays 0 or blank.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

JOINED_FIELDS = ["session", "run", "seq", "policy", "robot", "t_gen_ns", "t_selected_ns", "t_tx_ns", "t_ok_ns",
                 "t_rx_ns", "deferral_ns", "channel", "rssi_dbm", "snr_db", "payload_hex", "payload_bytes",
                 "sent", "received", "status", "radio_response", "predicted_trust", "information_score",
                 "pair_constraints"]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def join_run(run_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    candidates = [row for path in sorted(run_dir.glob("candidates_*.csv")) for row in _read(path)]
    received_path = run_dir / "received_server.csv"
    received_rows = _read(received_path) if received_path.exists() else []
    received: dict[tuple[str, str], dict[str, str]] = {}
    duplicates = undecodable = 0
    for row in received_rows:
        if row["decode_status"] != "OK":
            undecodable += 1
            continue
        key = (row["robot"], row["seq"])
        if key in received:
            duplicates += 1  # keep the first reception
            continue
        received[key] = row
    joined, matched = [], set()
    for c in candidates:
        rx = received.get((c["robot"], c["seq"]))
        sent = c["status"] == "SENT"
        selected = c.get("t_selected_ns", "") != ""
        if rx is not None:
            matched.add((c["robot"], c["seq"]))
        joined.append({
            "session": c["session"], "run": c["run"], "seq": c["seq"], "policy": c["policy"], "robot": c["robot"],
            "t_gen_ns": c["t_gen_ns"], "t_selected_ns": c["t_selected_ns"] if selected else 0,
            "t_tx_ns": c["t_cmd_ns"] if sent else 0, "t_ok_ns": c.get("t_ok_ns", ""),
            "t_rx_ns": rx["t_rcv_ns"] if rx else 0,
            "deferral_ns": int(c["t_selected_ns"]) - int(c["t_gen_ns"]) if selected else "",
            "channel": "", "rssi_dbm": rx["rssi_dbm"] if rx else "", "snr_db": rx["snr_db"] if rx else "",
            "payload_hex": "", "payload_bytes": c["payload_bytes"], "sent": int(sent), "received": int(rx is not None),
            "status": c["status"], "radio_response": c.get("radio_response", ""),
            "predicted_trust": c["predicted_trust"], "information_score": c["information_score"],
            "pair_constraints": c["pair_constraints"],
        })
    joined.sort(key=lambda r: (int(r["t_gen_ns"]), r["robot"], int(r["seq"])))
    report = {"candidates": len(candidates), "sent": sum(r["sent"] for r in joined),
              "received": len(matched), "received_unmatched": len(set(received) - matched),
              "received_duplicates": duplicates, "received_undecodable": undecodable}
    return joined, report


def join_session(session_dir: Path, out: Path) -> list[dict[str, Any]]:
    """Join every ``run_XX`` of a session into ``out``; returns one report row per run."""
    rows, reports = [], []
    for run_dir in sorted(session_dir.glob("run_*")):
        joined, report = join_run(run_dir)
        rows += joined
        reports.append({"run": run_dir.name, **report})
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=JOINED_FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    return reports
