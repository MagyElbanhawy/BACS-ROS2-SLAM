"""Robot-side candidate generator: keyframe scan matching -> /bacs/candidates.

    ros2 run bacs_scheduler bacs_candidates --ros-args -p session:=HWS-101-FIFO -p run:=1 -p robot:=limo01

Inputs: the robot's own ``scan_topic`` and its local pose from TF
(``local_frame`` -> ``base_frame``, e.g. its own SLAM or odometry frame). Never
Vicon. Side channel (lab Wi-Fi): ``/bacs/kf_desc``, ``/bacs/kf_request`` and
``/bacs/kf_points`` (std_msgs/String JSON); the byte count of every side-channel
message is logged so it can be reported. Output: ``/bacs/candidates``.
Logs under ``log_dir/<session>/run_XX/``: ``candidate_attempts_<robot>.csv``,
``keyframes_<robot>.csv`` and ``sidechannel_<robot>.csv``.
"""

from __future__ import annotations

import csv
import json
import math
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import Buffer, TransformException, TransformListener

from .candidate_generator import CandidateGenerator, GeneratorParams
from .node_common import run_dir
from .place_recognition import scan_to_points


def yaw_of(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class CandidateNode(Node):
    def __init__(self) -> None:
        super().__init__("bacs_candidates")
        p = lambda name, default: self.declare_parameter(name, default).value  # noqa: E731
        session, run, self.robot = p("session", ""), int(p("run", 0)), p("robot", "")
        if not session or not self.robot or run <= 0:
            raise SystemExit("Parameters 'session', 'robot' and 'run' (>0) are required.")
        fmt = lambda text: text.format(robot=self.robot)  # noqa: E731
        self.local_frame, self.base_frame = fmt(p("local_frame", "{robot}/odom")), fmt(p("base_frame", "{robot}/base_link"))
        self.period_s = float(p("keyframe_period_s", 2.0))
        self.min_motion_m = float(p("min_motion_m", 0.05))
        self.min_rotation_rad = math.radians(float(p("min_rotation_deg", 5.0)))
        out = run_dir(p("log_dir", "~/bacs_hw_logs"), session, run)

        self.attempts = (out / f"candidate_attempts_{self.robot}.csv").open("w", newline="", encoding="utf-8")
        self.keyframes = (out / f"keyframes_{self.robot}.csv").open("w", newline="", encoding="utf-8")
        self.sidechannel = (out / f"sidechannel_{self.robot}.csv").open("w", newline="", encoding="utf-8")
        self.kf_writer = csv.writer(self.keyframes, lineterminator="\n")
        self.kf_writer.writerow(["kf", "stamp_ns", "scan_stamp_ns", "x", "y", "yaw", "points"])
        self.side_writer = csv.writer(self.sidechannel, lineterminator="\n")
        self.side_writer.writerow(["t_ns", "direction", "topic", "bytes"])

        params = GeneratorParams(**{k: type(v)(p(k, v)) for k, v in vars(GeneratorParams()).items()})
        self.generator = CandidateGenerator(self.robot, time.time_ns, params, self.attempts)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.latest_scan: LaserScan | None = None
        self.last_pose: tuple[float, float, float] | None = None
        self.next_kf = 0

        self.pub_desc = self.create_publisher(String, "/bacs/kf_desc", 100)
        self.pub_request = self.create_publisher(String, "/bacs/kf_request", 100)
        self.pub_points = self.create_publisher(String, "/bacs/kf_points", 100)
        self.pub_candidates = self.create_publisher(String, "/bacs/candidates", 1000)
        self.pub_keyframes = self.create_publisher(String, "/bacs/keyframes", 1000)
        self.create_subscription(LaserScan, fmt(p("scan_topic", "/scan/{robot}")), self.on_scan, 10)
        self.create_subscription(String, "/bacs/kf_desc", self.on_desc, 1000)
        self.create_subscription(String, "/bacs/kf_request", self.on_request, 1000)
        self.create_subscription(String, "/bacs/kf_points", self.on_points, 1000)
        self.create_timer(self.period_s, self.on_keyframe_timer)
        self.get_logger().info(f"Candidate generator for {self.robot} ({self.local_frame} -> {self.base_frame})")

    # --- side channel with byte accounting ---------------------------------------------------------
    def _send(self, publisher, topic: str, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":"))
        self.side_writer.writerow([time.time_ns(), "tx", topic, len(data.encode())])
        publisher.publish(String(data=data))

    # --- callbacks -----------------------------------------------------------------------------------
    def on_scan(self, msg: LaserScan) -> None:
        self.latest_scan = msg

    def on_keyframe_timer(self) -> None:
        scan = self.latest_scan
        if scan is None:
            return
        try:
            tf = self.tf_buffer.lookup_transform(self.local_frame, self.base_frame, Time())
        except TransformException:
            return
        pose = (tf.transform.translation.x, tf.transform.translation.y, yaw_of(tf.transform.rotation))
        if self.last_pose is not None:
            moved = math.hypot(pose[0] - self.last_pose[0], pose[1] - self.last_pose[1])
            turned = abs(math.atan2(math.sin(pose[2] - self.last_pose[2]), math.cos(pose[2] - self.last_pose[2])))
            if moved < self.min_motion_m and turned < self.min_rotation_rad:
                return
        try:  # scan points into the base frame (the LiDAR sits on the front chassis)
            mount = self.tf_buffer.lookup_transform(self.base_frame, scan.header.frame_id, Time())
        except TransformException:
            return
        self.last_pose = pose
        points = scan_to_points(np.asarray(scan.ranges), scan.angle_min, scan.angle_increment,
                                scan.range_min, scan.range_max)
        c, s = math.cos(yaw_of(mount.transform.rotation)), math.sin(yaw_of(mount.transform.rotation))
        points = points @ np.array([[c, s], [-s, c]]) + (mount.transform.translation.x, mount.transform.translation.y)
        kf, self.next_kf = self.next_kf, self.next_kf + 1
        stamp = time.time_ns()
        scan_stamp = scan.header.stamp.sec * 1_000_000_000 + scan.header.stamp.nanosec
        self.kf_writer.writerow([kf, stamp, scan_stamp, *pose, len(points)])
        self.keyframes.flush()
        self._send(self.pub_keyframes, "/bacs/keyframes",
                   {"robot": self.robot, "kf": kf, "stamp_ns": stamp, "x": pose[0], "y": pose[1], "yaw": pose[2]})
        message, requests, candidates = self.generator.add_own_keyframe(kf, stamp, points)
        self._send(self.pub_desc, "/bacs/kf_desc", message)
        for request in requests:
            self._send(self.pub_request, "/bacs/kf_request", request)
        self._publish(candidates)

    def on_desc(self, msg: String) -> None:
        payload = json.loads(msg.data)
        if payload["robot"] != self.robot:
            self.side_writer.writerow([time.time_ns(), "rx", "/bacs/kf_desc", len(msg.data.encode())])
            self.generator.add_remote_descriptor(payload)

    def on_request(self, msg: String) -> None:
        request = json.loads(msg.data)
        if request["robot"] == self.robot:
            self.side_writer.writerow([time.time_ns(), "rx", "/bacs/kf_request", len(msg.data.encode())])
            reply = self.generator.points_message(int(request["kf"]))
            if reply is not None:
                self._send(self.pub_points, "/bacs/kf_points", reply)

    def on_points(self, msg: String) -> None:
        payload = json.loads(msg.data)
        if payload["robot"] != self.robot:
            self.side_writer.writerow([time.time_ns(), "rx", "/bacs/kf_points", len(msg.data.encode())])
            self._publish(self.generator.add_remote_points(payload))

    def _publish(self, candidates: list[dict]) -> None:
        for candidate in candidates:
            self.pub_candidates.publish(String(data=json.dumps(candidate)))

    def close(self) -> None:
        for handle in (self.attempts, self.keyframes, self.sidechannel):
            handle.close()


def main() -> None:
    rclpy.init()
    node = CandidateNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close(); node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
