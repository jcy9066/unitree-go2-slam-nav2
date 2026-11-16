# Unitree Go2 L1 + D435i: RTAB-Map / Nav2

## 현재 주행 범위와 제한

운영자 보고와 2026-11-12 저장 주행 로그를 기준으로 정리했습니다. 지도는 **사전에 Mapping한 창학관 3층 지도**를 사용합니다. 아래 결과는 운영자의 목표 지정·초기 위치 보정·방향 전환을 포함한 주행 결과입니다.

| 항목 | 확인된 동작과 제한 |
|---|---|
| 초기 위치 | Nav2 시작 시 자동 초기 위치 정합이 원활하지 않아 RViz2의 **2D Pose Estimate**로 위치·방향을 수동 설정한 뒤 출발 |
| 연구실 → 교수님 방 문앞 | 소구간 목표(waypoint)를 조금씩 여러 번 지정하여 Nav2 주행 가능 |
| 도착 후 180° 회전 | 교수님 방 문앞에서 Nav2를 통한 180° 방향 전환을 완료하지 못함. 원인은 미확정 |
| 교수님 방 문앞 → 연구실 | 운영자가 Go2를 수동으로 180° 회전한 뒤, 소구간 목표를 반복 지정하여 Nav2 복귀 가능 |
| 전체 자동 왕복 | 초기 위치 설정·목표 지정·도착 후 방향 전환에 수동 개입 필요. 무개입 전체 미션 완료는 미달성 |
| Mapping | 기존 창학관 3층 지도 작성 결과 사용. 신규 서버에서 설치부터 새 Mapping까지 실행한 결과는 미검증 |

저장 로그의 주요 근거(2026-11-12 KST):

- **21:22:39–21:23:46:** FollowWaypoints 실행에서 첫 점은 21:22:51에 성공했고 두 번째 점은 취소됐습니다.
- **이후:** 교수님 방 방향 및 복귀 방향으로 NavigateToPose 목표를 여러 번 교체한 기록이 있습니다. 목표 교체(preemption)에 따른 ABORTED 상태는 별도로 구분합니다.
- **21:27:12–21:29:05:** 복귀 방향 목표를 나눠 지정했고 마지막 Goal은 21:29:05에 SUCCEEDED입니다. 수동 180° 회전은 운영자 관측으로 기록합니다.

원본은 실험 PC의 `~/go2_maps/nav_sessions/20261112_194202_3012154/diagnostics/20261112_211808_7a89824a/events.jsonl.gz`에 있습니다. 상세 이력은 [단일 검증 기록](docs/go2_navigation_validation.html)에 보존합니다. 이번 문서 갱신에서 로봇 이동이나 새로운 실기 시험을 수행하지 않았습니다.

## 환경 설치: Conda `go2_nav2`

현재 PC의 Ubuntu 22.04 x86_64와 기존 Conda Python **3.14.7**을 기준으로 구성합니다. ROS 2는 Humble, Nav2는 1.1.20, RTAB-Map은 0.23.13입니다. 패키지·채널·소스 commit·빌드·검증 설정은 **[environment.json](environment.json)** 한 파일에서 관리합니다. Conda가 이미 설치돼 있어야 합니다.

저장소 루트에서 기존 설치 스크립트 한 번으로 환경 생성부터 시작합니다.

```bash
bash scripts/install_student.sh
```

스크립트는 `conda create --name go2_nav2`로 **기존 Conda의 기본 envs 경로**에 환경을 생성합니다. 저장소 안에 가상환경이나 별도 설치 폴더를 만들지 않습니다. 선언한 의존성을 설치하고, Unitree 메시지·`rtabmap_viz`·프로젝트 패키지를 임시 작업 폴더에서 빌드해 해당 Conda 환경에 설치합니다. 원본 로봇 연결·망 설정·지도·주행 설정은 이 설치 명령에서 다루지 않습니다.

모든 설치·빌드·Python/ROS 패키지·메시지·플러그인 검증이 성공한 마지막에만 다음 문구가 출력됩니다. 실패하면 오류로 종료하고 이 문구는 출력하지 않습니다.

```text
go2_nav2 환경 설정이 완료되었습니다.
```

설치 후에는 일반 Conda 방식으로 활성화합니다.

```bash
conda activate go2_nav2
bash scripts/install_student.sh verify
```

설치 동작 없이 목록만 확인하려면 `bash scripts/install_student.sh plan`, 명세와 ROS 메타데이터를 대조하려면 `python3 scripts/environment.py validate`를 사용합니다. 설치 기록·해결된 패키지 목록·빌드 로그는 선택된 Conda 환경의 `.go2_nav2_setup/`에 저장됩니다. 기존에 직접 만든 `go2_nav2`가 있으면 자동 덮어쓰지 않고 중단합니다.

`rtabmap_viz`는 RViz2와 별도 GUI입니다. 2026-11-05/09의 실행 기록과 현재 Mapping 스크립트의 사용을 확인해 유지합니다. Conda 채널에 해당 바이너리가 없어 현재 PC와 같은 **0.23.13의 공식 소스 commit**으로 빌드합니다. Nav2 주행은 이 GUI를 끄고 RViz2를 사용합니다.

검증 범위: Conda 의존성 dry-run에서 **58개 요청/927개 패키지 해결**, 설치·실행 진입의 오프라인 회귀 **21개 통과**. 이번 작업에서 새 Conda 환경의 실제 전체 설치·소스 빌드·GUI 실행·로봇 주행은 수행하지 않았습니다. 실제 설치 성공 여부는 위 명령의 검증과 완료 문구로 확인해야 합니다.

## 기존 노트북 실행 경로

아래는 기존 시스템 ROS 환경의 실험 재현 기록입니다. 새 Conda 설치는 위 절차를 사용하며 두 환경의 overlay를 섞지 않습니다.

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

현재 소스의 navigation 설정은 두 문 허용(`GO2_FIRST_DOOR_ONLY=false`), Footprint 70×36cm와 양쪽 padding 1cm(검사 72×38cm), Local inflation 20cm / Global inflation 30cm입니다. 0.5m/s에서 실제 다리 스윕과 제동거리는 미검증입니다. `aligned_visual` Localization은 RGB-D odometry의 상대 방향으로 native Go2 yaw drift를 제한하고 센서 원본 취득 시각을 보존합니다. 기존 Mapping/legacy 모드의 카메라 시각 재표기와 구분합니다. 정지 yaw와 동결 경로의 과거 비교는 [R37 기록](docs/go2_navigation_validation.html#heading-fix-r37), 복귀·바닥 필터·진척 검사 변경은 [R47 기록](docs/go2_navigation_validation.html#known-space-return-r47)을 참조하세요.

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
| Footprint | 0.70 × 0.36 m |
| Global / Local padding | 0.01 / 0.01 m |
| Global / Local inflation radius | 0.30 / 0.20 m |
| Inflation scaling | 4.0 |
| Planner / Controller | NavFn Dijkstra / DWB, retained from PR #1 |
| Forward / lateral velocity | 0…0.50 m/s / 0 |

The footprint is a configuration baseline, **not a measured dynamic leg boundary**. The previous PR's 70×40cm and 0.42m inflation remain historical experiments in the same validation record. DWB now restores `Go2WalkingSpeed` and `ObstacleFootprint` in addition to its existing critics. Nonzero translation candidates below 0.20m/s are rejected; zero-translation turns remain available. The padded rectangular boundary is checked at sampled trajectory poses. This is not a measured dynamic leg envelope or a guarantee of continuous collision safety. Initial localization currently requires the operator’s 2D Pose Estimate. The supervised route and manual turn are documented above; the dynamic leg envelope and autonomous complete mission remain unverified.

Local checks:

```bash
bash -n scripts/_env.sh scripts/run_mapping.sh scripts/run_nav.sh
# After sourcing the built workspace:
python3 -m pytest -q tests
```

See the single [validation record](docs/go2_navigation_validation.html) for R5 results, T00–T10, exact limits, and commit history. Follow [AGENTS.md](AGENTS.md). No GitHub Actions or automatic merge.

## Corner safeguards and automatic evaluation recording

Nonzero DWB translation candidates are limited to **0.20…0.50m/s**, while `min_vel_x=0` retains in-place rotation. `min_speed_theta=0.60rad/s` filters tiny pure turns. `Go2WalkingSpeed` rejects small translation even when mixed with rotation; `ObstacleFootprint` checks the rotated padded boundary. The 0.20m/s threshold is an adjustable trial value informed by the earlier response measurements, not a proven universal walking threshold. Smoother startup/braking can still pass briefly through lower speeds. Commands are never boosted after collision scoring. The maximum yaw rate remains ±1.8rad/s; reverse/lateral translation remains blocked. `PoseProgressChecker` recognizes either 0.5m translation or 0.10rad rotation within 10 seconds. This configured rotation support does not establish successful 180° turning at the professor’s room entrance.

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

### First-door-only laboratory round trip

For the saved lab map used in R32, enable an optional route policy that keeps
the second door out of both Costmaps and stops at a failed waypoint:

```bash
export GO2_TEST_MAP="$HOME/GH/go2_l1_nav2_ws/analysis/left_door_repair_20261110/navigation_map.db"
GO2_FIRST_DOOR_ONLY=true GO2_RECORD_OBSTACLE_SENSORS=true \
  bash scripts/laptop_nav.sh view "$GO2_TEST_MAP"
```

This is still **view**, with no motion bridge. The route mask is a virtual
restriction and never edits the RTAB-Map DB or describes a new physical wall.
The launch checks the saved occupancy hash, geometry and mask checksum before
starting nodes; other maps are rejected. The default route mode is unchanged.

The intended mission is lab → first door → professor's room entrance → first
door → lab. The operator selects current waypoints and headings after verifying
localization and body clearance. First-door failure must stop the mission,
without falling back to door 2. The mask enforces that route preference; it does
not solve the first-door registration or walking-clearance problems. See
[R33](docs/go2_navigation_validation.html#first-door-r33) for the planner-only
comparison and the two-terminal startup commands.

### Camera `bad_alloc caught` messages

Do not infer exhausted RAM from this message alone. In R34 the Go2 had
6,209 MiB available and RGB/aligned-depth reception continued while the camera
used Foxy Fast DDS 2.1.4. The same log text exists in Fast DDS discovery-data
deserialization; the exact offending packet was not identified.

The tested camera backend remains `rmw_fastrtps_cpp`. A Cyclone DDS comparison
crashed this device's camera node and was reverted. The payload exposes
`GO2_CAMERA_RMW_IMPLEMENTATION` for explicit separate experiments, not as a
recommendation to switch this device. Stream profiles and the laptop RMW are
unchanged. The SSH payload disables interactive job control so `setsid` retains
the owned launch PID/group for cleanup. See [R34](docs/go2_navigation_validation.html#camera-dds-r34)
for before/failure/restoration evidence and the remaining limitations.
