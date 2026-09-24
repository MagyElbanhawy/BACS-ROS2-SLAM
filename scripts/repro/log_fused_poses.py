#!/usr/bin/env python3
"""Log fused-map robot poses next to the matching Vicon pose during bag replay.

Run while the bag replays (``--clock``) and the SLAM/fusion stack is running, so
that ``map -> <robot>/base_link`` is actually published:

    ros2 bag play hardware/raw/HWS-002-FIFO/HWS-002-FIFO_20260714_094217_mcap --clock
    python3 scripts/repro/log_fused_poses.py --ros-args -p use_sim_time:=true \
        -p session:=HWS-002-FIFO -p out:=paper_results/physical/fused/fused_HWS-002-FIFO.csv

One row is written per robot per tick. Rows are skipped (never interpolated or
filled) when the transform or a sufficiently fresh Vicon sample is unavailable;
skip counts are printed on shutdown.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import Buffer, TransformException, TransformListener

FIELDS = ["session", "stamp_ns", "robot", "est_x", "est_y", "est_yaw", "tf_stamp_ns",
          "vicon_stamp_ns", "vicon_x", "vicon_y", "vicon_yaw"]


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def stamp_ns(stamp) -> int:
    return stamp.sec * 1_000_000_000 + stamp.nanosec


class FusedPoseLogger(Node):
    def __init__(self) -> None:
        super().__init__("fused_pose_logger")
        self.session = self.declare_parameter("session", "").value
        out = self.declare_parameter("out", "").value
        self.map_frame = self.declare_parameter("map_frame", "map").value
        self.robots = list(self.declare_parameter("robots", ["limo01", "limo02"]).value)
        base_fmt = self.declare_parameter("base_frame_format", "{robot}/base_link").value
        vicon_fmt = self.declare_parameter("vicon_topic_format", "/vicon/{robot}/pose").value
        rate_hz = float(self.declare_parameter("rate_hz", 10.0).value)
        self.max_vicon_age_ns = int(float(self.declare_parameter("max_vicon_age_s", 0.05).value) * 1e9)
        if not self.session or not out:
            raise SystemExit("Parameters 'session' and 'out' are required.")

        self.base_frames = {r: base_fmt.format(robot=r) for r in self.robots}
        self.vicon: dict[str, PoseStamped | None] = {r: None for r in self.robots}
        self.skipped = {r: {"no_tf": 0, "no_vicon": 0, "stale_vicon": 0} for r in self.robots}
        self.written = {r: 0 for r in self.robots}

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        for robot in self.robots:
            self.create_subscription(PoseStamped, vicon_fmt.format(robot=robot),
                                     lambda msg, r=robot: self.vicon.__setitem__(r, msg), qos_profile_sensor_data)

        path = Path(out); path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = path.open("w", newline="", encoding="utf-8")
        self.writer = csv.DictWriter(self.handle, fieldnames=FIELDS); self.writer.writeheader()
        self.create_timer(1.0 / rate_hz, self.tick)
        self.get_logger().info(f"Logging {self.map_frame} -> {list(self.base_frames.values())} to {path}")

    def tick(self) -> None:
        now_ns = self.get_clock().now().nanoseconds
        if now_ns == 0:  # /clock not received yet
            return
        for robot in self.robots:
            try:
                tf = self.tf_buffer.lookup_transform(self.map_frame, self.base_frames[robot], Time())
            except TransformException:
                self.skipped[robot]["no_tf"] += 1
                continue
            vicon = self.vicon[robot]
            if vicon is None:
                self.skipped[robot]["no_vicon"] += 1
                continue
            tf_ns, vicon_ns = stamp_ns(tf.header.stamp), stamp_ns(vicon.header.stamp)
            if abs(vicon_ns - tf_ns) > self.max_vicon_age_ns:
                self.skipped[robot]["stale_vicon"] += 1
                continue
            t, q = tf.transform.translation, tf.transform.rotation
            vp, vq = vicon.pose.position, vicon.pose.orientation
            self.writer.writerow({
                "session": self.session, "stamp_ns": now_ns, "robot": robot,
                "est_x": t.x, "est_y": t.y, "est_yaw": yaw_from_quaternion(q.x, q.y, q.z, q.w),
                "tf_stamp_ns": tf_ns, "vicon_stamp_ns": vicon_ns, "vicon_x": vp.x, "vicon_y": vp.y,
                "vicon_yaw": yaw_from_quaternion(vq.x, vq.y, vq.z, vq.w),
            })
            self.written[robot] += 1

    def close(self) -> None:
        self.handle.close()
        for robot in self.robots:
            self.get_logger().info(f"{robot}: written={self.written[robot]} skipped={self.skipped[robot]}")


def main() -> None:
    rclpy.init()
    node = FusedPoseLogger()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close(); node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
