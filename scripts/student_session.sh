#!/usr/bin/env bash
# Operator entry points for the already installed go2_nav2 Conda environment.
set -Eeuo pipefail
SCRIPTS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MODE=${1:-check}
if [[ "$MODE" == -h || "$MODE" == --help ]]; then
    echo 'Usage: student_session.sh check|sensors|camera|map [new.db]|view existing.db|bridge|health|shell'
    echo 'Activate go2_nav2 first. Runtime robot/network options remain operator inputs.'
    exit 0
fi
[[ "$MODE" =~ ^(check|sensors|camera|map|view|bridge|health|shell)$ ]] && (( $# <= 2 )) || exit 2
if [[ "$MODE" != map && "$MODE" != view ]] && (( $# > 1 )); then exit 2; fi
ENV_NAME=$(env -u PYTHONHOME -u PYTHONPATH /usr/bin/python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["conda"]["name"])' "$SCRIPTS/../environment.json")
[[ -n ${CONDA_PREFIX:-} && "$(basename -- "$CONDA_PREFIX")" == "$ENV_NAME" ]] || {
    printf 'ERROR: activate the project environment first: conda activate %s\n' "$ENV_NAME" >&2; exit 1;
}
PYTHON_BIN="$CONDA_PREFIX/bin/python"
"$PYTHON_BIN" "$SCRIPTS/environment.py" verify
export GO2_SKIP_BUILD=1 GO2_ENABLE_MOTION=false
if [[ "$MODE" == check ]]; then exit 0; fi
if [[ "$MODE" == shell ]]; then
    echo 'Conda ROS shell. Type exit to leave. No robot command sent.'
    exec /bin/bash --noprofile --norc -i
fi
NET_IFACE=${GO2_NET_IFACE:-lo}
[[ "$NET_IFACE" != lo && -d "/sys/class/net/$NET_IFACE" ]] || {
    echo 'Offline interface selected. Set GO2_NET_IFACE explicitly for live modes.' >&2; exit 1;
}
if [[ "$MODE" == camera ]]; then
    [[ "${GO2_SSH_TARGET:-}" =~ ^[a-zA-Z0-9_.]+@[a-zA-Z0-9_.:-]+$ ]] || {
        echo 'Set GO2_SSH_TARGET explicitly for camera mode.' >&2; exit 2;
    }
    echo 'Run once only. The Go2 must already have ~/ros2_realsense_456_ws/activate.bash.'
    exec ssh -tt -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 \
        "$GO2_SSH_TARGET" "bash --noprofile --norc -s -- ${ROS_DOMAIN_ID:-0}" < "$SCRIPTS/go2_camera_session.sh"
fi
if [[ "$MODE" == sensors ]]; then exec "$PYTHON_BIN" "$SCRIPTS/mapping_preflight.py" ready --timeout 20; fi
if [[ "$MODE" == health ]]; then exec bash "$SCRIPTS/nav_health.sh"; fi
if [[ "$MODE" == bridge ]]; then
    if ros2 node list 2>/dev/null | "$PYTHON_BIN" -c 'import sys; sys.exit(0 if "/sport_ctrl" in sys.stdin.read().splitlines() else 1)'; then
        echo 'ERROR: sport_ctrl already exists. Keep the original bridge terminal.' >&2; exit 1
    fi
    echo 'Starting DISABLED bridge. No Sport request is published while enabled=false.'
    exec ros2 run go2_cmd_processor sport_ctrl --ros-args -r __node:=sport_ctrl \
        -r cmd_vel:=/go2_nav/cmd_vel -p enabled:=false -p max_linear_x:=0.5 -p max_angular_z:=1.8
fi
[[ -n ${DISPLAY:-} ]] || { echo 'RViz needs a desktop/X11 DISPLAY.' >&2; exit 1; }
"$PYTHON_BIN" "$SCRIPTS/mapping_preflight.py" idle --timeout 3
"$PYTHON_BIN" "$SCRIPTS/mapping_preflight.py" ready --timeout 20
if [[ "$MODE" == map ]]; then
    DB=${2:-${GO2_MAP_DIR:-$HOME/go2_maps}/go2_$(date +%Y%m%d_%H%M%S)_$$.db}
    exec bash "$SCRIPTS/run_mapping.sh" "$DB"
fi
[[ $# == 2 && -s "$2" ]] || { echo 'Usage: student_session.sh view /absolute/path/to/saved.db' >&2; exit 2; }
exec bash "$SCRIPTS/run_nav.sh" "$2"
