"""Stock Go2 L1 + D435i mapping/localization; no RoboSense or ICP odometry."""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    return LaunchDescription([IncludeLaunchDescription(PythonLaunchDescriptionSource(
        PathJoinSubstitution([FindPackageShare('go2_slam_nav'), 'launch', 'l1_rgbd.launch.py'])
    ))])
