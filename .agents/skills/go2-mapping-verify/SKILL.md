---
name: go2-mapping-verify
description: Verify the Unitree Go2 LiDAR-only RTAB-Map mapping launch, new DB creation, and safe DB retention. Use for mapping setup or map database problems.
---

# Mapping verification

## Scope
Mapping is separate from Nav2 localization. Do not confuse dynamic Nav2 Costmap updates with permanent RTAB-Map mapping.

## Checks
1. Read `AGENTS.md`, `run_mapping.sh`, `scripts/_env.sh`, `go2_slam_nav/launch/mapping.launch.py` and `rtab_lidar.launch.py`.
2. Confirm `localize_only:=false`, `restart_map:=false`, and the explicit `database_path`.
3. Confirm the output path does not already exist. Stop rather than overwrite any .db.
4. Run `bash -n run_mapping.sh scripts/_env.sh` as an offline check.
5. Check ROS package, LiDAR topic, TF and ICP dependencies without commanding motion.
6. For live Mapping, provide the operator this command, but do not execute it against hardware automatically:
   `bash run_mapping.sh [new_map.db]`.
7. Require evidence that a populated DB is readable and valid after stopping the ROS process. A non-empty file alone is not proof the map is correct.
8. Track source-map, output-map, file size, completion timestamp, map appearance and runtime errors.

## Output
PASS/FAIL/BLOCKED/NOT TESTED per step; retain original DB, and link evidence in `docs/go2_navigation_validation.html`. Never call GitHub Actions.
