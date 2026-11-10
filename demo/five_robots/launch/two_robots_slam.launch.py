from launch import LaunchDescription
from launch_ros.actions import Node
from pathlib import Path

def generate_launch_description():
    nodes = []

    for robot in ("robot1", "robot2"):
        nodes.append(
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                namespace=robot,
                name="slam_toolbox",
                output="screen",
                parameters=[
                    {
                        "use_sim_time": True,
                        "odom_frame": f"{robot}/odom",
                        "map_frame": f"{robot}/map",
                        "base_frame": f"{robot}/base_footprint",
                        "scan_topic": f"/{robot}/scan",
                        "mode": "mapping",
                        "resolution": 0.05,
                        "max_laser_range": 12.0,
                        "minimum_travel_distance": 0.05,
                        "minimum_travel_heading": 0.05,
                        "map_update_interval": 1.0,
                        "transform_publish_period": 0.02,
                        "transform_timeout": 0.5,
                        "tf_buffer_duration": 30.0,
                        "use_scan_matching": True,
                        "do_loop_closing": True,
                        "solver_plugin": "solver_plugins::CeresSolver",
                    }
                ],
                remappings=[
                    ("/tf", "/tf"),
                    ("/tf_static", "/tf_static"),
                    ("/map", f"/{robot}/map"),
                    ("/map_metadata", f"/{robot}/map_metadata"),
                    ("/map_updates", f"/{robot}/map_updates"),
                ],
            )
        )

    return LaunchDescription(nodes)
