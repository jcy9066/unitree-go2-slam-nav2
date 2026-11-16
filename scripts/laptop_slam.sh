#!/usr/bin/env bash
# Laptop -> optional owned SSH camera -> fresh sensors -> new-DB Mapping + RViz.
# All movement is performed by the operator. No Sport bridge or Nav2 starts here.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
usage() {
    cat <<'HELP'
Usage: bash scripts/laptop_slam.sh [start|check|plan] [new_map.db]
  start (default): build/source, verify idle, reuse/start camera, check sensors,
                   run Mapping + RViz; Ctrl+C flushes and validates the new DB.
  check: local ROS/workspace check only; no SSH, sensors or Mapping started.
  plan: print the intended paths and commands; no build, SSH or ROS started.
Environment:
  GO2_CAMERA_MODE=auto|existing  (default auto; auto reuses streaming RGB-D)
  GO2_SSH_TARGET=unitree@192.168.123.18
  GO2_WS_ROOT=.../unitree_go2_pr1_ws, GO2_MAP_DIR=$HOME/go2_maps
  GO2_SKIP_BUILD=1 skips build; ROS_DOMAIN_ID / CYCLONEDDS_URI are respected.
HELP
}
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then usage; exit 0; fi
MODE="${1:-start}"
if [[ "$MODE" != start && "$MODE" != check && "$MODE" != plan ]] || (( $# > 2 )); then
    usage >&2; exit 2
fi
export GO2_WS_ROOT="${GO2_WS_ROOT:-$(dirname -- "$REPO_ROOT")/unitree_go2_pr1_ws}"
export ROS_DISTRO=humble RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}" ROS_LOCALHOST_ONLY=0
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"eno1\"/></Interfaces></General></Domain></CycloneDDS>}"
[[ "$ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] && (( ROS_DOMAIN_ID <= 232 )) || {
    echo 'ERROR: ROS_DOMAIN_ID must be an integer from 0 to 232' >&2; exit 2;
}
CAMERA_MODE="${GO2_CAMERA_MODE:-auto}"
[[ "$CAMERA_MODE" == auto || "$CAMERA_MODE" == existing ]] || {
    echo 'ERROR: GO2_CAMERA_MODE must be auto or existing' >&2; exit 2;
}
SSH_TARGET="${GO2_SSH_TARGET:-unitree@192.168.123.18}"
[[ "$SSH_TARGET" =~ ^[a-zA-Z0-9_.]+@[a-zA-Z0-9_.:-]+$ ]] || {
    echo 'ERROR: GO2_SSH_TARGET must have the form user@host' >&2; exit 2;
}
MAP_DIR="$(realpath -m -- "${GO2_MAP_DIR:-$HOME/go2_maps}")"
DB="$(realpath -m -- "${2:-$MAP_DIR/go2_$(date +%Y%m%d_%H%M%S)_$$.db}")"
if [[ "$DB" != *.db || -e "$DB" || -L "$DB" ]]; then
    echo 'ERROR: choose a new, nonexistent .db path; existing DBs are preserved' >&2
    exit 1
fi
if [[ "$MODE" == plan ]]; then
    printf 'Workspace: %s\nNew database: %s\nROS domain: %s\nCamera: %s (%s)\n' \
        "$GO2_WS_ROOT" "$DB" "$ROS_DOMAIN_ID" "$CAMERA_MODE" "$SSH_TARGET"
    printf 'Mapping command: bash %q %q\n' "$SCRIPT_DIR/run_mapping.sh" "$DB"
    echo 'No build, SSH, ROS nodes or robot motion started.'
    exit 0
fi
if [[ "$MODE" == start ]] && [[ "$(cat /sys/class/net/eno1/carrier 2>/dev/null || true)" != 1 ]]; then
    echo 'ERROR: eno1 has no Ethernet link. Connect/power on Go2 first.' >&2
    exit 1
fi
source "$SCRIPT_DIR/_env.sh"
if [[ "$MODE" == check ]]; then
    printf '[go2] Local workspace ready: %s\n' "$GO2_WS_ROOT"
    echo '[go2] No SSH, camera, ROS nodes or Mapping started; live checks NOT TESTED.'
    exit 0
fi
for dependency in ssh setsid flock python3; do
    command -v "$dependency" >/dev/null || {
        printf 'ERROR: required command missing: %s\n' "$dependency" >&2; exit 1;
    }
done
mkdir -p -- "$MAP_DIR"
exec 9>"$MAP_DIR/.laptop_slam.lock"
flock -n 9 || { echo 'ERROR: another laptop_slam session is running' >&2; exit 1; }
RUN_DIR="$(mktemp -d "$MAP_DIR/mapping_session_$(date +%Y%m%d_%H%M%S)_XXXXXX")"
printf '%s\n' "$DB" > "$RUN_DIR/database_path.txt"
printf '[go2] Session logs: %s\n[go2] New map: %s\n' "$RUN_DIR" "$DB"
ssh_pid=''; mapping_pid=''
cleanup() {
    trap - EXIT INT TERM
    if [[ -n "$mapping_pid" ]] && kill -0 "$mapping_pid" 2>/dev/null; then
        echo '[go2] Stopping owned Mapping process; waiting for DB flush...'
        kill -INT -- "-$mapping_pid" 2>/dev/null || true
        wait "$mapping_pid" 2>/dev/null || true
    fi
    if [[ -n "$ssh_pid" ]] && kill -0 "$ssh_pid" 2>/dev/null; then
        kill -TERM "$ssh_pid" 2>/dev/null || true
        wait "$ssh_pid" 2>/dev/null || true
    fi
    printf '[go2] Logs retained: %s\n' "$RUN_DIR"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
python3 "$SCRIPT_DIR/mapping_preflight.py" idle --timeout 3 | tee "$RUN_DIR/idle.json"
echo '[go2] Checking whether RGB-D is already streaming...'
camera_status=0
python3 "$SCRIPT_DIR/mapping_preflight.py" camera --timeout 3 > "$RUN_DIR/camera_before.json" || camera_status=$?
if (( camera_status == 2 || camera_status == 3 )); then
    cat "$RUN_DIR/camera_before.json"
    echo 'ERROR: SLAM conflict or an existing camera is not streaming; no duplicate camera will be started.' >&2
    exit 1
fi
if (( camera_status != 0 )); then
    if [[ "$CAMERA_MODE" == existing ]]; then
        cat "$RUN_DIR/camera_before.json"
        echo 'ERROR: expected an existing streaming camera; start it first.' >&2; exit 1
    fi
    echo '[go2] Starting camera over SSH. Enter the Go2 SSH password if prompted.'
    echo '[go2] Camera startup output is in the session camera.log.'
    # Only a validated numeric domain is appended to this fixed remote command.
    ssh -tt -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=3 \
        "$SSH_TARGET" "bash --noprofile --norc -s -- $ROS_DOMAIN_ID" \
        < "$SCRIPT_DIR/go2_camera_session.sh" > "$RUN_DIR/camera.log" 2>&1 &
    ssh_pid=$!
else
    echo '[go2] Reusing the streaming camera; it will not be stopped by this script.'
fi
echo '[go2] Waiting up to 90 seconds for RGB, aligned depth, camera_info, L1 and odometry...'
if ! python3 "$SCRIPT_DIR/mapping_preflight.py" ready --timeout 90 | tee "$RUN_DIR/sensors.json"; then
    echo "ERROR: sensors not ready; inspect $RUN_DIR/camera.log and sensors.json" >&2
    exit 1
fi
if [[ -n "$ssh_pid" ]] && ! kill -0 "$ssh_pid" 2>/dev/null; then
    echo 'ERROR: owned SSH camera session exited during startup' >&2; exit 1
fi
echo '[go2] Starting RTAB-Map Mapping + RViz. Move Go2 only with the operator controller.'
echo '[go2] Press Ctrl+C here to stop and validate the saved DB.'
export GO2_SKIP_BUILD=1
setsid bash "$SCRIPT_DIR/run_mapping.sh" "$DB" &
mapping_pid=$!
wait "$mapping_pid"
