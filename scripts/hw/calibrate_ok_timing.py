#!/usr/bin/env python3
"""Calibrate what the RYLR998 ``+OK`` reply marks, on a single clock.

Connect TWO modules to ONE computer (e.g. /dev/ttyUSB0 = robot side, /dev/ttyUSB1 =
server side), about 1 m apart, then:

    python3 scripts/hw/calibrate_ok_timing.py --tx-port /dev/ttyUSB0 --rx-port /dev/ttyUSB1 \
        --count 100 --out calibration/

Each packet is a real 52-byte payload, as in the experiment. Packets are spaced
--interval seconds apart (default 10.5 s keeps one transmitter under the 1 % duty
cycle: 0.1027 s / 10.5 s = 0.98 %), so 100 packets take about 18 minutes.

Writes calibration.csv (one row per packet), serial_tx.csv / serial_rx.csv (raw
transcripts), radio_config_*.json and summary.json, and prints the verdict:

  OK_AFTER_TRANSMISSION  +OK arrives >= 80 % of the time-on-air after the command
  OK_ON_ACCEPT           +OK arrives within 20 % of the time-on-air (command accepted only)
  AMBIGUOUS              anything in between -- report the distribution as measured
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ros2_ws.src.bacs_scheduler.bacs_scheduler.calibration import CALIBRATION_FIELDS, summarise  # noqa: E402
from ros2_ws.src.bacs_scheduler.bacs_scheduler.rylr998 import (  # noqa: E402
    ON_AIR_BYTES, ConstraintPayload, Rylr998Link, TraceWriter, configuration_commands, expected_readback,
    readback_mismatches, send_command)
from ros2_ws.src.bacs_scheduler.bacs_scheduler.scheduler import lora_airtime_s  # noqa: E402

TX_ADDRESS, RX_ADDRESS = 1, 100


def configure(link: Rylr998Link, address: int, out: Path, power_dbm: int) -> None:
    settings = dict(address=address, network_id=18, power_dbm=power_dbm)
    replies = link.configure(configuration_commands(**settings))
    problems = readback_mismatches(replies, expected_readback(**settings))
    out.write_text(json.dumps({"replies": [{"command": c, "response": r} for c, r in replies],
                               "problems": problems}, indent=2), encoding="utf-8")
    if problems:
        raise SystemExit(f"module {address} not configured as required: {problems}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tx-port", required=True)
    parser.add_argument("--rx-port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--interval", type=float, default=10.5)
    parser.add_argument("--rx-wait", type=float, default=2.0, help="seconds to wait for +RCV after +OK")
    parser.add_argument("--power-dbm", type=int, default=14)
    parser.add_argument("--out", type=Path, default=Path("calibration"))
    args = parser.parse_args()
    airtime = lora_airtime_s(ON_AIR_BYTES)
    if airtime / args.interval > 0.01:
        raise SystemExit(f"--interval {args.interval} s exceeds the 1 % duty cycle for {airtime:.4f} s packets")

    import serial
    args.out.mkdir(parents=True, exist_ok=True)
    received: dict[int, tuple[int, int, int]] = {}
    arrived = threading.Condition()

    def on_receive(t_ns, packet) -> None:
        seq = ConstraintPayload.decode(packet.data).seq
        with arrived:
            received.setdefault(seq, (t_ns, packet.rssi_dbm, packet.snr_db))
            arrived.notify_all()

    with (args.out / "serial_tx.csv").open("w", newline="") as tx_log, \
         (args.out / "serial_rx.csv").open("w", newline="") as rx_log, \
         (args.out / "calibration.csv").open("w", newline="") as handle:
        tx = Rylr998Link(serial.Serial(args.tx_port, args.baud, timeout=0.2), TraceWriter(tx_log))
        rx = Rylr998Link(serial.Serial(args.rx_port, args.baud, timeout=0.2), TraceWriter(rx_log), on_receive=on_receive)
        configure(tx, TX_ADDRESS, args.out / "radio_config_tx.json", args.power_dbm)
        configure(rx, RX_ADDRESS, args.out / "radio_config_rx.json", args.power_dbm)
        writer = csv.DictWriter(handle, fieldnames=CALIBRATION_FIELDS, lineterminator="\n")
        writer.writeheader()
        rows, command_chars = [], 0
        for i in range(args.count):
            start = time.monotonic()
            line = send_command(RX_ADDRESS, ConstraintPayload(i, 0, 1, 0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 0).encode())
            command_chars = len(line)
            t_cmd, t_ok, response = tx.command(line)
            with arrived:
                arrived.wait_for(lambda: i in received, timeout=args.rx_wait)
                rcv = received.get(i)
            row = {"i": i, "t_cmd_ns": t_cmd, "t_ok_ns": t_ok if t_ok is not None else "", "response": response,
                   "t_rcv_ns": rcv[0] if rcv else "", "rssi_dbm": rcv[1] if rcv else "", "snr_db": rcv[2] if rcv else ""}
            writer.writerow(row); handle.flush(); rows.append(row)
            ok_ms = f"{(t_ok - t_cmd) / 1e6:7.1f}" if t_ok else "   n/a"
            rcv_ms = f"{(rcv[0] - t_cmd) / 1e6:7.1f}" if rcv else "   lost"
            print(f"{i:3d}  {response:<8} cmd->OK {ok_ms} ms   cmd->RCV {rcv_ms} ms")
            time.sleep(max(0.0, args.interval - (time.monotonic() - start)))
        tx.close(); rx.close()

    summary = summarise(rows, airtime, command_chars, args.baud)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
