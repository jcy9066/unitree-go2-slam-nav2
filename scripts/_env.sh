#!/usr/bin/env bash
# Shared bootstrap for run_mapping.sh and run_nav.sh. Source from those scripts.
# Assumes a colcon workspace layout: <workspace>/src/unitree-go2-slam-nav2.
GO2_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GO2_REPO_ROOT="$(cd -- "$GO2_SCRIPT_DIR/.." && pwd)"
GO2_WS_ROOT="${GO2_WS_ROOT:-$(cd -- "$GO2_REPO_ROOT/../.." && pwd)}"
GO2_ROS_DISTRO="${ROS_DISTRO:-humble}"
GO2_ROS_SETUP="/opt/ros/$GO2_ROS_DISTRO/setup.bash"

if [[ ! -f "$GO2_ROS_SETUP" ]]; then
    printf 'ERROR: ROS 2 setup not found: %s\n' "$GO2_ROS_SETUP" >&2
    exit 1
fi
if [[ ! -d "$GO2_WS_ROOT/src" ]]; then
    printf 'ERROR: No colcon src directory at %s/src. Set GO2_WS_ROOT.\n' "$GO2_WS_ROOT" >&2
    exit 1
fi

# colcon setup scripts may inspect optional environment variables.
set +u
# shellcheck disable=SC1090
source "$GO2_ROS_SETUP"
GO2_UNITREE_SETUP="${GO2_UNITREE_SETUP:-$HOME/unitree_ros2/cyclonedds_ws/install/setup.bash}"
if [[ -f "$GO2_UNITREE_SETUP" ]]; then
    source "$GO2_UNITREE_SETUP"
fi
if [[ -f "$GO2_WS_ROOT/install/setup.bash" ]]; then
    # shellcheck disable=SC1090
    source "$GO2_WS_ROOT/install/setup.bash"
fi
set -u

if [[ "${GO2_SKIP_BUILD:-0}" != "1" ]]; then
    if ! command -v colcon >/dev/null 2>&1; then
        echo 'ERROR: colcon is not installed. Complete the README workspace setup.' >&2
        exit 1
    fi
    echo "[go2] Building changed launch/config packages in $GO2_WS_ROOT"
    # Only discover source packages; workspace backups may contain package.xml.
    (cd -- "$GO2_WS_ROOT" && colcon build --base-paths "$GO2_WS_ROOT/src" \
        --packages-select go2_nav2_critics go2_slam_nav go2_cmd_processor)
fi

if [[ ! -f "$GO2_WS_ROOT/install/setup.bash" ]]; then
    echo '[go2] ERROR: No workspace install/setup.bash. Run colcon build after importing dependencies.' >&2
    exit 1
fi
set +u
# shellcheck disable=SC1090
source "$GO2_WS_ROOT/install/setup.bash"
set -u

for pkg in go2_slam_nav go2_nav2_critics go2_cmd_processor rtabmap_slam rtabmap_util nav2_bringup depthimage_to_laserscan unitree_api; do
    if ! ros2 pkg prefix "$pkg" >/dev/null 2>&1; then
        printf 'ERROR: required ROS package %s missing; import/build dependencies first.\n' "$pkg" >&2
        exit 1
    fi
done
