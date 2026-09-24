"""Server-side receive-log row construction (ROS-free)."""

from __future__ import annotations

from .rylr998 import ConstraintPayload, Received

RECEIVED_FIELDS = ["session", "run", "t_rcv_ns", "address", "robot", "seq", "robot_i", "robot_j", "gen_ms",
                   "rssi_dbm", "snr_db", "length", "decode_status"]


def received_row(session: str, run: int, t_ns: int, packet: Received, address_to_robot: dict[int, str],
                 robots: list[str]) -> dict:
    row = {"session": session, "run": run, "t_rcv_ns": t_ns, "address": packet.address,
           "robot": address_to_robot.get(packet.address, ""), "rssi_dbm": packet.rssi_dbm,
           "snr_db": packet.snr_db, "length": packet.length}
    try:
        payload = ConstraintPayload.decode(packet.data)
        row.update({"seq": payload.seq, "robot_i": robots[payload.robot_i], "robot_j": robots[payload.robot_j],
                    "gen_ms": payload.gen_ms, "decode_status": "OK"})
    except (ValueError, IndexError) as error:
        row.update({"decode_status": f"DECODE_ERROR: {error}"})
    return row
