# Go2 + D435i + built-in L1 lidar mapping with RTAB-Map.
#
# The camera + lidar RTAB-Map layout follows h-naderi/unitree-go2-slam-nav2
# (rtab_camera_lidar.launch.py), rewritten for a stock Go2:
#   - lidar:    built-in L1 /utlidar/cloud_base (already in base_link),
#               restamped to the camera clock and assembled over ~1 s
#   - odometry: Go2 /utlidar/robot_odom through go2_camera_bringup
#               (odom_time_sync + odom_to_tf + base_link->camera_link TF),
#               so no ICP odometry and no extra lidar static TFs
#   - camera:   color + aligned depth (Go2 realsense launched with
#               align_depth.enable:=true)
#   - map:      occupancy grid published as /map; localize_only /
#               restart_map choose between keeping, extending or resetting it
#
# Talks to the Go2 only with RMW_IMPLEMENTATION=rmw_cyclonedds_cpp.

import os

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

RGB_TOPIC = '/camera/color/image_raw'
CAMERA_INFO_TOPIC = '/camera/color/camera_info'
DEPTH_TOPIC = '/camera/aligned_depth_to_color/image_raw'
ODOM_TOPIC = '/robot_odom_fixed'
LIDAR_TOPIC = '/utlidar/cloud_base'


def launch_setup(context):
    localize_only = LaunchConfiguration('localize_only').perform(context) == 'true'
    # Existing databases are never reset by this adapter.
    database_path = os.path.expanduser(LaunchConfiguration('database_path').perform(context))
    grid_sensor = LaunchConfiguration('grid_sensor').perform(context)
    if localize_only and not os.path.isfile(database_path):
        raise RuntimeError('Localization requires an existing database')
    if not localize_only and os.path.exists(database_path):
        raise RuntimeError('Mapping refuses an existing database; choose a new path')

    sensor_remappings = [
        ('rgb/image', RGB_TOPIC),
        ('rgb/camera_info', CAMERA_INFO_TOPIC),
        ('depth/image', DEPTH_TOPIC),
        ('scan_cloud', '/assembled_cloud'),
        ('odom', ODOM_TOPIC),
    ]

    cloud_time_sync = Node(
        package='go2_slam_nav', executable='sensor_time_sync', output='screen',
        parameters=[{
            'in_cloud': LIDAR_TOPIC,
            'out_cloud': '/cloud_base_synced',
            'rgb_topic': RGB_TOPIC,
            'publish_odom': LaunchConfiguration('odom_bridge'),
        }],
    )

    # L1 gives ~650 points per message: accumulate ~1 s in the odom frame
    # (motion compensated through TF) and output it in base_link
    assembler = Node(
        package='rtabmap_util', executable='point_cloud_assembler', output='screen',
        parameters=[{
            'assembling_time': 1.0,
            'fixed_frame_id': 'odom',
            'frame_id': 'base_link',
            'voxel_size': 0.05,
            'range_max': 10.0,
            'wait_for_transform': 0.2,
            'use_sim_time': False,
        }],
        remappings=[
            ('cloud', '/cloud_base_synced'),
            ('assembled_cloud', '/assembled_cloud'),
        ],
    )

    rtabmap = Node(
        package='rtabmap_slam', executable='rtabmap', output='screen',
        parameters=[{
            'frame_id': 'base_link',
            'odom_frame_id': '',  # odometry from ODOM_TOPIC
            'subscribe_depth': True,
            'subscribe_rgb': False,
            'subscribe_scan_cloud': True,
            'approx_sync': True,
            'approx_sync_max_interval': 0.5,
            'topic_queue_size': 10,
            'sync_queue_size': 10,
            'wait_for_transform': 0.2,
            'database_path': database_path,
            # In localization, exclude temporary node 0: its observations must
            # not modify the saved occupancy grid when the pose is uncertain.
            'map_always_update': not localize_only,
            'use_saved_map': True,
            'use_sim_time': False,
            'Reg/Strategy': '0',        # visual registration (L1 is too sparse for ICP)
            'Reg/Force3DoF': 'true',    # ground robot: x, y, yaw only
            'RGBD/CreateOccupancyGrid': 'true',
            'Grid/Sensor': grid_sensor,  # 0=lidar, 1=depth, 2=both
            'Grid/RangeMax': '4',
            # base_link is ~0.31 m above the floor: only surfaces whose lowest
            # point is below -0.15 m are ground, so desk tops become obstacles
            'Grid/MaxGroundHeight': '-0.15',
            'Grid/MinGroundHeight': '-0.5',
            'Grid/RayTracing': 'true',
            'Mem/IncrementalMemory': 'false' if localize_only else 'true',
            'Mem/InitWMWithAllNodes': 'true' if localize_only else 'false',
            'Mem/LocalizationReadOnly': 'true' if localize_only else 'false',
            'Mem/LocalizationDataSaved': 'false',
        }],
        remappings=sensor_remappings,

    )

    rtabmap_viz = Node(
        package='rtabmap_viz', executable='rtabmap_viz', output='screen',
        parameters=[{
            'frame_id': 'base_link',
            'odom_frame_id': 'odom',
            'subscribe_depth': True,
            'subscribe_scan_cloud': True,
            'subscribe_odom_info': False,
            'approx_sync': True,
            'use_sim_time': False,
        }],
        remappings=sensor_remappings,
        condition=IfCondition(LaunchConfiguration('use_rtabmapviz')),
    )

    rviz = Node(
        package='rviz2', executable='rviz2', output='screen',
        arguments=['-d', PathJoinSubstitution([
            FindPackageShare('go2_slam_nav'), 'config', 'nav.rviz'])],
        condition=IfCondition(LaunchConfiguration('use_rviz')),
    )

    return [cloud_time_sync, assembler, rtabmap, rtabmap_viz, rviz]


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'localize_only', default_value='false', choices=['true', 'false'],
            description='Localize in the saved map without changing it'),
        DeclareLaunchArgument(
            'restart_map', default_value='false', choices=['false'],
            description='Database reset is disabled'),
        DeclareLaunchArgument(
            'database_path', default_value='~/.ros/rtabmap_go2_l1.db',
            description='Where the map is saved and loaded'),
        DeclareLaunchArgument(
            'grid_sensor', default_value='2', choices=['0', '1', '2'],
            description='Occupancy grid source: 0=L1 lidar, 1=depth camera, 2=both'),
        DeclareLaunchArgument(
            'use_rtabmapviz', default_value='true', choices=['true', 'false'],
            description='Open the RTAB-Map viewer'),
        DeclareLaunchArgument(
            'use_rviz', default_value='true', choices=['true', 'false'],
            description='Open RViz with the map, L1 points and trajectory already set up'),
        DeclareLaunchArgument(
            'odom_bridge', default_value='true', choices=['true', 'false'],
            description='Start go2_camera_bringup odom sync + TF (set false if already running)'),

        Node(package='tf2_ros', executable='static_transform_publisher',
             name='static_tf_camera',
             arguments=['0.2', '0', '0.09', '0', '0', '0', '1', 'base_link', 'camera_link']),
        OpaqueFunction(function=launch_setup),
    ])
