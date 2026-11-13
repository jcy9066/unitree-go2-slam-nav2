"""No-process check: mapping unchanged, localization has one TF owner."""
from pathlib import Path
from types import SimpleNamespace
import runpy
import pytest
from launch import LaunchContext
import launch_ros.actions

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize('localization,enabled', [(True,True),(True,False),(False,True)])
def test_visual_yaw_profile_and_database_protection(monkeypatch, tmp_path, localization, enabled):
    monkeypatch.setattr(launch_ros.actions,'Node',lambda **kw: SimpleNamespace(**kw))
    db=tmp_path/'map.db'
    if localization:db.write_bytes(b'protected original')
    c=LaunchContext();c.launch_configurations.update(localize_only=str(localization).lower(),
        visual_heading_correction=str(enabled).lower(),database_path=str(db),grid_sensor='2')
    nodes=runpy.run_path(str(ROOT/'go2_slam_nav/launch/l1_rgbd.launch.py'))['launch_setup'](c)
    vo=[n for n in nodes if n.executable=='rgbd_odometry']
    assert bool(vo)==(localization and enabled)
    if vo:assert vo[0].parameters[0]['publish_tf'] is False
    sync=next(n for n in nodes if n.executable=='sensor_time_sync')
    assert sync.parameters[0]['visual_heading']==(localization and enabled)
    rtab=next(n for n in nodes if n.executable=='rtabmap').parameters[0]
    assert rtab['Reg/Strategy']=='0' and not any(k.startswith('Icp/') for k in rtab)
    assert rtab['Mem/IncrementalMemory']==str(not localization).lower()
    if localization:assert db.read_bytes()==b'protected original'
    assert not any(n.package=='go2_cmd_processor' for n in nodes)
