"""Saved-map localization, Nav2, and optional existing local Go2 control."""

import os
import json
import math

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription, OpaqueFunction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterFile
from launch_ros.substitutions import FindPackageShare
from go2_slam_nav.first_door_route import validate_route_database


def launch_setup(context):
    share = FindPackageShare('go2_slam_nav').perform(context)
    params = os.path.expanduser(LaunchConfiguration('nav2_params_file').perform(context))
    if not os.path.isfile(params):
        raise RuntimeError(f'Nav2 parameter file does not exist: {params}')
    first_door_only = LaunchConfiguration('first_door_only').perform(context) == 'true'
    profile = LaunchConfiguration('localization_profile').perform(context)
    if profile not in ('legacy', 'aligned_visual', 'reference_visual'):
        raise RuntimeError('Unknown localization profile')
    if first_door_only:
        default_params = os.path.join(share, 'config', 'nav2_params.yaml')
        if os.path.realpath(params) != os.path.realpath(default_params):
            raise RuntimeError('first_door_only uses its validated built-in parameter file')
        validate_route_database(
            LaunchConfiguration('database_path').perform(context),
            os.path.join(share, 'config', 'first_door_route.json'))
        params = os.path.join(share, 'config', 'nav2_first_door_only.yaml')
    # Resolve installed behavior-tree paths in the parameter YAML.
    parameter_file = ParameterFile(params, allow_substs=True)
    actions = []
    route_nodes = []
    if first_door_only:
        actions.extend([
            Node(package='nav2_map_server', executable='map_server',
                 name='first_door_mask', output='screen', parameters=[{
                     'use_sim_time': False, 'frame_id': 'map', 'topic_name': '/first_door_mask',
                     'yaml_filename': os.path.join(share, 'config', 'first_door_keepout.yaml')}]),
            Node(package='nav2_map_server', executable='costmap_filter_info_server',
                 name='first_door_filter_info', output='screen', parameters=[{
                     'use_sim_time': False, 'filter_info_topic': '/first_door_filter_info',
                     'type': 0, 'mask_topic': '/first_door_mask', 'base': 0.0, 'multiplier': 1.0}]),
        ])
        route_nodes = ['first_door_mask', 'first_door_filter_info']
    if LaunchConfiguration('start_localization').perform(context) == 'true':
        database = os.path.expanduser(LaunchConfiguration('database_path').perform(context))
        if not os.path.isfile(database) or os.path.getsize(database) == 0:
            raise RuntimeError(f'An existing RTAB-Map database is required: {database}')
        # Keep the mapping viewer switches local to this include. Otherwise its
        # use_rviz=false also disables the navigation RViz declared below.
        localization_launch = 'l1_rgbd.launch.py' if profile == 'legacy' else 'aligned_visual_localization.launch.py'
        localization_args = {
            'database_path': database, 'localize_only': 'true', 'restart_map': 'false',
            'use_rviz': 'false', 'use_rtabmapviz': 'false',
            'odom_bridge': LaunchConfiguration('odom_bridge'),
        } if profile == 'legacy' else {
            'database_path': database,
            'reference_camera': str(profile == 'reference_visual').lower(),
        }
        actions.append(GroupAction(scoped=True, actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(os.path.join(share, 'launch', localization_launch)),
                launch_arguments=localization_args.items(),
            ),
        ]))

    nav_camera_frame = 'camera_color_frame'
    calibration_path = LaunchConfiguration('nav_camera_calibration').perform(context)
    if calibration_path:
        with open(os.path.expanduser(calibration_path)) as stream:
            calibration = json.load(stream)
        translation = calibration['normal_frame_translation']
        quaternion = calibration['normal_frame_quaternion_xyzw']
        if (len(translation) != 3 or len(quaternion) != 4 or
                not all(math.isfinite(v) for v in [*translation, *quaternion]) or
                abs(sum(v*v for v in quaternion)-1.0) > 1e-4):
            raise RuntimeError('Invalid navigation camera calibration')
        nav_camera_frame = 'go2_nav_camera_color_frame'
        actions.append(Node(
            package='tf2_ros', executable='static_transform_publisher',
            name='go2_nav_camera_calibration', output='screen',
            arguments=[*[str(v) for v in translation], *[str(v) for v in quaternion],
                       'base_link', nav_camera_frame],
            parameters=[{'use_sim_time': False}],
        ))

    actions.append(Node(
        package='go2_slam_nav', executable='obstacle_cloud_filter',
        name='go2_obstacle_cloud_filter', output='screen',
        parameters=[{'use_sim_time': False, 'minimum_body_height': -0.20,
                     'maximum_body_height': 1.20}],
    ))
    actions.append(Node(
        package='depthimage_to_laserscan', executable='depthimage_to_laserscan_node',
        name='go2_nav_depth_to_scan', output='screen',
        parameters=[{'use_sim_time': False, 'scan_height': 10, 'scan_time': 1.0 / 30.0,
                     'output_frame': nav_camera_frame,
                     'range_min': 0.3, 'range_max': 3.0}],
        remappings=[('depth', '/camera/aligned_depth_to_color/image_raw'),
                    ('depth_camera_info', '/camera/color/camera_info'),
                    ('scan', '/go2_nav/depth_scan')],
    ))

    # Humble Nav2 server layout, with explicit velocity routing. The default
    # /cmd_vel remains unused so an unrelated Go2 bridge cannot move the robot.
    servers = [
        ('nav2_controller', 'controller_server', [('cmd_vel', '/go2_nav/cmd_vel_raw')]),
        ('nav2_smoother', 'smoother_server', []),
        ('nav2_planner', 'planner_server', []),
        ('nav2_behaviors', 'behavior_server', [('cmd_vel', '/go2_nav/cmd_vel_raw')]),
        ('nav2_bt_navigator', 'bt_navigator', []),
        ('nav2_waypoint_follower', 'waypoint_follower', []),
        ('nav2_velocity_smoother', 'velocity_smoother', [
            ('cmd_vel', '/go2_nav/cmd_vel_raw'), ('cmd_vel_smoothed', '/go2_nav/cmd_vel')]),
    ]
    server_parameters = [parameter_file]
    if profile == 'aligned_visual':
        # The original planar DB uses body-height zero, unlike odom's floor
        # datum. Preserve equivalent physical height filtering in Global.
        server_parameters.append(ParameterFile(os.path.join(
            share, 'config', 'nav2_aligned_visual_height.yaml')))
    server_parameters.append({'use_sim_time': False})
    for package, name, remappings in servers:
        actions.append(Node(package=package, executable=name, name=name, output='screen',
                            parameters=server_parameters, remappings=remappings))
    actions.append(Node(
        package='nav2_lifecycle_manager', executable='lifecycle_manager',
        name='lifecycle_manager_navigation', output='screen',
        parameters=[{'use_sim_time': False, 'autostart': True,
                     'node_names': route_nodes + [name for _, name, _ in servers]}],
    ))
    if LaunchConfiguration('record_diagnostics').perform(context) == 'true':
        database = os.path.expanduser(LaunchConfiguration('database_path').perform(context))
        directory = LaunchConfiguration('diagnostics_dir').perform(context)
        if not directory:
            directory = os.path.join(os.path.dirname(database), 'diagnostics')
        actions.append(Node(
            package='go2_slam_nav', executable='navigation_recorder', name='navigation_recorder',
            parameters=[{'output_dir': directory, 'config_file': params, 'map_database': database,
                         'evaluation_hz': 2.0,
                         'record_obstacle_sensors': LaunchConfiguration(
                             'record_obstacle_sensors').perform(context) == 'true'}],
            output='screen', respawn=True, respawn_delay=2.0,
        ))

    # The bridge is absent during planning-only checks. Its output policy also
    # rejects reverse/lateral commands if a controller or external sender errs.
    if LaunchConfiguration('enable_motion').perform(context) == 'true':
        actions.append(Node(
            package='go2_cmd_processor', executable='sport_ctrl', name='sport_ctrl',
            parameters=[{'enabled': True, 'max_linear_x': 0.5, 'max_angular_z': 1.8}],
            remappings=[('cmd_vel', '/go2_nav/cmd_vel')], output='screen',
        ))
    actions.append(Node(
        package='rviz2', executable='rviz2', name='go2_l1_navigation_rviz', output='screen',
        arguments=['-d', os.path.join(share, 'config', 'nav.rviz')],
        parameters=[{'use_sim_time': False}],
        condition=IfCondition(LaunchConfiguration('use_nav2_rviz')),
    ))
    return actions


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('database_path', default_value='~/.ros/rtabmap_go2_l1.db',
                              description='Existing map database; this launch never resets it'),
        DeclareLaunchArgument('nav2_params_file', default_value=PathJoinSubstitution([
            FindPackageShare('go2_slam_nav'), 'config', 'nav2_params.yaml'])),
        DeclareLaunchArgument('start_localization', default_value='true', choices=['true', 'false'],
                              description='False when the existing localization pipeline is running'),
        DeclareLaunchArgument('localization_profile', default_value='legacy',
                              choices=['legacy', 'aligned_visual', 'reference_visual'],
                              description='Explicit acquisition-time/6DoF localization comparison profiles'),
        DeclareLaunchArgument('odom_bridge', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('record_diagnostics', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('first_door_only', default_value='false', choices=['true', 'false'],
                              description='Saved-lab-map route policy: forbid door2, stop on waypoint failure'),
        DeclareLaunchArgument('record_obstacle_sensors', default_value='false',
                              choices=['true', 'false'],
                              description='Record raw L1/depth scan and full TF for obstacle attribution'),
        DeclareLaunchArgument('diagnostics_dir', default_value=''),
        DeclareLaunchArgument('enable_motion', default_value='false', choices=['true', 'false'],
                              description='Operator opt-in: enable the forward-only Sport command bridge'),
        DeclareLaunchArgument('nav_camera_calibration', default_value=PathJoinSubstitution([
            FindPackageShare('go2_slam_nav'), 'config', 'nav_camera_extrinsics_20261110.json']),
                              description='Optional calibrated depth-scan frame; saved RTAB-Map camera models are retained'),
        DeclareLaunchArgument('use_nav2_rviz', default_value='true', choices=['true', 'false']),
        DeclareLaunchArgument('localize_only', default_value='true', choices=['true']),
        DeclareLaunchArgument('restart_map', default_value='false', choices=['false']),
        DeclareLaunchArgument('use_rviz', default_value='true', choices=['true', 'false']),
        OpaqueFunction(function=launch_setup),
    ])
