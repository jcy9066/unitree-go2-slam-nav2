#!/usr/bin/env bash
# Internal helpers for root 02_create_map.sh and 03_run_nav.sh; sourcing starts nothing.
GO2_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
GO2_REPO_ROOT="$(cd -- "$GO2_SCRIPT_DIR/.." && pwd)"

go2_map_directory() {
    if [[ -n ${GO2_MAP_DIR:-} ]]; then
        realpath -m -- "$GO2_MAP_DIR"
    else
        # Runtime Mapping/Nav2 maps are local, independent of repository map archives.
        realpath -m -- "$HOME/maps"
    fi
}

go2_auto_network_interface() {
    # Prefer Go2's dedicated wired subnet, then a single active physical Ethernet interface.
    local line iface matches=()
    if command -v ip >/dev/null 2>&1; then
        while IFS= read -r line; do
            if [[ "$line" =~ ^[0-9]+:[[:space:]]+([[:alnum:]_.:-]+)[[:space:]]+inet[[:space:]]+192\.168\.123\.[0-9]+/ ]]; then
                iface="${BASH_REMATCH[1]}"
                [[ -d "/sys/class/net/$iface/device" && -r "/sys/class/net/$iface/carrier" ]] || continue
                [[ "$(cat "/sys/class/net/$iface/carrier" 2>/dev/null || true)" == 1 ]] || continue
                matches+=("$iface")
            fi
        done < <(ip -o -4 addr show 2>/dev/null)
    fi
    if (( ${#matches[@]} == 1 )); then
        printf '%s\n' "${matches[0]}"
        return 0
    fi
    if (( ${#matches[@]} > 1 )); then
        echo 'ERROR: 여러 Go2 네트워크 연결 감지. 중복 연결을 확인하세요.' >&2
        return 1
    fi
    for iface in /sys/class/net/*; do
        [[ -d "$iface/device" && -r "$iface/carrier" ]] || continue
        [[ "$(cat "$iface/type" 2>/dev/null || true)" == 1 ]] || continue
        [[ "$(cat "$iface/carrier" 2>/dev/null || true)" == 1 ]] || continue
        [[ "${iface##*/}" == wl* ]] && continue
        matches+=("${iface##*/}")
    done
    if (( ${#matches[@]} != 1 )); then
        echo 'ERROR: Go2 유선 네트워크를 하나로 확인할 수 없습니다.' >&2
        return 1
    fi
    printf '%s\n' "${matches[0]}"
}

go2_require_network() {
    local iface="${GO2_NET_IFACE:-}"
    if [[ -z "$iface" ]]; then
        iface="$(go2_auto_network_interface)" || return 1
        export GO2_NET_IFACE="$iface"
        printf '[go2] Ethernet 자동 선택: %s\n' "$iface"
    fi
    if [[ "$iface" == lo || ! "$iface" =~ ^[a-zA-Z0-9_.:-]+$ || ! -d "/sys/class/net/$iface" ]]; then
        echo 'ERROR: 유효한 Go2 네트워크가 없습니다.' >&2
        return 1
    fi
    if [[ ! -r "/sys/class/net/$iface/carrier" ]] || [[ "$(cat "/sys/class/net/$iface/carrier" 2>/dev/null || true)" != 1 ]]; then
        printf 'ERROR: %s Ethernet 연결을 확인하세요.\n' "$iface" >&2
        return 1
    fi
    export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
    export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}" ROS_LOCALHOST_ONLY=0
    [[ "$ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] && (( ROS_DOMAIN_ID <= 232 )) || {
        echo 'ERROR: ROS_DOMAIN_ID must be 0..232' >&2; return 1;
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
if [[ -z ${CONDA_PREFIX:-} && ${GO2_USE_SYSTEM_ROS:-0} != 1 ]]; then
    local hook='' base=''
    if command -v conda >/dev/null 2>&1; then
        base="$(conda info --base 2>/dev/null || true)"
        [[ -f "$base/etc/profile.d/conda.sh" ]] && hook="$base/etc/profile.d/conda.sh"
    fi
    if [[ -z "$hook" && -n ${CONDA_EXE:-} ]]; then
        base="$(dirname -- "$(dirname -- "$CONDA_EXE")")"
        [[ -f "$base/etc/profile.d/conda.sh" ]] && hook="$base/etc/profile.d/conda.sh"
    fi
    if [[ -z "$hook" ]]; then
        for base in "$HOME/anaconda3" "$HOME/miniconda3" "$HOME/miniforge3"; do
            if [[ -f "$base/etc/profile.d/conda.sh" ]]; then
                hook="$base/etc/profile.d/conda.sh"
                break
            fi
        done
    fi
    if [[ -z "$hook" ]]; then
        echo 'ERROR: Conda를 찾지 못했습니다. 01_setup_env.sh를 확인하세요.' >&2
        return 1
    fi
    set +u
    # shellcheck disable=SC1090
    source "$hook"
    if ! conda activate go2_nav2; then
        set -u
        echo 'ERROR: go2_nav2 환경 활성화 실패. 01_setup_env.sh를 확인하세요.' >&2
        return 1
    fi
    set -u
fi
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
