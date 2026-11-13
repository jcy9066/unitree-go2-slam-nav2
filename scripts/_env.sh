#!/usr/bin/env bash
# Internal helpers for root run_mapping.sh and run_nav.sh; sourcing starts nothing.
GO2_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GO2_REPO_ROOT="$(cd -- "$GO2_SCRIPT_DIR/.." && pwd)"

go2_map_directory() {
    if [[ -n ${GO2_MAP_DIR:-} ]]; then
        realpath -m -- "$GO2_MAP_DIR"
    else
        env -u PYTHONHOME -u PYTHONPATH "${GO2_BOOTSTRAP_PYTHON:-/usr/bin/python3}" -c \
            'import json,pathlib,sys; r=pathlib.Path(sys.argv[1]); print((r/json.load(open(r/"environment.json"))["maps"]["root"]).resolve())' \
            "$GO2_REPO_ROOT"
    fi
}

go2_require_network() {
    local iface=${GO2_NET_IFACE:-}
    if [[ -z "$iface" ]]; then
        if [[ -n ${CONDA_PREFIX:-} ]]; then iface=lo; else iface=eno1; fi
    fi
    if [[ "$iface" == lo || ! "$iface" =~ ^[a-zA-Z0-9_.:-]+$ || ! -d "/sys/class/net/$iface" ]]; then
        echo 'ERROR: Offline interface selected. Set GO2_NET_IFACE explicitly for live modes.' >&2
        return 1
    fi
    if [[ ! -r "/sys/class/net/$iface/carrier" ]] || [[ "$(cat "/sys/class/net/$iface/carrier" 2>/dev/null || true)" != 1 ]]; then
        printf 'ERROR: %s has no Ethernet link. Connect Go2 first.\n' "$iface" >&2
        return 1
    fi
    export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
    export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}" ROS_LOCALHOST_ONLY=0
    [[ "$ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] && (( ROS_DOMAIN_ID <= 232 )) || {
        echo 'ERROR: ROS_DOMAIN_ID must be an integer from 0 to 232' >&2; return 1;
    }
    export CYCLONEDDS_URI="${CYCLONEDDS_URI:-<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"$iface\"/></Interfaces></General></Domain></CycloneDDS>}"
}

GO2_LAUNCH_PID=''
go2_stop_launch() {
    if [[ -n "$GO2_LAUNCH_PID" ]] && kill -0 "$GO2_LAUNCH_PID" 2>/dev/null; then
        kill -INT -- "-$GO2_LAUNCH_PID" 2>/dev/null || true
        wait "$GO2_LAUNCH_PID" 2>/dev/null || true
    fi
    GO2_LAUNCH_PID=''
}

go2_launch() {
    local status=0
    set +m
    setsid ros2 "$@" &
    GO2_LAUNCH_PID=$!
    trap 'go2_stop_launch; exit 130' INT
    trap 'go2_stop_launch; exit 143' TERM
    wait "$GO2_LAUNCH_PID" || status=$?
    GO2_LAUNCH_PID=''
    return "$status"
}

go2_load_environment() {
if [[ -n ${CONDA_PREFIX:-} ]]; then
    GO2_ENV_NAME=$(env -u PYTHONHOME -u PYTHONPATH /usr/bin/python3 -c \
        'import json,sys; print(json.load(open(sys.argv[1]))["conda"]["name"])' \
        "$GO2_REPO_ROOT/environment.json")
    if [[ "$(basename -- "$CONDA_PREFIX")" != "$GO2_ENV_NAME" ]]; then
        printf 'ERROR: activate the project environment first: conda activate %s\n' "$GO2_ENV_NAME" >&2
        return 1
    fi
    "$CONDA_PREFIX/bin/python" "$GO2_SCRIPT_DIR/environment.py" verify || return 1
    export GO2_ENV_MANAGER=conda
    export GO2_PYTHON="$CONDA_PREFIX/bin/python"
    GO2_WS_ROOT="$CONDA_PREFIX"
    return 0
fi
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
GO2_PYTHON=python3
}
