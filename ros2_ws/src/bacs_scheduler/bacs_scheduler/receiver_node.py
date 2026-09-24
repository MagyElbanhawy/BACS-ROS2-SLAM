"""Server-side RYLR998 receiver: logs every +RCV with the module-reported RSSI/SNR.

    ros2 run bacs_scheduler bacs_receiver --ros-args -p session:=HWS-101 -p run:=1 \
        -p port:=/dev/ttyUSB0 -p address:=100

Publishes decoded constraints as ``std_msgs/String`` JSON on ``/bacs/received``
for the fusion server, and writes ``received_server.csv`` plus the raw serial
transcript under ``log_dir/<session>/run_XX/``.
"""

from __future__ import annotations

import csv
import json
import time

import rclpy
import serial
from rclpy.node import Node
from std_msgs.msg import String

from .node_common import clock_snapshot, configure_radio, run_dir
from .receiver_core import RECEIVED_FIELDS, received_row
from .rylr998 import Received, Rylr998Link, TraceWriter


class ReceiverNode(Node):
    def __init__(self) -> None:
        super().__init__("bacs_receiver")
        p = lambda name, default: self.declare_parameter(name, default).value  # noqa: E731
        self.session, self.run = p("session", ""), int(p("run", 0))
        if not self.session or self.run <= 0:
            raise SystemExit("Parameters 'session' and 'run' (>0) are required.")
        self.robots = list(p("robots", ["limo01", "limo02"]))
        self.address_to_robot = dict(zip([int(a) for a in p("robot_addresses", [1, 2])], self.robots))
        self.out = run_dir(p("log_dir", "~/bacs_hw_logs"), self.session, self.run)
        clock_snapshot(self.out / "clock_server_start.txt")

        self.log = (self.out / "received_server.csv").open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.log, fieldnames=RECEIVED_FIELDS, lineterminator="\n")
        self.writer.writeheader()
        self.serial_log = (self.out / "serial_server.csv").open("w", newline="", encoding="utf-8")
        self.publisher = self.create_publisher(String, "/bacs/received", 100)
        port = serial.Serial(p("port", "/dev/ttyUSB0"), int(p("baud", 115200)), timeout=0.2)
        self.link = Rylr998Link(port, TraceWriter(self.serial_log), on_receive=self.on_receive,
                                clock_ns=time.time_ns)
        configure_radio(self.link, self.out / "radio_config_server.json", int(p("address", 100)),
                        int(p("network_id", 18)), int(p("bw_code", 7)), int(p("preamble", 8)), int(p("power_dbm", 14)))
        self.get_logger().info(f"Receiver logging to {self.out}")

    def on_receive(self, t_ns: int, packet: Received) -> None:
        row = received_row(self.session, self.run, t_ns, packet, self.address_to_robot, self.robots)
        self.writer.writerow(row); self.log.flush()
        if row["decode_status"] == "OK":
            self.publisher.publish(String(data=json.dumps(row)))

    def close(self) -> None:
        self.link.close()
        clock_snapshot(self.out / "clock_server_end.txt")
        self.log.close(); self.serial_log.close()


def main() -> None:
    rclpy.init()
    node = ReceiverNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close(); node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
