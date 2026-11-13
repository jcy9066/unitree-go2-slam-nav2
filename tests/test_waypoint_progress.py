from pathlib import Path
import xml.etree.ElementTree as ET
import yaml

ROOT=Path(__file__).parents[1]


def test_through_pose_capture_window_covers_maximum_travel_between_updates():
    cfg=yaml.safe_load((ROOT/'go2_slam_nav/config/nav2_params.yaml').read_text())
    tree=ET.parse(ROOT/'go2_slam_nav/behavior_trees/forward_navigation_through_poses.xml')
    hz=float(tree.find('.//RateController').attrib['hz'])
    radius=float(tree.find('.//RemovePassedGoals').attrib['radius'])
    speed=cfg['controller_server']['ros__parameters']['FollowPath']['max_vel_x']
    assert speed/hz < 2*radius  # a straight pass cannot jump the entire window
    # The verified exit is 0.75m beyond the first-door reference. Do not mark it
    # passed while the padded 0.72m body is still straddling the portal.
    assert radius + .36 < .75
