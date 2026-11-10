from launch import LaunchDescription
from launch_ros.actions import Node
from pathlib import Path

def generate_launch_description():
    nodes = []
    urdf_dir = Path.home() / "ros2_ws/worlds/agilex_robots"

    for i in (3, 4, 5):
        robot = f"robot{i}"
        urdf = (urdf_dir / f"{robot}.urdf").read_text()

        nodes.append(
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                namespace=robot,
                name="robot_state_publisher",
                output="screen",
                parameters=[{
                    "robot_description": urdf,
                    "use_sim_time": True,
                    "publish_frequency": 30.0,
                }],
                remappings=[
                    ("/tf", "/tf"),
                    ("/tf_static", "/tf_static"),
                ],
            )
        )

        nodes.append(
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                namespace=robot,
                name="slam_toolbox",
                output="screen",
                parameters=[{
                    "use_sim_time": True,
                    "odom_frame": f"{robot}/odom",
                    "map_frame": f"{robot}/map",
                    "base_frame": f"{robot}/base_footprint",
                    "scan_topic": f"/{robot}/scan",
                    "mode": "mapping",
                    "resolution": 0.05,
                    "max_laser_range": 8.0,
                    "minimum_travel_distance": 0.05,
                    "minimum_travel_heading": 0.05,
                    "map_update_interval": 1.0,
                }],
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
