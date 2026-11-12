"""Expand actual launch descriptions with inert nodes; no process may start."""
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET
import pytest
import yaml
import launch
import launch_ros.actions
from launch.action import Action
from launch.actions import ExecuteProcess, SetLaunchConfiguration

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('motion', ['false', 'true'])
@pytest.mark.parametrize('recording', ['false', 'true'])
@pytest.mark.parametrize('raw_sensors', ['false', 'true'])
def test_l1_navigation_expands_without_starting_any_process(
        monkeypatch, tmp_path, motion, recording, raw_sensors):
    monkeypatch.setenv("ROS_LOG_DIR", str(tmp_path / "logs"))
    recorded = []
    class RecordNode(Action):
        def __init__(self, **settings):
            super().__init__(condition=settings.get('condition'))
            self.settings = settings
        def execute(self, context):
            recorded.append(self.settings)
    def reject_process(*args, **kwargs):
        raise AssertionError('Starting a process is forbidden in this test')
    monkeypatch.setattr(launch_ros.actions, 'Node', RecordNode)
    monkeypatch.setattr(ExecuteProcess, 'execute', reject_process)
    database = tmp_path/'synthetic.db'; database.write_bytes(b'inert launch placeholder')
    description = runpy.run_path(str(ROOT/'go2_slam_nav/launch/nav.launch.py'))['generate_launch_description']()
    service = launch.LaunchService()
    service.include_launch_description(launch.LaunchDescription([
        SetLaunchConfiguration('database_path', str(database)),
        SetLaunchConfiguration('enable_motion', motion),
        SetLaunchConfiguration('record_diagnostics', recording),
        SetLaunchConfiguration('record_obstacle_sensors', raw_sensors),
        SetLaunchConfiguration('use_nav2_rviz', 'false'), *description.entities]))
    assert service.run() == 0
    assert not any(n['package'] in ['rslidar_sdk','rtabmap_odom','go2_camera_bringup'] for n in recorded)
    assert any(n.get('executable') == 'sensor_time_sync' for n in recorded)
    rtab = next(n for n in recorded if n.get('executable') == 'rtabmap')
    assert rtab['parameters'][0]['Mem/IncrementalMemory'] == 'false'
    assert rtab['parameters'][0]['Mem/LocalizationReadOnly'] == 'true'
    assert rtab['parameters'][0]['Reg/Strategy'] == '0'
    assert any(n.get('executable') == 'sport_ctrl' for n in recorded) == (motion == 'true')
    if motion == 'true':
        bridge = next(n for n in recorded if n.get('executable') == 'sport_ctrl')
        cfg = yaml.safe_load((ROOT/'go2_slam_nav/config/nav2_params.yaml').read_text())
        dwb = cfg['controller_server']['ros__parameters']['FollowPath']
        smoother = cfg['velocity_smoother']['ros__parameters']
        assert (bridge['parameters'][0]['max_linear_x'] == dwb['max_vel_x'] ==
                dwb['max_speed_xy'] == smoother['max_velocity'][0])
    controllers = [n for n in recorded if n.get('name')=='controller_server']
    assert controllers[0]['remappings'] == [('cmd_vel','/go2_nav/cmd_vel_raw')]
    assert len([n for n in recorded if n.get('executable')=='lifecycle_manager']) == 1
    assert not any(n.get('package')=='rviz2' for n in recorded)
    assert any(n.get('executable') == 'navigation_recorder' for n in recorded) == (recording == 'true')
    if recording == 'true':
        recorder = next(n for n in recorded if n.get('executable') == 'navigation_recorder')
        assert recorder['parameters'][0]['record_obstacle_sensors'] == (raw_sensors == 'true')


def test_all_nav2_translation_and_recovery_routes_obey_forward_only_policy():
    cfg = yaml.safe_load((ROOT/'go2_slam_nav/config/nav2_params.yaml').read_text())
    dwb=cfg['controller_server']['ros__parameters']['FollowPath']
    assert dwb['min_vel_x'] == 0 and dwb['min_vel_y'] == dwb['max_vel_y'] == 0
    smoother=cfg['velocity_smoother']['ros__parameters']
    assert smoother['min_velocity'][:2] == [0.,0.]
    assert smoother['max_velocity'][1] == 0
    assert cfg['behavior_server']['ros__parameters']['behavior_plugins'] == ['wait']
    for path in (ROOT/'go2_slam_nav/behavior_trees').glob('*.xml'):
        tags={n.tag for n in ET.parse(path).iter()}
        assert not tags & {'BackUp','DriveOnHeading','AssistedTeleop'}
