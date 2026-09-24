"""Robot-side BACS sender: candidates in, RYLR998 packets out, every event logged.

    ros2 run bacs_scheduler bacs_sender --ros-args -p session:=HWS-101 -p run:=1 \
        -p policy:=BACS+ -p robot:=limo01 -p address:=1 -p port:=/dev/ttyUSB0

Input: ``std_msgs/String`` JSON candidates on ``candidate_topic`` (fields in
docs/HARDWARE_EXPERIMENT_V2.md). Output: ``/bacs/scheduler`` JSON events (for the
bag) and, under ``log_dir/<session>/run_XX/``, the candidate log, the raw serial
transcript, the radio configuration read-back and clock snapshots.
"""

from __future__ import annotations

import json
import time

import rclpy
import serial
from rclpy.node import Node
from std_msgs.msg import String

from .node_common import clock_snapshot, configure_radio, run_dir
from .rylr998 import Rylr998Link, TraceWriter
from .scheduler import DutyCycleBudget, Scheduler
from .sender_core import SenderCore


class SenderNode(Node):
    def __init__(self) -> None:
        super().__init__("bacs_sender")
        p = lambda name, default: self.declare_parameter(name, default).value  # noqa: E731
        session, run, policy, robot = p("session", ""), int(p("run", 0)), p("policy", "BACS+"), p("robot", "")
        if not session or not robot or run <= 0:
            raise SystemExit("Parameters 'session', 'robot' and 'run' (>0) are required.")
        self.out = run_dir(p("log_dir", "~/bacs_hw_logs"), session, run)
        clock_snapshot(self.out / f"clock_{robot}_start.txt")

        self.serial_log = (self.out / f"serial_{robot}.csv").open("w", newline="", encoding="utf-8")
        port = serial.Serial(p("port", "/dev/ttyUSB0"), int(p("baud", 115200)), timeout=0.2)
        self.link = Rylr998Link(port, TraceWriter(self.serial_log))
        configure_radio(self.link, self.out / f"radio_config_{robot}.json", int(p("address", 1)),
                        int(p("network_id", 18)), int(p("bw_code", 7)), int(p("preamble", 8)), int(p("power_dbm", 14)))

        scheduler = Scheduler(policy, DutyCycleBudget(float(p("window_s", 60.0)), float(p("duty_cycle", 0.01))),
                              trust_threshold=float(p("trust_threshold", 0.5)),
                              observability_weight=float(p("observability_weight", 0.30)),
                              observability_reference=int(p("observability_reference", 6)),
                              defer_half_life_s=float(p("defer_half_life_s", 60.0)))
        self.candidate_log = (self.out / f"candidates_{robot}.csv").open("w", newline="", encoding="utf-8")
        self.core = SenderCore(session=session, run=run, policy=policy, robot=robot,
                               robots=list(p("robots", ["limo01", "limo02"])), radio=self.link,
                               destination=int(p("server_address", 100)), log=self.candidate_log,
                               clock_ns=time.time_ns, scheduler=scheduler,
                               max_queue_age_s=float(p("max_queue_age_s", 600.0)))
        self.robot = robot
        self.events = self.create_publisher(String, "/bacs/scheduler", 100)
        self.create_subscription(String, p("candidate_topic", "/bacs/candidates"), self.on_candidate, 1000)
        self.create_timer(1.0 / float(p("tick_hz", 5.0)), self.on_tick)
        self.get_logger().info(f"{policy} sender for {robot}, logging to {self.out}")

    def on_candidate(self, msg: String) -> None:
        candidate = json.loads(msg.data)
        if candidate.get("robot_i") != self.robot:  # each robot transmits only its own candidates
            return
        self.core.enqueue(candidate)

    def on_tick(self) -> None:
        status = self.core.tick()
        if status is not None:
            self.events.publish(String(data=json.dumps({"robot": self.robot, "status": status,
                                                         "queue": len(self.core.queue)})))

    def close(self) -> None:
        self.core.close(); self.link.close()
        clock_snapshot(self.out / f"clock_{self.robot}_end.txt")
        self.candidate_log.close(); self.serial_log.close()


def main() -> None:
    rclpy.init()
    node = SenderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close(); node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
