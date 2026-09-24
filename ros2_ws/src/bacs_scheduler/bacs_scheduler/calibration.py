"""Summarise the +OK timing calibration (what does the RYLR998 ``+OK`` mark?)."""

from __future__ import annotations

import statistics
from typing import Any

CALIBRATION_FIELDS = ["i", "t_cmd_ns", "t_ok_ns", "response", "t_rcv_ns", "rssi_dbm", "snr_db"]


def uart_time_s(line_chars: int, baud: int = 115200) -> float:
    """Time to clock ``line_chars`` + CRLF through the UART at 8N1 (10 bits per char)."""
    return (line_chars + 2) * 10 / baud


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {}
    q = statistics.quantiles(values, n=20, method="inclusive") if len(values) > 1 else [values[0]] * 19
    return {"n": len(values), "median_s": statistics.median(values), "p5_s": q[0], "p95_s": q[-1],
            "min_s": min(values), "max_s": max(values)}


def summarise(rows: list[dict[str, Any]], airtime_s: float, command_chars: int, baud: int = 115200) -> dict[str, Any]:
    ok = [r for r in rows if r["response"] == "+OK"]
    heard = [r for r in ok if r["t_rcv_ns"] not in ("", None)]
    to_ok = [(int(r["t_ok_ns"]) - int(r["t_cmd_ns"])) / 1e9 for r in ok]
    to_rcv = [(int(r["t_rcv_ns"]) - int(r["t_cmd_ns"])) / 1e9 for r in heard]
    ok_to_rcv = [(int(r["t_rcv_ns"]) - int(r["t_ok_ns"])) / 1e9 for r in heard]
    median_ok = statistics.median(to_ok) if to_ok else float("nan")
    if not to_ok:
        verdict = "NO_OK_REPLIES"
    elif median_ok >= 0.8 * airtime_s:
        verdict = "OK_AFTER_TRANSMISSION"   # +OK comes once the packet has left the antenna
    elif median_ok <= 0.2 * airtime_s:
        verdict = "OK_ON_ACCEPT"            # +OK only acknowledges the UART command
    else:
        verdict = "AMBIGUOUS"
    return {"packets": len(rows), "ok": len(ok), "received": len(heard),
            "delivery_ratio": len(heard) / len(ok) if ok else float("nan"),
            "airtime_s": airtime_s, "uart_command_s": uart_time_s(command_chars, baud),
            "cmd_to_ok": _stats(to_ok), "cmd_to_rcv": _stats(to_rcv), "ok_to_rcv": _stats(ok_to_rcv),
            "verdict": verdict}
