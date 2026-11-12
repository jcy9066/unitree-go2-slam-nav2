"""Regress the observed loss of all depth rays after a body-zero map seed."""
from pathlib import Path
import yaml

ROOT = Path(__file__).parents[1]


def test_aligned_global_keeps_wall_rays_but_excludes_observed_floor():
    base = yaml.safe_load((ROOT/'go2_slam_nav/config/nav2_params.yaml').read_text())
    overlay = yaml.safe_load((ROOT/'go2_slam_nav/config/nav2_aligned_visual_height.yaml').read_text())
    local = base['local_costmap']['local_costmap']['ros__parameters']['obstacle_layer']
    global_layer = overlay['global_costmap']['global_costmap']['ros__parameters']['obstacle_layer']
    # Recorded stationary depth rays: odom z=0.262..0.315, map z=-0.133..-0.055.
    # Their physical scene is identical; a map floor/body datum must not erase it.
    assert local['min_obstacle_height'] <= .262 <= .315 <= local['max_obstacle_height']
    for key in ('l1', 'depth_scan'):
        limits = global_layer[key]
        assert limits['min_obstacle_height'] <= -.133 <= -.055 <= limits['max_obstacle_height']
        assert -.281 < limits['min_obstacle_height']  # highest observed floor point
    assert local['min_obstacle_height'] == .1  # odom datum remains unchanged
