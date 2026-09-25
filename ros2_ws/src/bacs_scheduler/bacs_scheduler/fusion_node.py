"""Fusion server: trust-weighted pose graph (Eq. 1, Eq. 6) -> map -> <robot>/odom on /tf.

    ros2 bag play <session_bag> --clock
    ros2 run bacs_scheduler bacs_fusion --ros-args -p use_sim_time:=true -p session:=HWS-101-FIFO \
        -p run:=1 -p start_poses:="[0.0, 0.0, 0.0, 0.0, 1.0, 0.0]"

Inputs: ``/bacs/keyframes`` (each robot's keyframe poses in its own local frame, JSON) and
``/bacs/received`` (LoRa-delivered constraints from ``bacs_receiver``, JSON with z_ij, variances,
keyframe ids, t_rcv_ns and gen_ms). Output: ``map -> <robot>/odom`` transforms stamped with the
node clock (the bag's /clock when use_sim_time is true). ``map -> <robot>/base_link`` follows
through the bag's own ``odom -> base_link``; publishing map -> base_link directly would give
base_link two parents. Every inter-robot edge and its trust is written to
``fusion_edges.csv``; ``fusion_summary.json`` holds the edge count and mean trust.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster

from .fusion_core import FusionCore, FusionParams
from .node_common import run_dir


class FusionNode(Node):
    def __init__(self) -> None:
        super().__init__("bacs_fusion")
        p = lambda name, default: self.declare_parameter(name, default).value  # noqa: E731
        session, run = p("session", ""), int(p("run", 0))
        if not session or run <= 0:
            raise SystemExit("Parameters 'session' and 'run' (>0) are required.")
        self.robots = list(p("robots", ["limo01", "limo02"]))
        flat = [float(v) for v in p("start_poses", [0.0] * 3 * len(self.robots))]
        if len(flat) != 3 * len(self.robots):
            raise SystemExit("start_poses must hold x, y, yaw for every robot (measured floor marks).")
        starts = {r: tuple(flat[3 * i:3 * i + 3]) for i, r in enumerate(self.robots)}
        t_defer = float(p("t_defer_s", 155.0))
        params = FusionParams(tau_e=float(p("tau_e", 0.5)), p=float(p("p", 3.0)), floor=float(p("floor", 0.01)),
                              gamma=math.log(2) / t_defer, iterations=int(p("iterations", 10)),
                              constraint_information=p("constraint_information", "fixed"))
        if not self.get_parameter("use_sim_time").value:
            self.get_logger().warn("use_sim_time is false: transforms are stamped with the system clock.")
        self.map_frame = p("map_frame", "map")
        self.local_format = p("local_frame", "{robot}/odom")
        self.out = run_dir(p("log_dir", "~/bacs_hw_logs"), session, run)
        self.edge_log = (self.out / "fusion_edges.csv").open("w", newline="", encoding="utf-8")
        self.core = FusionCore(self.robots, starts, params, self.edge_log)
        self.broadcaster = TransformBroadcaster(self)
        self.fused_pub = self.create_publisher(String, p("fused_pose_topic", "/fused_poses"), 100)
        self.create_subscription(String, p("keyframe_topic", "/bacs/keyframes"), self.on_keyframe, 1000)
        self.create_subscription(String, p("constraint_topic", "/bacs/received"), self.on_constraint, 1000)
        self.create_timer(float(p("solve_period_s", 1.0)), self.on_solve)
        self.create_timer(1.0 / float(p("tf_rate_hz", 20.0)), self.on_tf)
        self.get_logger().info(f"Fusion: gamma = ln2/{t_defer:.0f} s = {params.gamma:.5f}/s, logging to {self.out}")

    def on_keyframe(self, msg: String) -> None:
        k = json.loads(msg.data)
        if k["robot"] in self.robots:
            self.core.add_keyframe(k["robot"], int(k["kf"]), float(k["x"]), float(k["y"]), float(k["yaw"]))

    def on_constraint(self, msg: String) -> None:
        c = json.loads(msg.data)
        if c.get("decode_status", "OK") == "OK" and c["robot_i"] in self.robots and c["robot_j"] in self.robots:
            self.core.add_constraint(c)

    def on_solve(self) -> None:
        if self.core.dirty:
            self.core.optimize()

    def on_tf(self) -> None:
        stamp = self.get_clock().now().to_msg()
        transforms = []
        poses = []
        for robot in self.robots:
            pose = self.core.map_to_local(robot)
            if pose is None:
                continue
            t = TransformStamped()
            t.header.stamp, t.header.frame_id = stamp, self.map_frame
            t.child_frame_id = self.local_format.format(robot=robot)
            t.transform.translation.x, t.transform.translation.y = pose[0], pose[1]
            t.transform.rotation.z, t.transform.rotation.w = math.sin(pose[2] / 2), math.cos(pose[2] / 2)
            transforms.append(t)
            poses.append({"robot": robot, "frame_id": self.map_frame, "child_frame_id": t.child_frame_id,
                          "x": pose[0], "y": pose[1], "yaw": pose[2]})
        if transforms:
            self.broadcaster.sendTransform(transforms)
            self.fused_pub.publish(String(data=json.dumps({
                "stamp_ns": self.get_clock().now().nanoseconds,
                "map_frame": self.map_frame,
                "poses": poses,
            }, separators=(",", ":"))))

    def close(self) -> None:
        thetas = self.core.thetas
        summary = {"inter_robot_edges": len(thetas), "pending_unmatched": len(self.core.pending),
                   "mean_trust": sum(thetas) / len(thetas) if thetas else None}
        (Path(self.out) / "fusion_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        self.edge_log.close()


def main() -> None:
    rclpy.init()
    node = FusionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.close(); node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
