#!/usr/bin/env bash
# Server bootstrap: explicit installation only; never starts ROS nodes or motion.
set -Eeuo pipefail
if [[ ${GO2_INSTALL_CLEAN:-0} != 1 ]]; then
    exec env -u PYTHONPATH -u PYTHONHOME -u CONDA_PREFIX -u CONDA_DEFAULT_ENV \
        -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH -u CMAKE_PREFIX_PATH \
        -u LD_LIBRARY_PATH -u LD_PRELOAD -u ROS_DISTRO -u ROS_VERSION \
        -u PYTHONPYCACHEPREFIX PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        PYTHONNOUSERSITE=1 GO2_INSTALL_CLEAN=1 /bin/bash "$0" "$@"
fi
usage() {
    cat <<'HELP'
Usage: bash install_student.sh [plan|install|verify] [options]
  plan (default): print compatibility and installation plan; no changes.
  install: install missing apt dependencies, clone and build a separate workspace.
  verify: check an existing installation; no ROS nodes or robot commands.
Options:
  --prefix PATH     default $HOME/ctrlcv/go2_nav
  --data-root PATH  default $HOME/Documents/hh/go2_nav
  --interface NAME default lo (offline); set the actual robot-network interface
  --ref REF        default docs/student-tutorial-r48; exact SHA also accepted
The existing Isaac/Conda/CUDA installations are not used or upgraded.
Requires Ubuntu 22.04, system Python 3.10 and sudo for missing apt packages.
HELP
}
MODE=${1:-plan}
if [[ "$MODE" == -h || "$MODE" == --help ]]; then usage; exit 0; fi
if (( $# )); then shift; fi
PREFIX="$HOME/ctrlcv/go2_nav"
DATA_ROOT="$HOME/Documents/hh/go2_nav"
NET_IFACE=lo
PROJECT_REF=docs/student-tutorial-r48
UNITREE_REF=668d1ec5a05d1c38d3306bdca7d59f2ba3581a88
while (( $# )); do
    (( $# >= 2 )) || { usage >&2; exit 2; }
    case "$1" in
        --prefix) PREFIX=$2;;
        --data-root) DATA_ROOT=$2;;
        --interface) NET_IFACE=$2;;
        --ref) PROJECT_REF=$2;;
        *) usage >&2; exit 2;;
    esac
    shift 2
done
[[ "$MODE" =~ ^(plan|install|verify)$ ]] || { usage >&2; exit 2; }
[[ "$NET_IFACE" =~ ^[a-zA-Z0-9_.:-]+$ ]] || { echo 'Invalid interface' >&2; exit 2; }
[[ "$PROJECT_REF" =~ ^[a-zA-Z0-9_./-]+$ && "$PROJECT_REF" != -* ]] || exit 2
PREFIX=$(realpath -m -- "$PREFIX")
DATA_ROOT=$(realpath -m -- "$DATA_ROOT")
for path in "$PREFIX" "$DATA_ROOT"; do
    [[ "$path" == "$HOME/"* && "$path" != "$HOME/ctrlcv" && "$path" != "$HOME/Documents/hh" ]] || {
        echo 'Choose a dedicated subdirectory inside your home.' >&2; exit 2;
    }
done
REPO="$PREFIX/ws/src/unitree-go2-slam-nav2"
UNITREE="$PREFIX/vendor/unitree_ros2"
source /etc/os-release
ARCH=$(dpkg --print-architecture)
PACKAGES=(git curl ca-certificates build-essential cmake pkg-config libyaml-cpp-dev
    python3-numpy python3-scipy python3-opencv python3-yaml python3-pytest
    python3-colcon-common-extensions python3-rosdep python3-vcstool openssh-client
    ros-humble-desktop ros-humble-navigation2 ros-humble-nav2-bringup
    ros-humble-rtabmap-ros ros-humble-depthimage-to-laserscan
    ros-humble-rmw-cyclonedds-cpp ros-humble-rosidl-generator-dds-idl)
printf 'Host: %s %s / %s\nSystem Python: ' "$ID" "$VERSION_ID" "$ARCH"
/usr/bin/python3 --version
printf 'Code: %s\nMaps/logs: %s\nInterface: %s\nSource ref: %s\n' "$PREFIX" "$DATA_ROOT" "$NET_IFACE" "$PROJECT_REF"
if [[ "$MODE" == plan ]]; then
    printf 'Apt dependencies: %s\n' "${PACKAGES[*]}"
    echo 'Build: Unitree message packages + 3 Go2 packages; 2 jobs; CPU only.'
    echo 'No apt, clone, build, SSH, network change, ROS startup or motion executed.'
    if [[ "$ID/$VERSION_ID" != ubuntu/22.04 ]]; then
        echo 'UNSUPPORTED: install mode requires Ubuntu 22.04.'
    fi
    exit 0
fi
[[ "$ID/$VERSION_ID" == ubuntu/22.04 && "$ARCH" =~ ^(amd64|arm64)$ ]] || {
    echo 'ERROR: Ubuntu 22.04 amd64/arm64 required; no changes made.' >&2; exit 1;
}
[[ $(/usr/bin/python3 -c 'import sys; print("%s.%s" % sys.version_info[:2])') == 3.10 ]] || exit 1
verify_install() {
    [[ -f "$PREFIX/env.bash" ]] || { echo 'Missing env.bash; install first.' >&2; return 1; }
    set +u
    source "$PREFIX/env.bash"
    set -u
    for package in unitree_api unitree_go go2_slam_nav go2_cmd_processor go2_nav2_critics \
                   rtabmap_slam rtabmap_odom nav2_bringup depthimage_to_laserscan; do
        ros2 pkg prefix "$package"
    done
    /usr/bin/python3 -c 'import rclpy, numpy, scipy, cv2; from unitree_api.msg import Request; from rtabmap_msgs.msg import OdomInfo; print("System Python imports OK")'
    /usr/bin/python3 - <<'PY'
from pathlib import Path
root = Path('/opt/ros/humble/share/nav2_controller')
assert any('PoseProgressChecker' in p.read_text() for p in root.glob('*.xml')), 'PoseProgressChecker unavailable; check Nav2 package version'
PY
    echo 'INSTALL CHECK PASS (packages/imports only). Live sensors, TF and motion NOT TESTED.'
}
if [[ "$MODE" == verify ]]; then verify_install; exit 0; fi
(( EUID != 0 )) || { echo 'Run as your normal account; sudo is used only for apt.' >&2; exit 1; }
[[ -d "/sys/class/net/$NET_IFACE" ]] || { echo 'Unknown network interface; use lo for offline install.' >&2; exit 1; }
if [[ -e "$PREFIX" && ! -f "$PREFIX/.go2-student-install" ]] && \
   [[ -n $(find "$PREFIX" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
    echo 'ERROR: nonempty unowned prefix. Choose a new dedicated directory.' >&2; exit 1
fi
mkdir -p "$PREFIX" "$DATA_ROOT/maps" "$DATA_ROOT/logs" "$DATA_ROOT/tmp"
touch "$PREFIX/.go2-student-install"
exec > >(tee -a "$DATA_ROOT/logs/install_$(date +%Y%m%d_%H%M%S).log") 2>&1
trap 'echo "Installation stopped at line $LINENO. Logs and existing files retained; rerun after fixing the error." >&2' ERR
missing=()
for package in "${PACKAGES[@]}"; do
    [[ $(dpkg-query -W -f='${Status}' "$package" 2>/dev/null || true) == 'install ok installed' ]] || missing+=("$package")
done
if (( ${#missing[@]} )); then
    sudo apt-get update
    sudo apt-get install --no-upgrade -y ca-certificates curl
    if ! apt-cache show ros-humble-desktop >/dev/null 2>&1; then
        # Official ros-infrastructure release, pinned and checksum verified.
        DEB="$DATA_ROOT/tmp/ros2-apt-source_1.3.0.jammy_all.deb"
        curl --fail --location --retry 3 -o "$DEB" \
            https://github.com/ros-infrastructure/ros-apt-source/releases/download/1.3.0/ros2-apt-source_1.3.0.jammy_all.deb
        printf '%s  %s\n' 110b9a462d55252decb8b7c816f61c2ba0d9890ce5fb93ac504e97cae5860d76 "$DEB" | sha256sum -c -
        sudo dpkg -i "$DEB"
        sudo apt-get update
    fi
    sudo apt-get install --no-upgrade -y "${missing[@]}"
fi
mkdir -p "$PREFIX/ws/src" "$PREFIX/vendor"
clone_exact() {
    local url=$1 target=$2 ref=$3
    if [[ ! -e "$target" ]]; then
        git clone --no-checkout "$url" "$target"
        git -C "$target" fetch origin "$ref"
        git -C "$target" checkout --detach FETCH_HEAD
    else
        [[ -d "$target/.git" && -z $(git -C "$target" status --porcelain) ]] || {
            echo "ERROR: existing checkout modified: $target" >&2; return 1;
        }
        local expected
        expected=$(git -C "$target" rev-parse "$ref^{commit}" 2>/dev/null || \
            git -C "$target" rev-parse "origin/$ref^{commit}")
        [[ $(git -C "$target" rev-parse HEAD) == "$expected" ]] || {
            echo 'ERROR: checkout differs from requested revision; choose a new prefix.' >&2; return 1;
        }
    fi
}
clone_exact https://github.com/jcy9066/unitree-go2-slam-nav2.git "$REPO" "$PROJECT_REF"
clone_exact https://github.com/unitreerobotics/unitree_ros2.git "$UNITREE" "$UNITREE_REF"
[[ -f "$REPO/scripts/student_session.sh" ]] || { echo 'Selected source lacks student_session.sh' >&2; exit 1; }
export MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
set +u
source /opt/ros/humble/setup.bash
set -u
(cd "$UNITREE/cyclonedds_ws" && /usr/bin/colcon build --base-paths src/unitree \
    --packages-select unitree_go unitree_api --executor sequential --cmake-args -DBUILD_TESTING=OFF)
set +u
source "$UNITREE/cyclonedds_ws/install/setup.bash"
set -u
(cd "$PREFIX/ws" && /usr/bin/colcon build --base-paths src \
    --packages-select go2_nav2_critics go2_slam_nav go2_cmd_processor --executor sequential \
    --cmake-args -DBUILD_TESTING=OFF)
{
    echo '# Generated for Bash. Use a clean system-Python shell; no Conda activation.'
    printf 'export GO2_PREFIX=%q\nexport GO2_DATA_ROOT=%q\n' "$PREFIX" "$DATA_ROOT"
    printf 'export GO2_WS_ROOT=%q\nexport GO2_REPO_ROOT=%q\n' "$PREFIX/ws" "$REPO"
    printf 'export GO2_UNITREE_SETUP=%q\nexport GO2_MAP_DIR=%q\n' "$UNITREE/cyclonedds_ws/install/setup.bash" "$DATA_ROOT/maps"
    printf 'export GO2_NET_IFACE=%q\n' "$NET_IFACE"
    cat <<'ENV'
export GO2_SKIP_BUILD=1 GO2_ENABLE_MOTION=false GO2_LOCALIZATION_PROFILE=aligned_visual
export GO2_RECORD_DIAGNOSTICS=true GO2_RECORD_OBSTACLE_SENSORS=true
export GO2_SSH_TARGET=unitree@192.168.123.18
export ROS_DOMAIN_ID=0 ROS_LOCALHOST_ONLY=0 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export PYTHONNOUSERSITE=1 OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
export CUDA_VISIBLE_DEVICES='' LIBGL_ALWAYS_SOFTWARE=1 QT_X11_NO_MITSHM=1
export CYCLONEDDS_URI="<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$GO2_NET_IFACE\"/></Interfaces></General></Domain></CycloneDDS>"
source /opt/ros/humble/setup.bash
source "$GO2_UNITREE_SETUP"
source "$GO2_WS_ROOT/install/setup.bash"
ENV
} > "$PREFIX/env.bash"
{
    printf 'project_commit='; git -C "$REPO" rev-parse HEAD
    printf 'unitree_commit='; git -C "$UNITREE" rev-parse HEAD
    /usr/bin/python3 --version
    dpkg-query -W 'ros-humble-*' 2>/dev/null || true
} > "$DATA_ROOT/logs/installed_versions.txt"
verify_install
printf 'Next: bash %q check\n' "$REPO/scripts/student_session.sh"
