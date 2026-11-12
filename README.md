# Unitree Go2 L1 + D435i: RTAB-Map / Nav2

새 지도를 만들 때는 노트북에서 다음 한 줄을 실행합니다. 카메라 재사용/SSH 시작 → 센서 수신 확인 → 새 DB Mapping·RViz → Ctrl+C 후 저장 검사를 묶었습니다. 로봇 이동은 운영자가 수행합니다.

```bash
bash /home/cvr/GH/unitree-go2-slam-nav2/scripts/laptop_slam.sh
```

먼저 설치만 확인하려면 끝에 `check`, 아무것도 시작하지 않고 계획만 보려면 `plan`을 붙입니다. 실제 Go2에서의 새 SSH·Mapping 전체 실행은 아직 검증하지 않았습니다. 드론 튜토리얼 형식의 [Go2 SLAM 따라하기 및 실험 보고서](docs/go2_navigation_validation.html#tutorial-start)에 준비·예상 출력·저장·문제 해결을 정리했습니다.

현재 노트북에서는 아래 명령을 사용합니다. 저장소와 실제 `~/GH/unitree_go2_pr1_ws` 설치를 연결해 두었습니다.

```bash
cd ~/GH/unitree-go2-slam-nav2
bash scripts/laptop_nav.sh check   # 설치 확인, 노드 시작 안 함
bash scripts/laptop_nav.sh view    # Go2/카메라 시작 후 지도·위치 확인, Sport bridge 없음
```

위 `view`를 Ctrl+C로 종료하고 위치 정합을 확인한 뒤, 운영자만 `bash scripts/laptop_nav.sh drive`로 주행 bridge를 켭니다. Goal도 운영자가 지정합니다. 두 번째 인자로 다른 `.db`를 선택할 수 있습니다. Ethernet `eno1`에 연결이 없으면 `view`/`drive`는 ROS 기동 전에 중단합니다.

2026-11-10 설치 점검: 실제 작업공간 빌드 PASS, 기존 DB 복사본 quick_check `ok` / 4,516 keyframes, 로봇과 분리한 ROS 기동에서 1131×1537 지도 로드 PASS. Live 센서·초기 위치 정합·실제 문 통과는 Go2 전원 OFF로 NOT TESTED. 자세한 기록은 같은 HTML의 R6에 있습니다.

This fork adapts Hossein Naderi's Go2 SLAM/Nav2 demo to the **current laptop + stock Go2** experiment: ROS 2 Humble on the laptop, Go2 native odometry, internal L1 LiDAR, and the head-mounted D435i. The original RoboSense launch files remain as legacy references; the default Mapping/Navigation scripts do not start RoboSense or ICP odometry.

## Current data and control routes

- `/utlidar/cloud_base` → camera-clock alignment → `/cloud_base_synced` → 1 s motion-compensated `/assembled_cloud`.
- `/utlidar/robot_odom` → latest RGB stamp → `/robot_odom_fixed` and `odom → base_link`. Set `odom_bridge:=false` only if the existing equivalent bridge is already running.
- `/camera/color/image_raw`, `/camera/color/camera_info`, `/camera/aligned_depth_to_color/image_raw` → RTAB-Map visual registration (`Reg/Strategy=0`). Navigation localizes in a saved database with `Mem/IncrementalMemory=false`, `Mem/LocalizationReadOnly=true`, `map_always_update=false`.
- Sensor restamping follows the previous experiment's approximate latest-camera-stamp convention. It is **not hardware synchronization**. Stale camera input stops synchronized output; cached odometry is not reused beyond 0.5 s.
- `base_link → camera_link = (0.20, 0, 0.09)m` preserves the existing saved-map camera model. RealSense publishes its internal camera frames. The included 2026-11-10 calibration affects only the Nav2 depth-scan frame; it does not rewrite saved keyframes. Disable it for another mount with `nav_camera_calibration:=''` when launching directly.
- DWB → `/go2_nav/cmd_vel_raw` → velocity smoother → `/go2_nav/cmd_vel` → optional `sport_ctrl` → `/api/sport/request`.
- All translation routes enforce `x >= 0`, `y = 0`. Turning is allowed. Negative/lateral commands are clipped again at the Sport encoder; non-finite input sends StopMove. Backup recovery is absent from both behavior trees and the behavior server. This policy covers this Nav2 bridge; a separately running teleoperation or SDK process has its own control path.

## Laptop setup

Do not mix the previous Go2 SLAM/navigation overlays into this workspace. The existing Unitree message workspace is reused; no second RoboSense SDK is needed.

```bash
source /opt/ros/humble/setup.bash
source "$HOME/unitree_ros2/cyclonedds_ws/install/setup.bash"
export GO2_WS_ROOT="$HOME/GH/unitree_go2_pr1_ws"
mkdir -p "$GO2_WS_ROOT/src"
# On this laptop this symlink already exists. For a new checkout, create it once:
# ln -s /absolute/path/unitree-go2-slam-nav2 "$GO2_WS_ROOT/src/unitree-go2-slam-nav2"
cd "$GO2_WS_ROOT"
colcon build --base-paths "$GO2_WS_ROOT/src" --packages-select go2_nav2_critics go2_cmd_processor go2_slam_nav
source install/setup.bash
```

Required installed ROS packages: RTAB-Map (`rtabmap_slam`, `rtabmap_util`, `rtabmap_viz`), Nav2, `depthimage_to_laserscan`, CycloneDDS, and `unitree_api`. Scripts source the existing Unitree setup at `~/unitree_ros2/cyclonedds_ws/install/setup.bash`; override its location with `GO2_UNITREE_SETUP`.

## Operator: start the camera on Go2

On the laptop, open **terminal 1** and connect to the powered robot:

```bash
ssh unitree@192.168.123.18
```

At `ros:foxy(1) ...`, choose `1`. Then run **on Go2**:

```bash
source ~/ros2_realsense_456_ws/activate.bash
ros2 launch realsense2_camera rs_launch.py \
  camera_namespace:=/ camera_name:=camera \
  depth_module.depth_profile:=640x480x30 rgb_camera.color_profile:=640x480x15 \
  enable_color:=true enable_depth:=true enable_infra1:=false enable_infra2:=false \
  enable_sync:=false align_depth.enable:=true pointcloud.enable:=false \
  enable_accel:=false enable_gyro:=false \
  depth_module.emitter_enabled:=1 depth_module.emitter_on_off:=false
```

## Operator: existing-map navigation, initially without motion

On the **laptop, terminal 2**:

```bash
cd ~/GH/unitree-go2-slam-nav2
export GO2_WS_ROOT="$HOME/GH/unitree_go2_pr1_ws"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID=0
export ROS_LOCALHOST_ONLY=0
export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="eno1"/></Interfaces></General></Domain></CycloneDDS>'
bash scripts/run_nav.sh "$HOME/GH/go2_l1_nav2_ws/analysis/saved_map_fix_20261109/navigation_map.db"
```

`eno1`, domain 0, and the DB above are the current laptop's experiment settings. The Ethernet link and camera must be active. The command copies the original DB into `~/go2_maps/nav_sessions/`; it does not modify the original. To inspect the separate 2026-11-10 left-door map candidate, explicitly supply `~/GH/go2_l1_nav2_ws/analysis/left_door_repair_20261110/navigation_map.db` instead. That candidate has not passed a physical door traversal.

The default has **no Sport bridge**. Verify `map → odom → base_link`, initial position/yaw, the actual doorway, both Costmaps, and the real moving leg envelope. A loaded map or a successful build does not establish localization or collision safety.

Only the **operator**, after completing these checks, may stop that session with Ctrl+C and opt in to the motion bridge:

```bash
GO2_ENABLE_MOTION=true bash scripts/run_nav.sh \
  "$HOME/GH/go2_l1_nav2_ws/analysis/saved_map_fix_20261109/navigation_map.db"
```

The operator sends any RViz2 navigation goal and controls the supervised test. Maximum translation is `0.50m/s` (raised from `0.30m/s` at the operator’s request); maximum turn rate is `1.8rad/s`. The higher cap requires a new operator-supervised trial; it is not physically validated. The Sport timeout remains `0.25s`; zero/invalid/stale commands use StopMove (`1003`). No stand-up, dance, or other motion services are exposed by this navigation bridge.

## Optional: mapping into a new DB

With the same camera/network/workspace environment and Navigation stopped:

```bash
bash scripts/run_mapping.sh
# Or choose a new, nonexistent filename:
bash scripts/run_mapping.sh "$HOME/go2_maps/lab_new.db"
```

Mapping refuses an existing DB path. Stop with Ctrl+C to flush it. Navigation uses Localization only; only Nav2 Costmaps update with current obstacles.

## Current geometry and verification

| Setting | Current |
|---|---|
| Global / Local resolution | 0.05 / 0.02 m |
| Footprint | 0.80 × 0.42 m, matching the previous laptop configuration |
| Global / Local padding | 0.01 / 0.02 m |
| Both inflation radii / scaling | 0.45 m / 4.0 |
| Planner / Controller | NavFn Dijkstra / DWB, retained from PR #1 |
| Forward / lateral velocity | 0…0.50 m/s / 0 |

The footprint is a configuration baseline, **not a measured dynamic leg boundary**. The previous PR's 70×40cm and 0.42m inflation remain historical experiments in the same validation record. DWB now restores `Go2WalkingSpeed` and `ObstacleFootprint` in addition to its existing critics. Nonzero translation candidates below 0.20m/s are rejected; zero-translation turns remain available. The padded rectangular boundary is checked at sampled trajectory poses. This is not a measured dynamic leg envelope or a guarantee of continuous collision safety. Initial localization and the 90cm second-door traversal remain NOT TESTED with this port because Go2 is powered off.

Local checks:

```bash
bash -n scripts/_env.sh scripts/run_mapping.sh scripts/run_nav.sh
# After sourcing the built workspace:
python3 -m pytest -q tests
```

See the single [validation record](docs/go2_navigation_validation.html) for R5 results, T00–T10, exact limits, and commit history. Follow [AGENTS.md](AGENTS.md). No GitHub Actions or automatic merge.

## Corner safeguards and automatic evaluation recording

Nonzero DWB translation candidates are limited to **0.20…0.50m/s**, while `min_vel_x=0` retains in-place rotation. `min_speed_theta=0.20rad/s` filters tiny pure turns. `Go2WalkingSpeed` rejects small translation even when mixed with rotation; `ObstacleFootprint` checks the rotated padded boundary. The 0.20m/s threshold is an adjustable trial value informed by the earlier response measurements, not a proven universal walking threshold. Smoother startup/braking can still pass briefly through lower speeds. Commands are never boosted after collision scoring. The maximum yaw rate remains ±1.8rad/s; reverse/lateral translation remains blocked. The current progress checker is unchanged for comparison.

A read-only recorder starts automatically with `view` and `drive`. It sends no motion or parameter-setting requests. It saves:

- `/evaluation`: all candidate velocities, validity/totals, critic costs, and the selected predicted poses at up to 2Hz. DWB short-circuiting remains enabled, so some losing candidates have partial scores.
- Raw/smoothed commands, Sport requests/responses, native/synchronized odometry, robot gait/velocity/foot state, TF, plans, action status and selected ROS logs.
- Exact uint8 raw Local/Global Costmaps, footprints, parameter snapshots and the Sport publisher graph. Images and pointclouds are excluded.

Each session has a unique directory:

```text
~/go2_maps/nav_sessions/<session>/diagnostics/<run>/
  metadata.json
  events.jsonl.gz
  summary.json
```

Receipt timestamps share the same recording clock; this does not make sensor acquisition hardware-synchronous. The writer uses a bounded background queue and reports diagnostic drops instead of blocking the callback. Its drop count does not measure transport losses. Stop the experiment normally with **Ctrl+C** to close the compressed file and write the summary. `evaluations_present=false` means no DWB evaluations were received, for example when no Goal ran. This Humble recorder receives message-only callbacks, so per-message Sport publisher GIDs are always null. The publisher graph lists endpoints but cannot attribute an individual command. Runtime callback failures are counted in `summary.json`; launch restarts the recorder after two seconds into a new recording folder.

To disable logging for a comparison run, use `GO2_RECORD_DIAGNOSTICS=false` before the existing laptop command. To reproduce the recorder smoke check without robot motion, source the workspace, select a nonzero loopback-only DDS domain, and run `python3 tests/recorder_ros_smoke.py`. The test refuses domain 0 and creates diagnostic evaluation/costmap publishers and a metadata request on a remapped diagnostic topic. It creates no Sport command publisher.

### Capture the observations behind doorway obstacles

The ordinary trace does not retain raw LiDAR or depth scans. To distinguish
saved-map walls, sensor projection and stale marking, enable the optional raw
capture when starting a fresh **view** session:

```bash
GO2_RECORD_OBSTACLE_SENSORS=true bash scripts/laptop_nav.sh view "$GO2_TEST_MAP"
```

This keeps motion disabled. It records `/cloud_base_synced` and
`/go2_nav/depth_scan` as base64 CDR, preserving cloud layout, scan NaN/Inf,
frames and acquisition stamps. It also records initial/localization poses and
RTAB-Map Info, removes application downsampling of TF and received DWB
evaluations, and raises the Global Costmap recording limit from 0.2 to 1 Hz.
The default is **off**. It does not recover messages lost before reception,
invent missing DWB evaluations, or synchronize hardware clocks.

For a 40-second capture beside an existing Nav2 session, use another terminal
with the **same ROS environment**; no Nav2 restart or motion activation is needed:

```bash
ros2 run go2_slam_nav navigation_recorder --ros-args \
  -r __node:=door_obstacle_recorder \
  -p record_obstacle_sensors:=true -p duration:=40.0 \
  -p output_dir:="$HOME/go2_maps/door_obstacle_trials"
```

Check `summary.json` for dropped messages and write errors. Raw capture increases
CPU and disk use; the existing queue bounds memory but does not cap total disk
usage. The loopback smoke test verifies lossless capture and no motion
publishers; live recording load and actual doorway passage remain unverified.
See [R32](docs/go2_navigation_validation.html#door-failure-r32) for the first-door
analysis, confirmed limits and next supervised test sequence.
