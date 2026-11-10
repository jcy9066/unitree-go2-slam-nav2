---
name: go2-config-audit
description: Inspect Go2 Nav2 config, footprint, inflation, costmap resolution, LiDAR and TF without moving the robot. Use for parameter audits and narrow-door planning analysis.
---

# Go2 configuration audit

## Read
- `AGENTS.md`
- `go2_slam_nav/config/nav2_params.yaml`
- `go2_slam_nav/launch/nav.launch.py`, `mapping.launch.py`, `rtab_lidar.launch.py`
- `docs/go2_navigation_validation.html` sections 01–03

## Procedure
1. Record the branch and before values. Confirm `main` remains unchanged.
2. Audit local and global Costmap separately: `resolution`, `footprint`, `footprint_padding`, `inflation_radius`, `cost_scaling_factor`, observation sources, marking and clearing.
3. Audit the `base_link → base_laser` static transform and actual sensor mounting assumption.
4. Calculate inscribed radius and circumscribed radius from the padded polygon. Report calculations, units and assumptions. A radius value alone does not prove a collision-free path.
5. If ROS 2 is available, use read-only `ros2 param get`, `ros2 topic info` and TF queries to distinguish effective runtime settings from YAML.
6. Compare obstacle cells with inflated cost cells. Do not infer a true wider opening from a visually smaller cost field alone.
7. Report before → after, why, PASS/FAIL/NOT TESTED, exact files/lines and risk.

## Do not
- Do not change DWB or Planner algorithms solely to improve results visually.
- Do not assert 70×40 cm is the measured moving leg envelope.
- Do not command Go2 motion.
- Do not edit the original RTAB-Map .db.

## Output
A short table: item, expected, observed, evidence, status, next action. Update the canonical HTML only after changes or new evidence.
