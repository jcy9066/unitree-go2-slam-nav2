---
name: go2-localization-verify
description: Check RTAB-Map localization from a saved DB, ICP odometry, map-to-odom TF, initial pose and temporal alignment. Use when the map loads but robot pose is wrong.
---

# Localization verification

## Scope
Do not modify or re-map an existing RTAB-Map database while solving a Nav2 startup problem.

## Procedure
1. Read `AGENTS.md`, `run_nav.sh`, and the `database_path` logic in all launch files.
2. Confirm the original DB is copied into a session path. Ensure `restart_map:=false`, `localize_only:=true` and `Mem/IncrementalMemory=false`.
3. Confirm `/rslidar_points`, ICP Odometry, `/odom`, `map → odom → base_link`, and `base_link → base_laser` sources and timestamps.
4. Check the robot's position and yaw against the RViz map; map visualization alone is not localization success.
5. Check whether a map transform is being published by another active localization node. Avoid competing `map → odom` publishers.
6. If localization fails, separate an incorrect starting pose, bad ICP registration, poor scan overlap, stale timestamps, and wrong LiDAR TF. Collect logs before tuning.
7. Do not send any navigation goal until the user/operator confirms a correct initial pose.

## Evidence
Record DB path, session copy, localization params, TF source, observed pose, failure message and status. Keep localization changes in a separate task/branch unless the user directs otherwise.
