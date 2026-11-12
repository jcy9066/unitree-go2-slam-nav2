#!/usr/bin/env bash
# Portable student entry point. No command enables motion or sends a goal.
set -Eeuo pipefail
if [[ ${GO2_SESSION_CLEAN:-0} != 1 ]]; then
    exec env -u PYTHONPATH -u PYTHONHOME -u CONDA_PREFIX -u CONDA_DEFAULT_ENV \
        -u AMENT_PREFIX_PATH -u COLCON_PREFIX_PATH -u CMAKE_PREFIX_PATH \
        -u LD_LIBRARY_PATH -u LD_PRELOAD -u ROS_DISTRO -u ROS_VERSION \
        -u PYTHONPYCACHEPREFIX PATH=/usr/sbin:/usr/bin:/sbin:/bin \
        PYTHONNOUSERSITE=1 GO2_SESSION_CLEAN=1 /bin/bash "$0" "$@"
fi
MODE=${1:-check}
if [[ "$MODE" == -h || "$MODE" == --help ]]; then
    echo 'Usage: student_session.sh check|sensors|camera|map [new.db]|view existing.db|bridge|health|shell'
    echo 'GO2_STUDENT_ENV overrides $HOME/ctrlcv/go2_nav/env.bash. Motion activation is manual.'
    exit 0
fi
[[ "$MODE" =~ ^(check|sensors|camera|map|view|bridge|health|shell)$ ]] && (( $# <= 2 )) || exit 2
if [[ "$MODE" != map && "$MODE" != view ]] && (( $# > 1 )); then exit 2; fi
ENV_FILE=${GO2_STUDENT_ENV:-$HOME/ctrlcv/go2_nav/env.bash}
[[ -f "$ENV_FILE" ]] || { echo "Missing $ENV_FILE; run install_student.sh first." >&2; exit 1; }
set +u
source "$ENV_FILE"
set -u
export GO2_SKIP_BUILD=1 GO2_ENABLE_MOTION=false
SCRIPTS="$GO2_REPO_ROOT/scripts"
if [[ "$MODE" == check ]]; then
    exec bash "$SCRIPTS/install_student.sh" verify --prefix "$GO2_PREFIX" --data-root "$GO2_DATA_ROOT"
fi
if [[ "$MODE" == shell ]]; then
    echo 'System Python ROS shell. Type exit to leave. No robot command sent.'
    exec /bin/bash --noprofile --norc -i
fi
[[ "$GO2_NET_IFACE" != lo && -d "/sys/class/net/$GO2_NET_IFACE" ]] || {
    echo "Offline interface selected. Set GO2_NET_IFACE in $ENV_FILE after checking the robot network." >&2; exit 1;
}
if [[ "$MODE" == camera ]]; then
    [[ "$GO2_SSH_TARGET" =~ ^[a-zA-Z0-9_.]+@[a-zA-Z0-9_.:-]+$ ]] || exit 2
    echo 'Run once only. The Go2 must already have ~/ros2_realsense_456_ws/activate.bash.'
    exec ssh -tt -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 \
        "$GO2_SSH_TARGET" "bash --noprofile --norc -s -- $ROS_DOMAIN_ID" < "$SCRIPTS/go2_camera_session.sh"
fi
if [[ "$MODE" == sensors ]]; then exec /usr/bin/python3 "$SCRIPTS/mapping_preflight.py" ready --timeout 20; fi
if [[ "$MODE" == health ]]; then exec bash "$SCRIPTS/nav_health.sh"; fi
if [[ "$MODE" == bridge ]]; then
    if ros2 node list 2>/dev/null | /usr/bin/python3 -c 'import sys; sys.exit(0 if "/sport_ctrl" in sys.stdin.read().splitlines() else 1)'; then
        echo 'ERROR: sport_ctrl already exists. Keep the original bridge terminal.' >&2; exit 1
    fi
    echo 'Starting DISABLED bridge. No Sport request is published while enabled=false.'
    exec ros2 run go2_cmd_processor sport_ctrl --ros-args -r __node:=sport_ctrl \
        -r cmd_vel:=/go2_nav/cmd_vel -p enabled:=false -p max_linear_x:=0.5 -p max_angular_z:=1.8
fi
[[ -n ${DISPLAY:-} ]] || { echo 'RViz needs a desktop/X11 DISPLAY. Connect using ssh -X or a configured remote desktop.' >&2; exit 1; }
/usr/bin/python3 "$SCRIPTS/mapping_preflight.py" idle --timeout 3
/usr/bin/python3 "$SCRIPTS/mapping_preflight.py" ready --timeout 20
if [[ "$MODE" == map ]]; then
    DB=${2:-$GO2_MAP_DIR/go2_$(date +%Y%m%d_%H%M%S)_$$.db}
    exec bash "$SCRIPTS/run_mapping.sh" "$DB"
fi
[[ $# == 2 && -s "$2" ]] || { echo 'Usage: student_session.sh view /absolute/path/to/saved.db' >&2; exit 2; }
exec bash "$SCRIPTS/run_nav.sh" "$2"
