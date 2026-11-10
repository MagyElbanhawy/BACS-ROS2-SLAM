#!/usr/bin/env bash

set -e

BASE="$HOME/ros2_ws"
DEMO="$BASE/final_demo"
ROBOT_DIR="$BASE/worlds/agilex_robots"
WORLD="$BASE/worlds/robotics_office_5rooms.world"

source /opt/ros/humble/setup.bash
source "$BASE/install/setup.bash"

mkdir -p "$DEMO/logs" "$DEMO/pids"

start_demo() {
    echo "Starting Gazebo..."
    gazebo --verbose "$WORLD" \
      -s libgazebo_ros_init.so \
      -s libgazebo_ros_factory.so \
      > "$DEMO/logs/gazebo.log" 2>&1 &

    echo $! > "$DEMO/pids/gazebo.pid"

    echo "Waiting for Gazebo spawn service..."
    until ros2 service list 2>/dev/null | grep -qx '/spawn_entity'; do
        sleep 2
    done

    echo "Spawning five enlarged robots..."

    X=(-5.21 5.45 -5.90 0.00 5.90)
    Y=(-0.20 0.13 3.00 3.00 3.00)
    YAW=(0.33 2.57 0 0 0)

    for i in 1 2 3 4 5; do
        j=$((i-1))
        ros2 run gazebo_ros spawn_entity.py \
          -entity "robot$i" \
          -file "$ROBOT_DIR/robot${i}_visual150.urdf" \
          -x "${X[$j]}" \
          -y "${Y[$j]}" \
          -z 0.30 \
          -Y "${YAW[$j]}"
    done

    echo "Five robots spawned."
    echo "Gazebo is ready for camera zoom recording."
}

start_mapping() {
    echo "Starting five independent SLAM sessions..."

    if [ -f "$DEMO/pids/slam.pid" ] &&
       kill -0 "$(cat "$DEMO/pids/slam.pid")" 2>/dev/null; then
        echo "Mapping is already running."
        return
    fi

    python3 - "$DEMO/five_robots_mapping.launch.py" \
      > "$DEMO/logs/slam.log" 2>&1 <<'PYLAUNCH' &
import sys
from launch import LaunchService
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.actions import IncludeLaunchDescription
from launch import LaunchDescription

service = LaunchService()
service.include_launch_description(
    LaunchDescription([
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(sys.argv[1])
        )
    ])
)
service.run()
PYLAUNCH

    echo $! > "$DEMO/pids/slam.pid"
    echo "Five-robot mapping started."
}

start_move() {
    echo "Starting five-robot movement..."
    python3 "$BASE/scripts/five_robot_explore.py" \
      > "$DEMO/logs/movement.log" 2>&1 &

    echo $! > "$DEMO/pids/movement.pid"
}

stop_move() {
    if [ -f "$DEMO/pids/movement.pid" ]; then
        kill -INT "$(cat "$DEMO/pids/movement.pid")" 2>/dev/null || true
        rm -f "$DEMO/pids/movement.pid"
    fi

    for i in 1 2 3 4 5; do
        ros2 topic pub --once "/robot$i/cmd_vel" \
          geometry_msgs/msg/Twist '{}' >/dev/null 2>&1 || true
    done

    echo "Movement stopped."
}

stop_demo() {
    echo "Stopping experiment..."

    for file in "$DEMO"/pids/*.pid; do
        [ -f "$file" ] || continue
        kill -INT "$(cat "$file")" 2>/dev/null || true
    done

    sleep 2

    echo "Stop signals sent."
}

case "${1:-}" in
    start) start_demo ;;
    mapping) start_mapping ;;
    move) start_move ;;
    stop-move) stop_move ;;
    stop) stop_demo ;;
    *)
        echo "Usage:"
        echo "./demo.sh start"
        echo "./demo.sh mapping"
        echo "./demo.sh move"
        echo "./demo.sh stop-move"
        echo "./demo.sh stop"
        ;;
esac
