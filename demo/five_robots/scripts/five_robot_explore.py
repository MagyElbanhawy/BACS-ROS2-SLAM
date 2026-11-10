#!/usr/bin/env python3
import math
import time
import rclpy

from rclpy.node import Node
from geometry_msgs.msg import Twist
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from rclpy.qos import qos_profile_sensor_data

ROBOTS = {
    "robot1": (-5.21, -0.20, 0.85),
    "robot2": (5.45, 0.13, 0.85),
    "robot3": (-5.90, 3.00, 1.10),
    "robot4": (0.00, 3.00, 1.10),
    "robot5": (5.90, 3.00, 1.10),
}

class Explorer(Node):
    def __init__(self):
        super().__init__("five_robot_explorer")
        self.data = {}

        for name, (x, y, radius) in ROBOTS.items():
            self.data[name] = {
                "origin": (x, y),
                "radius": radius,
                "pose": None,
                "yaw": 0.0,
                "scan": None,
                "scan_time": 0.0,
                "odom_time": 0.0,
                "turn": 1 if name in ("robot1", "robot3", "robot5") else -1,
            }

            self.data[name]["pub"] = self.create_publisher(
                Twist, f"/{name}/cmd_vel", 10
            )

            self.create_subscription(
                LaserScan,
                f"/{name}/scan",
                lambda msg, n=name: self.on_scan(n, msg),
                qos_profile_sensor_data,
            )

            self.create_subscription(
                Odometry,
                f"/{name}/odom",
                lambda msg, n=name: self.on_odom(n, msg),
                10,
            )

        self.create_timer(0.1, self.control)
        self.get_logger().info("Five-robot explorer ready")

    def on_scan(self, name, msg):
        d = self.data[name]
        d["scan"] = msg
        d["scan_time"] = time.monotonic()

    def on_odom(self, name, msg):
        d = self.data[name]
        p = msg.pose.pose.position
        q = msg.pose.pose.orientation

        d["pose"] = (p.x, p.y)
        d["yaw"] = math.atan2(
            2 * (q.w * q.z + q.x * q.y),
            1 - 2 * (q.y*q.y + q.z*q.z)
        )
        d["odom_time"] = time.monotonic()

    def front_distance(self, scan):
        values = []
        for i, r in enumerate(scan.ranges):
            a = scan.angle_min + i * scan.angle_increment
            if abs(a) < math.radians(40):
                if math.isfinite(r) and scan.range_min <= r <= scan.range_max:
                    values.append(r)
        return min(values) if values else 0.0

    def control(self):
        now = time.monotonic()

        for name, d in self.data.items():
            cmd = Twist()

            if (
                d["pose"] is None or d["scan"] is None
                or now - d["scan_time"] > 1.0
                or now - d["odom_time"] > 1.0
            ):
                d["pub"].publish(cmd)
                continue

            x, y = d["pose"]
            ox, oy = d["origin"]

            distance = math.hypot(x - ox, y - oy)
            front = self.front_distance(d["scan"])

            if distance > d["radius"] * 0.75:
                target = math.atan2(oy - y, ox - x)
                error = math.atan2(
                    math.sin(target - d["yaw"]),
                    math.cos(target - d["yaw"])
                )

                cmd.linear.x = 0.04 if abs(error) < 0.5 else 0.0
                cmd.angular.z = max(-0.55, min(0.55, 1.2 * error))

            elif front < 0.70:
                cmd.linear.x = 0.0
                cmd.angular.z = 0.55 * d["turn"]

            else:
                cmd.linear.x = 0.16
                cmd.angular.z = 0.0

            d["pub"].publish(cmd)

    def stop_all(self):
        for _ in range(10):
            for d in self.data.values():
                d["pub"].publish(Twist())
            time.sleep(0.05)


def main():
    rclpy.init()
    node = Explorer()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop_all()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
