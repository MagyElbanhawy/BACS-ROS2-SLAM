#!/usr/bin/env python3
"""Configure one RYLR998 module and verify its read-back (no ROS needed).

    python3 scripts/hw/rylr998_setup.py --port /dev/ttyUSB0 --address 1     # LIMO-01
    python3 scripts/hw/rylr998_setup.py --port /dev/ttyUSB0 --address 2     # LIMO-02
    python3 scripts/hw/rylr998_setup.py --port /dev/ttyUSB0 --address 100   # server

Sets SF7 / 125 kHz (BW code 7) / CR 4/5 / preamble 8 at 868 MHz, then reads every
setting back. Exit code 0 only if the module reports exactly those settings.
The full command/reply list is written to --out (JSON) for the dataset.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ros2_ws.src.bacs_scheduler.bacs_scheduler.rylr998 import (  # noqa: E402
    Rylr998Link, configuration_commands, expected_readback, readback_mismatches)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--address", type=int, required=True)
    parser.add_argument("--network-id", type=int, default=18)
    parser.add_argument("--power-dbm", type=int, default=14)
    parser.add_argument("--out", type=Path, help="JSON file for the command/reply record")
    args = parser.parse_args()

    import serial
    link = Rylr998Link(serial.Serial(args.port, args.baud, timeout=0.2))
    settings = dict(address=args.address, network_id=args.network_id, power_dbm=args.power_dbm)
    replies = link.configure(configuration_commands(**settings))
    link.close()
    problems = readback_mismatches(replies, expected_readback(**settings))
    for command, reply in replies:
        print(f"{command:<32} {reply}")
    if args.out:
        args.out.write_text(json.dumps({"replies": [{"command": c, "response": r} for c, r in replies],
                                        "problems": problems}, indent=2), encoding="utf-8")
    print("PASS" if not problems else "FAIL:\n  " + "\n  ".join(problems))
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
