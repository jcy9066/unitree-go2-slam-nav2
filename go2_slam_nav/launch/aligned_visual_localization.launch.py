"""Saved-map visual comparison using acquisition times; no motion nodes."""
import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def launch_setup(context):
    database = os.path.expanduser(LaunchConfiguration('database_path').perform(context))
    if not os.path.isfile(database) or os.path.getsize(database) == 0:
        raise RuntimeError('An existing session-copy database is required')
    reference = LaunchConfiguration('reference_camera').perform(context) == 'true'
    use_sim_time = ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool)
    return [
        Node(package='go2_slam_nav', executable='sensor_time_sync', name='sensor_time_sync',
             output='screen', parameters=[{
                 'use_sim_time': use_sim_time, 'stamp_mode': 'source',
                 'visual_heading': False, 'publish_odom': True,
                 'max_source_stamp_skew': 1.0,
             }]),
        # Match the saved camera model for each DB family. These are historical
        # extrinsics, not a new physical calibration.
        Node(package='tf2_ros', executable='static_transform_publisher',
             name='static_tf_camera', output='screen',
             arguments=['0.34' if reference else '0.2', '0',
                        '0.095' if reference else '0.09', '0', '0', '0', '1',
                        'base_link', 'camera_link'],
             parameters=[{'use_sim_time': use_sim_time}]),
        Node(package='rtabmap_sync', executable='rgbd_sync', name='localization_rgbd_sync',
             output='screen', parameters=[{
                 'use_sim_time': use_sim_time, 'approx_sync': True,
                 'approx_sync_max_interval': 0.03, 'topic_queue_size': 100,
                 'sync_queue_size': 100, 'qos': 1, 'qos_image': 1, 'qos_camera_info': 1,
             }], remappings=[
                 ('rgb/image', '/camera/color/image_raw'),
                 ('depth/image', '/camera/aligned_depth_to_color/image_raw'),
                 ('rgb/camera_info', '/camera/color/camera_info'),
                 ('rgbd_image', '/go2_localization/rgbd_image'),
             ]),
        Node(package='rtabmap_slam', executable='rtabmap', name='rtabmap', output='screen',
             parameters=[{
                 'use_sim_time': use_sim_time, 'database_path': database,
                 'frame_id': 'base_link', 'odom_frame_id': '', 'map_frame_id': 'map',
                 'subscribe_rgbd': True, 'subscribe_depth': False,
                 'subscribe_scan_cloud': False, 'approx_sync': True,
                 'approx_sync_max_interval': 0.03, 'odom_sensor_sync': True,
                 'topic_queue_size': 100, 'sync_queue_size': 100,
                 'wait_for_transform': 0.2, 'qos': 1, 'qos_odom': 1,
                 'publish_tf': ParameterValue(LaunchConfiguration('publish_map_tf'), value_type=bool),
                 'map_always_update': False, 'use_saved_map': True,
                 'Reg/Strategy': '0', 'Reg/Force3DoF': 'false',
                 'Kp/DetectorStrategy': '8', 'Vis/FeatureType': '8',
                 'Vis/EstimationType': '1', 'Vis/MinInliers': '20',
                 'Mem/IncrementalMemory': 'false', 'Mem/InitWMWithAllNodes': 'true',
                 'Mem/LocalizationReadOnly': 'true', 'Mem/LocalizationDataSaved': 'false',
                 'Rtabmap/DetectionRate': '2.0', 'RGBD/ProximityBySpace': 'true',
                 'RGBD/ProximityOdomGuess': 'true',
                 'RGBD/LinearUpdate': '0.05', 'RGBD/AngularUpdate': '0.05',
             }], remappings=[('odom', '/robot_odom_fixed'),
                             ('rgbd_image', '/go2_localization/rgbd_image')]),
    ]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('database_path'),
        DeclareLaunchArgument('reference_camera', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('use_sim_time', default_value='false', choices=['true', 'false']),
        DeclareLaunchArgument('publish_map_tf', default_value='true', choices=['true', 'false']),
        OpaqueFunction(function=launch_setup),
    ])
