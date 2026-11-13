# Unitree Go2 L1 + D435i: RTAB-Map / Nav2

Unitree Go2의 내장 L1 LiDAR, D435i, native odometry를 이용하는 ROS 2 Humble 프로젝트입니다. RTAB-Map으로 지도를 작성하고, 주행에서는 저장된 지도에 위치를 추정하면서 Nav2(NavFn + DWB)를 사용합니다. 기본 파이프라인은 RoboSense나 ICP odometry를 시작하지 않습니다.

2026-11-13 [PR #2](https://github.com/jcy9066/unitree-go2-slam-nav2/pull/2)가 `main`에 병합되었습니다. L1·RGB-D 주행 코드와 Conda 설치 스크립트가 포함되며, **코드 통합과 실제 Conda 설치·주행 검증은 구분합니다.**

## 문서와 설정 기준

| 파일 | 역할과 현재 상태 |
|---|---|
| [environment.json](environment.json) | 의존성·채널·버전·외부 소스 SHA·빌드·검증 설정의 단일 기준 |
| [install_student.sh](install_student.sh) | 기존 Conda에서 `go2_nav2` 생성부터 설치·빌드·검증까지 수행하는 진입점 |
| [setup_maps.sh](setup_maps.sh) | 지도 DB의 무손실 압축·복원·검증. Git 공유는 사용자가 수행 |
| [검증 HTML](docs/go2_navigation_validation.html) | 프로젝트 소개·주행영상·개념·루트 실행 명령과 지도 준비 절차 |
| [환경 검증 R56](docs/go2_navigation_validation.html#conda-setup-r56) | 현재 PC용 설치 구현, 과거 운용 근거, 검증 범위와 미실행 항목 |
| [고정 과거 기록 R50](https://github.com/jcy9066/unitree-go2-slam-nav2/blob/7aa21b2/docs/go2_navigation_validation.html) | HTML 개편 전 튜토리얼과 R1~R50의 실험·실패 이력 |

## 현재 주행 범위와 제한

운영자 보고와 2026-11-12 저장 주행 로그를 기준으로 정리했습니다. 지도는 **사전에 Mapping한 창학관 3층 지도**를 사용합니다. 아래 결과는 운영자의 목표 지정·초기 위치 보정·방향 전환을 포함한 주행 결과입니다.

| 항목 | 확인된 동작과 제한 |
|---|---|
| 초기 위치 | Nav2 시작 시 자동 초기 위치 정합이 원활하지 않아 RViz2의 **2D Pose Estimate**로 위치·방향을 수동 설정한 뒤 출발 |
| 연구실 → 교수님 방 문앞 | 소구간 목표(waypoint)를 조금씩 여러 번 지정하여 Nav2 주행 가능 |
| 도착 후 180° 회전 | 교수님 방 문앞에서 Nav2를 통한 180° 방향 전환을 완료하지 못함. 원인은 미확정 |
| 교수님 방 문앞 → 연구실 | 운영자가 Go2를 수동으로 180° 회전한 뒤, 소구간 목표를 반복 지정하여 Nav2 복귀 가능 |
| 전체 자동 왕복 | 초기 위치 설정·목표 지정·도착 후 방향 전환에 수동 개입 필요. 무개입 전체 미션 완료는 미달성 |
| Mapping | 기존 창학관 3층 지도 작성 결과 사용. 새 Conda 환경에서의 Mapping 실행은 미검증 |

저장 로그의 주요 근거(2026-11-12 KST):

- **21:22:39–21:23:46:** FollowWaypoints 실행에서 첫 점은 21:22:51에 성공했고 두 번째 점은 취소됐습니다.
- **이후:** 교수님 방 방향 및 복귀 방향으로 NavigateToPose 목표를 여러 번 교체한 기록이 있습니다. 목표 교체(preemption)에 따른 ABORTED 상태는 별도로 구분합니다.
- **21:27:12–21:29:05:** 복귀 방향 목표를 나눠 지정했고 마지막 Goal은 21:29:05에 SUCCEEDED입니다. 수동 180° 회전은 운영자 관측으로 기록합니다.

원본은 실험 PC의 `~/go2_maps/nav_sessions/20261112_194202_3012154/diagnostics/20261112_211808_7a89824a/events.jsonl.gz`에 있습니다. 상세 이력은 [단일 검증 기록](docs/go2_navigation_validation.html)에 보존합니다. 이번 문서 갱신에서 로봇 이동이나 새로운 실기 시험을 수행하지 않았습니다.

## 환경 설치: Conda `go2_nav2`

현재 PC의 **Ubuntu 22.04 x86_64**를 대상으로 구성합니다. 새 `go2_nav2` 환경의 Python은 RoboStack Humble 패키지의 호환 ABI에 맞춘 **3.14.7**입니다. 기존 Conda base 환경의 Python 버전을 바꿀 필요는 없습니다. ROS 2는 Humble, Nav2는 1.1.20, RTAB-Map은 0.23.13입니다. 패키지·채널·소스 commit·빌드·검증 설정은 **[environment.json](environment.json)** 한 파일에서 관리합니다. Conda가 이미 설치돼 있어야 합니다.

저장소 루트에서 기존 설치 스크립트 한 번으로 환경 생성부터 시작합니다.

```bash
bash install_student.sh
```

스크립트는 `conda create --name go2_nav2`로 **기존 Conda의 기본 envs 경로**에 환경을 생성합니다. 저장소 안에 가상환경이나 별도 설치 폴더를 만들지 않습니다. 선언한 의존성을 설치하고, Unitree 메시지·`rtabmap_viz`·프로젝트 패키지를 임시 작업 폴더에서 빌드해 해당 Conda 환경에 설치합니다. 원본 로봇 연결·망 설정·지도·주행 설정은 이 설치 명령에서 다루지 않습니다.

모든 설치·빌드·Python/ROS 패키지·메시지·플러그인 검증이 성공한 마지막에만 다음 문구가 출력됩니다. 실패하면 오류로 종료하고 이 문구는 출력하지 않습니다.

```text
go2_nav2 환경 설정이 완료되었습니다.
```

설치 후에는 일반 Conda 방식으로 활성화합니다.

```bash
conda activate go2_nav2
bash install_student.sh verify
```

설치 동작 없이 목록만 확인하려면 `bash install_student.sh plan`, 명세와 ROS 메타데이터를 대조하려면 `bash install_student.sh validate`를 사용합니다. 설치 기록·해결된 패키지 목록·빌드 로그는 선택된 Conda 환경의 `.go2_nav2_setup/`에 저장됩니다. 기존에 직접 만든 `go2_nav2`가 있으면 자동 덮어쓰지 않고 중단합니다. 이 설치기로 만든 환경을 다시 설치할 때도 검증이 끝나기 전에는 완료 상태로 기록하지 않습니다.

설치 후 `conda activate go2_nav2`와 `bash run_nav.sh check`로 노드를 시작하지 않고 패키지를 확인할 수 있습니다. 실시간 실행에는 운영자가 `GO2_NET_IFACE`를 지정합니다. 새 Conda 셸에 기존 시스템 ROS overlay를 섞어 사용하지 않습니다.

`rtabmap_viz`는 RViz2와 별도 GUI입니다. 2026-11-05/09의 실행 기록과 현재 Mapping 스크립트의 사용을 확인해 유지합니다. Conda 채널에 해당 바이너리가 없어 현재 PC와 같은 **0.23.13의 공식 소스 commit**으로 빌드합니다. Nav2 주행은 이 GUI를 끄고 RViz2를 사용합니다.

2026-11-13까지 기록된 검증 범위는 다음과 같습니다. README 갱신에서 설치나 주행 시험을 새로 수행하지 않았습니다.

| 범위 | 상태와 근거 |
|---|---|
| 환경 명세 | PASS: `validate`로 JSON과 ROS `package.xml` 의존성 대조 |
| Conda 의존성 해석 | PASS: dry-run에서 58개 요청 / 927개 패키지 해결. 실제 설치 결과와 구분 |
| 소스 회귀 | PASS: 기존 시스템 ROS와 Unitree·프로젝트 overlay를 불러온 환경에서 126개 통과. 설치·진입 오프라인 검사 21개 포함 |
| 새 Conda 실제 설치·빌드 | NOT TESTED: 환경 생성, 패키지 설치, Unitree·rtabmap_viz·프로젝트 소스 컴파일 미실행 |
| 새 Conda GUI·ROS 실행 | NOT TESTED: RViz2·rtabmap_viz, 센서·TF, Mapping·저장 지도 실행 미검증 |
| 무개입 전체 왕복 | FAIL: 기존 운용에서 초기 위치·소구간 목표 지정·180° 회전에 수동 개입 필요. 새 Conda 주행은 NOT TESTED |

실제 설치 성공 여부는 설치 명령의 검증과 완료 문구로 확인해야 합니다. 소스 회귀와 모의 설치 검사는 새 Conda 환경의 컴파일·GUI·실물 주행 성공을 증명하지 않습니다.

## 지도 공유: `setup_maps.sh`

지도는 `maps/<지도 이름>/`에서 관리합니다. Git LFS에는 `*.db.zst`, 일반 Git에는 함께 생성된 `*.db.zst.json`을 올립니다. 원본 `.db`와 SQLite 임시 파일은 Git에서 제외합니다. 압축 도구·Git LFS 의존성과 압축 설정은 `environment.json`에 선언합니다.

```text
maps/창학관 3층/
├── rtabmap.db           # 로컬 원본 또는 복원본, Git 제외
├── rtabmap.db.zst       # 무손실 압축본, Git LFS
└── rtabmap.db.zst.json  # 자동 생성한 크기·SHA256·관측 지점 수
```

현재 창학관 3층 지도 원본은 사용자가 넣은 상태이며, **실제 지도 압축·업로드는 아직 수행하지 않았습니다.** 아래 Git 공유가 완료된 뒤에 다른 PC에서 Mapping 없이 복원할 수 있습니다.

| 명령 | 동작 |
|---|---|
| `bash setup_maps.sh plan` | 파일을 만들지 않고 처리 예정 지도만 표시 |
| `bash setup_maps.sh` | 전체 지도 처리: 압축본이 있으면 복원·기존 DB 확인, DB만 있으면 압축 |
| `bash setup_maps.sh pack "창학관 3층"` | 지정 지도 압축 및 왕복 무결성 검사 |
| `bash setup_maps.sh restore "창학관 3층"` | 지정 지도 복원. 기존 DB와 내용이 다르면 보존하고 중단 |
| `bash setup_maps.sh verify "창학관 3층"` | 압축본·DB 크기와 SHA256, SQLite 무결성 검사 |

지도 이름을 생략하면 `maps/` 아래 모든 지도 폴더를 처리합니다. 스크립트 경로를 지정하면 다른 작업 디렉터리에서도 실행할 수 있습니다. `setup_maps.sh`는 로컬 파일만 처리하고 Git 명령이나 ROS 노드를 실행하지 않습니다.

새 지도를 공유하는 PC에서는 Mapping을 정상 종료한 독립 DB를 지도 폴더에 넣고 `pack`을 실행합니다. `-journal`, `-wal`, `-shm`이 있거나 WAL 모드인 DB는 자동 수정하지 않고 중단합니다. 부수 파일을 임의로 지우지 말고 저장 상태를 확인하세요. 기존 압축본 갱신은 `pack --replace-archive "창학관 3층"`으로 명시하며 원본 DB는 변경하지 않습니다.

이후 **사용자가** 해당 작업 브랜치에서 압축본과 생성 메타데이터를 함께 공유합니다.

```bash
git add -- "maps/창학관 3층/rtabmap.db.zst" "maps/창학관 3층/rtabmap.db.zst.json"
git commit -m "map: 창학관 3층 지도 공유"
git push
```

다른 PC에서는 Git LFS 설치 후 저장소를 clone하고 `go2_nav2` 환경을 준비합니다. Git LFS가 설치된 일반 clone은 압축본도 내려받습니다. 포인터만 내려왔거나 다운로드를 건너뛴 경우 다음을 실행합니다. 이미 clone한 PC에서는 먼저 사용자가 `git pull`로 작업 브랜치를 갱신합니다.

```bash
git lfs pull
conda activate go2_nav2
bash setup_maps.sh restore "창학관 3층"
```

완료 시 `RESTORE OK` 또는 같은 DB가 이미 있으면 `REUSE DB`가 표시됩니다. 복원된 경로는 `maps/창학관 3층/rtabmap.db`입니다. Nav2 실행 시 이 경로를 지정하고 기존처럼 주행용 복사본을 사용합니다. 기존 DB가 다르면 덮어쓰지 않으므로 다른 지도 폴더에 보관한 뒤 진행하세요.

검증: 가짜 SQLite DB로 PC 간 압축본 전달·복원, 원본 보존, 손상 거부, 로컬 Git LFS 포인터 생성 등 23개 검사 PASS. 실제 지도 압축·GitHub LFS 업로드·다른 PC Nav2 실행은 NOT TESTED입니다.

## 실행용 sh: 루트 4개와 내부 공통 1개

모든 명령은 저장소 루트 기준입니다. 다른 위치에서는 sh의 절대 경로를 지정합니다.

| 파일 | 기능 |
|---|---|
| `install_student.sh` | Conda 환경 생성·설치·빌드·검증 |
| `setup_maps.sh` | 지도 압축·복원·검증 |
| `run_mapping.sh` | `start`, `check`, `plan`, `sensors` 및 새 DB 경로 입력 |
| `run_nav.sh` | `view`, `drive`, `check`, `plan`, `health`, `bridge`, `shell`, `aligned`, `reference` |
| `scripts/_env.sh` | 두 실행 파일이 사용하는 내부 공통 환경·프로세스 함수 |

기존 `laptop_slam.sh`, `laptop_nav.sh`, `student_session.sh`, `nav_health.sh`, `localization_compare.sh`는 위 실행 파일로 통합했습니다. `go2_camera_session.sh`는 제거했습니다. 카메라는 별도 SSH 터미널에서 Go2 명령으로 실행하며, **Go2에 저장소를 clone하지 않습니다.**

PC에서 환경을 활성화한 뒤 실제 로봇 연결 인터페이스를 지정합니다. 현재 PC에서는 `eno1`을 사용했으며 다른 PC에서는 해당 장치 이름을 사용합니다.

```bash
conda activate go2_nav2
export GO2_NET_IFACE=eno1  # 현재 PC 예시
bash run_nav.sh check
```

카메라를 아래 Go2 터미널에서 먼저 실행한 뒤 PC에서는 둘 중 하나를 선택합니다.

```bash
# 새 지도: Go2 조종기로 이동하며 Mapping. 기존 파일은 거부합니다.
bash run_mapping.sh "maps/새 지도/rtabmap.db"
# 또는 이미 복원한 지도로 Nav2·RViz2 시작. 주행 bridge는 비활성입니다.
bash run_nav.sh view "maps/창학관 3층/rtabmap.db"
```

Mapping은 Ctrl+C로 종료하고 저장 검사가 완료될 때까지 기다립니다. 기본 새 지도 경로는 `maps/go2_<날짜>_<PID>/rtabmap.db`입니다. 명시적 DB 경로와 `GO2_MAP_DIR` 재정의도 지원합니다. 저장 성공 후 `.last_map`을 기록하므로 `bash run_nav.sh view`로 최근 작성 지도를 선택할 수도 있습니다. 복원만 한 지도는 경로를 직접 입력합니다.

`bash run_mapping.sh plan`과 `bash run_nav.sh plan "maps/창학관 3층/rtabmap.db"`는 환경 로딩·빌드·노드 시작·파일 생성을 하지 않습니다. `check`는 환경만 확인합니다. `sensors`는 Mapping 시작 전 실시간 센서 수신을 확인합니다.

Nav2 원본 DB는 보존하고 `maps/nav_sessions/<날짜_PID>/rtabmap.db`에 복사해 사용합니다. `GO2_MAP_DIR`를 지정하면 세션도 그 아래에 생성합니다. `view`는 이전 `GO2_ENABLE_MOTION=true`가 남아 있어도 주행을 비활성으로 시작합니다. 운영자는 RViz2 위치·방향과 Costmap을 확인하고 view를 종료한 뒤 `bash run_nav.sh drive "maps/창학관 3층/rtabmap.db"`를 명시적으로 선택합니다. Goal과 실제 이동은 운영자가 수행합니다.

진단과 비교 기능은 다음과 같이 유지합니다.

```bash
bash run_nav.sh health --seconds 4
bash run_nav.sh aligned "maps/창학관 3층/rtabmap.db"
bash run_nav.sh reference "maps/비교 지도/rtabmap.db"
# 또는 view에서 직접 선택
bash run_nav.sh view "maps/창학관 3층/rtabmap.db" --profile aligned_visual
```

비교 명령은 각각 `aligned_visual`, `reference_visual`을 선택하며 주행은 비활성입니다. 서로 다른 지도 좌표를 혼용하지 않도록 비교 DB 경로는 필수입니다. 일반 실행의 기존 기본 프로필 `legacy`와 `GO2_LOCALIZATION_PROFILE` 설정은 유지합니다. `bridge`는 중복 bridge를 거부하고 비활성 상태로만 시작합니다. `shell`은 현재 ROS 환경의 별도 셸을 엽니다.

루트 통합 검증: 가짜 ROS·DB로 Mapping 13개, Nav2 11개, 설치 진입·공통 환경 9개, 지도 23개, 환경 13개, hook 보호 16개, **총 85개 PASS**. 실제 Conda 설치·카메라·센서·RViz2·물리 주행은 이번 정리에서 NOT TESTED입니다. 기존 주행 범위는 위 운영 기록을 참고합니다.

## Current data and control routes

- `/utlidar/cloud_base` → camera-clock alignment → `/cloud_base_synced` → 1 s motion-compensated `/assembled_cloud`.
- `/utlidar/robot_odom` → latest RGB stamp → `/robot_odom_fixed` and `odom → base_link`. Set `odom_bridge:=false` only if the existing equivalent bridge is already running.
- `/camera/color/image_raw`, `/camera/color/camera_info`, `/camera/aligned_depth_to_color/image_raw` → RTAB-Map visual registration (`Reg/Strategy=0`). Navigation localizes in a saved database with `Mem/IncrementalMemory=false`, `Mem/LocalizationReadOnly=true`, `map_always_update=false`.
- Sensor restamping follows the previous experiment's approximate latest-camera-stamp convention. It is **not hardware synchronization**. Stale camera input stops synchronized output; cached odometry is not reused beyond 0.5 s.
- `base_link → camera_link = (0.20, 0, 0.09)m` preserves the existing saved-map camera model. RealSense publishes its internal camera frames. The included 2026-11-10 calibration affects only the Nav2 depth-scan frame; it does not rewrite saved keyframes. Disable it for another mount with `nav_camera_calibration:=''` when launching directly.
- DWB → `/go2_nav/cmd_vel_raw` → velocity smoother → `/go2_nav/cmd_vel` → optional `sport_ctrl` → `/api/sport/request`.
- All translation routes enforce `x >= 0`, `y = 0`. Turning is allowed. Negative/lateral commands are clipped again at the Sport encoder; non-finite input sends StopMove. Backup recovery is absent from both behavior trees and the behavior server. This policy covers this Nav2 bridge; a separately running teleoperation or SDK process has its own control path.

## 기존 시스템 ROS 작업공간 빌드

The following reproduces the earlier native ROS laptop workspace. Use the Conda installer above for a new deployment; do not source these system overlays in an active `go2_nav2` environment. The existing Unitree message workspace is reused; no second RoboSense SDK is needed.

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

In this native ROS path, scripts source the existing Unitree setup at `~/unitree_ros2/cyclonedds_ws/install/setup.bash`; override its location with `GO2_UNITREE_SETUP`. The Conda path installs the declared packages from `environment.json` and does not reuse this system-built workspace.

## 카메라: Go2 SSH 터미널에서 명령어로 실행

On the laptop, open **terminal 1** and connect to the powered robot:

```bash
ssh unitree@192.168.123.18
```

At `ros:foxy(1) ...`, choose `1`. Then run **on Go2**:

```bash
source ~/ros2_realsense_456_ws/activate.bash
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_fastrtps_cpp
ros2 launch realsense2_camera rs_launch.py \
  camera_namespace:=/ camera_name:=camera \
  depth_module.depth_profile:=640x480x30 rgb_camera.color_profile:=640x480x15 \
  enable_color:=true enable_depth:=true enable_infra1:=false enable_infra2:=false \
  enable_sync:=false align_depth.enable:=true pointcloud.enable:=false \
  enable_accel:=false enable_gyro:=false \
  depth_module.emitter_enabled:=1 depth_module.emitter_on_off:=false
```

카메라 터미널은 실행한 채 유지합니다. Go2의 `ROS_DOMAIN_ID`는 PC와 같게 맞춥니다. 기존 카메라 환경 활성화 명령을 사용하며, 이 저장소의 sh나 새 파일을 Go2로 보내지 않습니다. 카메라를 종료할 때는 해당 터미널에서 Ctrl+C를 누릅니다.

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
bash -n scripts/_env.sh run_mapping.sh run_nav.sh
# After sourcing the built workspace:
python3 -m pytest -q tests
```

See the current [validation record](docs/go2_navigation_validation.html#revision-history) for the latest evidence and links to earlier records. R5 and the original T00–T10 history remain in the [fixed pre-redesign document](https://github.com/jcy9066/unitree-go2-slam-nav2/blob/7aa21b2/docs/go2_navigation_validation.html). Follow [AGENTS.md](AGENTS.md). No GitHub Actions or automatic merge.

## Corner safeguards and automatic evaluation recording

Nonzero DWB translation candidates are limited to **0.20…0.50m/s**, while `min_vel_x=0` retains in-place rotation. `min_speed_theta=0.60rad/s` filters tiny pure turns. `Go2WalkingSpeed` rejects small translation even when mixed with rotation; `ObstacleFootprint` checks the rotated padded boundary. The 0.20m/s threshold is an adjustable trial value informed by the earlier response measurements, not a proven universal walking threshold. Smoother startup/braking can still pass briefly through lower speeds. Commands are never boosted after collision scoring. The maximum yaw rate remains ±1.8rad/s; reverse/lateral translation remains blocked. `PoseProgressChecker` recognizes either 0.5m translation or 0.10rad rotation within 10 seconds. This configured rotation support does not establish successful 180° turning at the professor’s room entrance.

A read-only recorder starts automatically with `view` and `drive`. It sends no motion or parameter-setting requests. It saves:

- `/evaluation`: all candidate velocities, validity/totals, critic costs, and the selected predicted poses at up to 2Hz. DWB short-circuiting remains enabled, so some losing candidates have partial scores.
- Raw/smoothed commands, Sport requests/responses, native/synchronized odometry, robot gait/velocity/foot state, TF, plans, action status and selected ROS logs.
- Exact uint8 raw Local/Global Costmaps, footprints, parameter snapshots and the Sport publisher graph. Images and pointclouds are excluded.

Each session has a unique directory:

```text
maps/nav_sessions/<session>/diagnostics/<run>/
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
GO2_RECORD_OBSTACLE_SENSORS=true bash run_nav.sh view "$GO2_TEST_MAP"
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
See [R32](https://github.com/jcy9066/unitree-go2-slam-nav2/blob/7aa21b2/docs/go2_navigation_validation.html#door-failure-r32) for the first-door
analysis, confirmed limits and next supervised test sequence.

### First-door-only laboratory round trip

For the saved lab map used in R32, enable an optional route policy that keeps
the second door out of both Costmaps and stops at a failed waypoint:

```bash
export GO2_TEST_MAP="$HOME/GH/go2_l1_nav2_ws/analysis/left_door_repair_20261110/navigation_map.db"
GO2_FIRST_DOOR_ONLY=true GO2_RECORD_OBSTACLE_SENSORS=true \
  bash run_nav.sh view "$GO2_TEST_MAP"
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
[R33](https://github.com/jcy9066/unitree-go2-slam-nav2/blob/7aa21b2/docs/go2_navigation_validation.html#first-door-r33) for the planner-only
comparison and the two-terminal startup commands.

### Camera `bad_alloc caught` messages

Do not infer exhausted RAM from this message alone. In R34 the Go2 had
6,209 MiB available and RGB/aligned-depth reception continued while the camera
used Foxy Fast DDS 2.1.4. The same log text exists in Fast DDS discovery-data
deserialization; the exact offending packet was not identified.

The tested camera backend remains `rmw_fastrtps_cpp`. A Cyclone DDS comparison
crashed this device's camera node and was reverted. The manual Go2 launch command explicitly selects `rmw_fastrtps_cpp`; the repository no longer sends a camera shell payload. Stream profiles and the laptop RMW are
unchanged. The SSH payload disables interactive job control so `setsid` retains
the owned launch PID/group for cleanup. See [R34](https://github.com/jcy9066/unitree-go2-slam-nav2/blob/7aa21b2/docs/go2_navigation_validation.html#camera-dds-r34)
for before/failure/restoration evidence and the remaining limitations.
