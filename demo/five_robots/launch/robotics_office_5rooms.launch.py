#!/usr/bin/env python3
"""Standalone Gazebo Classic ROS 2 Humble robotics lab with two LiDAR robots.
Launch: ros2 launch /absolute/path/robotics_lab.launch.py
Requires: ros-humble-gazebo-ros-pkgs, Gazebo Classic.
"""
import os
import tempfile
from pathlib import Path
from launch import LaunchDescription
from launch.actions import ExecuteProcess, TimerAction, SetEnvironmentVariable
from launch_ros.actions import Node

WORLD = str(Path(__file__).resolve().with_name('robotics_office_5rooms.world'))


def robot_sdf(name):
    """Generate an independent differential-drive LiDAR robot SDF."""
    return f'''<?xml version="1.0"?>
<sdf version="1.6">
  <model name="{name}">
    <pose>0 0 0 0 0 0</pose>
    <link name="base_link">
      <pose>0 0 0.17 0 0 0</pose>
      <inertial><mass>8</mass><inertia><ixx>0.12</ixx><iyy>0.12</iyy><izz>0.18</izz></inertia></inertial>
      <collision name="body_collision"><geometry><box><size>0.36 0.26 0.18</size></box></geometry></collision>
      <visual name="body_visual"><geometry><box><size>0.36 0.26 0.18</size></box></geometry>
        <material><ambient>0.12 0.42 0.9 1</ambient><diffuse>0.12 0.42 0.9 1</diffuse></material></visual>
      <sensor name="lidar" type="ray">
        <pose>0 0 0.12 0 0 0</pose>
        <always_on>true</always_on><update_rate>10</update_rate><visualize>false</visualize>
        <ray><scan><horizontal><samples>360</samples><resolution>1</resolution><min_angle>-3.14159</min_angle><max_angle>3.14159</max_angle></horizontal></scan>
          <range><min>0.12</min><max>12.0</max><resolution>0.01</resolution></range></ray>
        <plugin name="ros_lidar" filename="libgazebo_ros_ray_sensor.so">
          <ros><namespace>/{name}</namespace><remapping>~/out:=scan</remapping></ros>
          <output_type>sensor_msgs/LaserScan</output_type><frame_name>{name}/laser</frame_name>
        </plugin>
      </sensor>
    </link>
    <link name="left_wheel"><pose>0 0.17 0.09 1.5707963 0 0</pose>
      <inertial><mass>0.3</mass><inertia><ixx>0.001</ixx><iyy>0.001</iyy><izz>0.001</izz></inertia></inertial>
      <collision name="collision"><geometry><cylinder><radius>0.09</radius><length>0.045</length></cylinder></geometry></collision>
      <visual name="visual"><geometry><cylinder><radius>0.09</radius><length>0.045</length></cylinder></geometry></visual>
    </link>
    <link name="right_wheel"><pose>0 -0.17 0.09 1.5707963 0 0</pose>
      <inertial><mass>0.3</mass><inertia><ixx>0.001</ixx><iyy>0.001</iyy><izz>0.001</izz></inertia></inertial>
      <collision name="collision"><geometry><cylinder><radius>0.09</radius><length>0.045</length></cylinder></geometry></collision>
      <visual name="visual"><geometry><cylinder><radius>0.09</radius><length>0.045</length></cylinder></geometry></visual>
    </link>
    <joint name="left_wheel_joint" type="revolute"><parent>base_link</parent><child>left_wheel</child><axis><xyz>0 0 1</xyz><limit><lower>-1e16</lower><upper>1e16</upper></limit></axis></joint>
    <joint name="right_wheel_joint" type="revolute"><parent>base_link</parent><child>right_wheel</child><axis><xyz>0 0 1</xyz><limit><lower>-1e16</lower><upper>1e16</upper></limit></axis></joint>
    <plugin name="diff_drive" filename="libgazebo_ros_diff_drive.so">
      <ros><namespace>/{name}</namespace><remapping>cmd_vel:=cmd_vel</remapping><remapping>odom:=odom</remapping></ros>
      <update_rate>50</update_rate><left_joint>left_wheel_joint</left_joint><right_joint>right_wheel_joint</right_joint>
      <wheel_separation>0.34</wheel_separation><wheel_diameter>0.18</wheel_diameter>
      <max_wheel_torque>12</max_wheel_torque><max_wheel_acceleration>2.0</max_wheel_acceleration>
      <command_topic>cmd_vel</command_topic><odometry_topic>odom</odometry_topic>
      <odometry_frame>{name}/odom</odometry_frame><robot_base_frame>{name}/base_link</robot_base_frame>
      <publish_odom>true</publish_odom><publish_odom_tf>true</publish_odom_tf><publish_wheel_tf>false</publish_wheel_tf>
    </plugin>
  </model>
</sdf>'''


def generate_launch_description():
    if not Path(WORLD).is_file():
        raise FileNotFoundError(f'World missing: {WORLD}')
    tmp = Path(tempfile.mkdtemp(prefix='bacs_lab_'))
    robots = [('limo01', '-6.0', '0.0', '0.0'), ('limo02', '6.0', '0.0', '3.14159')]
    actions = [
        SetEnvironmentVariable('GAZEBO_MASTER_URI', 'http://127.0.0.1:11345'),
        ExecuteProcess(cmd=['gazebo', '--verbose', WORLD,
                            '-s', 'libgazebo_ros_init.so',
                            '-s', 'libgazebo_ros_factory.so'], output='screen'),
    ]
    for name, x, y, yaw in robots:
        file = tmp / f'{name}.sdf'
        file.write_text(robot_sdf(name))
        actions.append(Node(package='tf2_ros', executable='static_transform_publisher',
                            arguments=['0', '0', '0.12', '0', '0', '0',
                                       f'{name}/base_link', f'{name}/laser'], output='screen'))
        actions.append(TimerAction(period=7.0, actions=[ExecuteProcess(
            cmd=['ros2', 'run', 'gazebo_ros', 'spawn_entity.py',
                 '-entity', name, '-file', str(file), '-x', x, '-y', y,
                 '-z', '0.05', '-Y', yaw], output='screen')]))
    return LaunchDescription(actions)
