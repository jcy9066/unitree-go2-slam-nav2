"""Expand comparison nodes without DDS, a robot, or database writes."""
from pathlib import Path
from types import SimpleNamespace
import runpy

import pytest
from launch import LaunchContext
import launch_ros.actions

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('reference', ['false', 'true'])
def test_aligned_visual_uses_source_time_full_pose_and_readonly_db(monkeypatch, tmp_path, reference):
    monkeypatch.setattr(launch_ros.actions, 'Node', lambda **kw: SimpleNamespace(**kw))
    db = tmp_path/'existing.db'; db.write_bytes(b'unchanged')
    context = LaunchContext()
    context.launch_configurations.update(database_path=str(db), reference_camera=reference,
                                         use_sim_time='false', publish_map_tf='true')
    nodes = runpy.run_path(str(ROOT/'go2_slam_nav/launch/aligned_visual_localization.launch.py'))['launch_setup'](context)
    assert not any(n.package in ('go2_cmd_processor', 'nav2_controller') for n in nodes)
    sync = next(n for n in nodes if n.executable == 'sensor_time_sync').parameters[0]
    assert sync['stamp_mode'] == 'source' and sync['visual_heading'] is False
    rtab = next(n for n in nodes if n.executable == 'rtabmap').parameters[0]
    assert rtab['Reg/Force3DoF'] == 'false' and rtab['odom_sensor_sync'] is True
    assert rtab['Mem/IncrementalMemory'] == 'false'
    assert rtab['Mem/LocalizationReadOnly'] == 'true'
    assert rtab['map_always_update'] is False and rtab['subscribe_scan_cloud'] is False
    assert db.read_bytes() == b'unchanged'
    camera = next(n for n in nodes if n.executable == 'static_transform_publisher')
    assert camera.arguments[0] == ('0.34' if reference == 'true' else '0.2')


@pytest.mark.parametrize('profile', ['aligned_visual', 'reference_visual'])
def test_unvalidated_comparison_profile_cannot_enable_motion(tmp_path, profile):
    ctx = LaunchContext()
    ctx.launch_configurations.update(localization_profile=profile, enable_motion='true',
                                     first_door_only='false')
    import ament_index_python.packages
    share = ament_index_python.packages.get_package_share_directory('go2_slam_nav')
    ctx.launch_configurations['nav2_params_file'] = str(Path(share)/'config/nav2_params.yaml')
    with pytest.raises(RuntimeError, match='view-only'):
        runpy.run_path(str(ROOT/'go2_slam_nav/launch/nav.launch.py'))['launch_setup'](ctx)
