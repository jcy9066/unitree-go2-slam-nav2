#!/usr/bin/env bash
# PC saved-map entry point. Camera startup stays in the operator's Go2 terminal.
set -Eeuo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
usage() {
    echo 'Usage: bash run_nav.sh [view|drive|plan|check] [existing.db] [--profile legacy|aligned_visual|reference_visual]'
    echo '       bash run_nav.sh health [--seconds 4] | bridge | shell'
    echo '       bash run_nav.sh aligned|reference existing.db'
    echo 'Default: view (motion disabled). Existing DB path alone is also supported.'
}
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then usage; exit 0; fi
MODE=view
if [[ "${1:-}" =~ ^(view|drive|plan|check|health|bridge|shell|aligned|reference)$ ]]; then MODE=$1; shift; fi
PROFILE=${GO2_LOCALIZATION_PROFILE:-legacy}
COMPARISON=0
if [[ "$MODE" == aligned || "$MODE" == reference ]]; then
    PROFILE=${MODE}_visual; MODE=view; COMPARISON=1
fi
DB=''
if [[ "$MODE" != health ]]; then
    while (( $# )); do
        case "$1" in
            --profile) (( $# >= 2 )) || { usage >&2; exit 2; }; PROFILE=$2; shift 2 ;;
            --*) usage >&2; exit 2 ;;
            *) [[ -z "$DB" ]] || { usage >&2; exit 2; }; DB=$1; shift ;;
        esac
    done
fi
case "$PROFILE" in
    aligned) PROFILE=aligned_visual ;; reference) PROFILE=reference_visual ;;
    legacy|aligned_visual|reference_visual) ;; *) echo 'ERROR: unknown localization profile.' >&2; exit 2 ;;
esac
if [[ "$MODE" == bridge || "$MODE" == shell ]] && [[ -n "$DB" ]]; then usage >&2; exit 2; fi
if (( COMPARISON )) && [[ -z "$DB" ]]; then
    echo 'ERROR: comparison requires an explicit DB path; map coordinate systems differ.' >&2; exit 2
fi
source "$REPO_ROOT/scripts/_env.sh"
MAP_DIR="$(go2_map_directory)"
if [[ "$MODE" =~ ^(view|drive|plan)$ ]]; then
    if [[ -z "$DB" && -s "$MAP_DIR/.last_map" ]]; then IFS= read -r DB < "$MAP_DIR/.last_map"; fi
    [[ -n "$DB" ]] || { echo 'ERROR: no map selected. Pass the existing .db path.' >&2; exit 1; }
fi
if [[ -n "$DB" ]]; then
    DB="$(realpath -m -- "$DB")"
    [[ -f "$DB" && -s "$DB" ]] || { printf 'ERROR: database not found or empty: %s\n' "$DB" >&2; exit 1; }
fi
if [[ "$MODE" == plan ]]; then
    printf 'Source database: %s\nProfile: %s\nCamera: run manually on Go2.\n' "$DB" "$PROFILE"
    echo 'Original DB will be copied for localization. No build, SSH, ROS nodes or files created.'
    exit 0
fi
export GO2_SKIP_BUILD=1
go2_load_environment
PYTHON_BIN=${GO2_PYTHON:-python3}
if [[ "$MODE" == check ]]; then
    echo '[go2] Environment ready; no ROS nodes or motion bridge started.'
    exit 0
fi
if [[ "$MODE" == shell ]]; then exec /bin/bash --noprofile --norc -i; fi
go2_require_network
if [[ "$MODE" == health ]]; then exec "$PYTHON_BIN" "$REPO_ROOT/scripts/nav_health.py" "$@"; fi
if [[ "$MODE" == bridge ]]; then
    if ros2 node list 2>/dev/null | "$PYTHON_BIN" -c 'import sys; sys.exit(0 if "/sport_ctrl" in sys.stdin.read().splitlines() else 1)'; then
        echo 'ERROR: sport_ctrl already exists. Keep the original bridge terminal.' >&2; exit 1
    fi
    echo '[go2] Starting DISABLED bridge. No Sport request while enabled=false.'
    exec ros2 run go2_cmd_processor sport_ctrl --ros-args -r __node:=sport_ctrl \
        -r cmd_vel:=/go2_nav/cmd_vel -p enabled:=false -p max_linear_x:=0.5 -p max_angular_z:=1.8
fi
[[ -n ${DISPLAY:-} ]] || { echo 'ERROR: RViz needs a desktop/X11 DISPLAY.' >&2; exit 1; }
"$PYTHON_BIN" "$REPO_ROOT/scripts/mapping_preflight.py" idle --timeout 3
"$PYTHON_BIN" "$REPO_ROOT/scripts/mapping_preflight.py" ready --timeout 20
SESSION_PARENT="$MAP_DIR/nav_sessions"
SESSION_DIR="$SESSION_PARENT/$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p -- "$SESSION_PARENT"
mkdir -- "$SESSION_DIR"
SESSION_DB="$SESSION_DIR/rtabmap.db"
cp -p -- "$DB" "$SESSION_DB"
printf '%s\n' "$DB" > "$SESSION_DIR/source_db_path.txt"
ENABLE_MOTION=false
if [[ "$MODE" == drive ]]; then ENABLE_MOTION=true; fi
if [[ "$PROFILE" == reference_visual ]]; then export GO2_FIRST_DOOR_ONLY=false; fi
printf '[go2] Original map (unchanged): %s\n[go2] Nav session map copy: %s\n' "$DB" "$SESSION_DB"
printf '[go2] Profile: %s; motion bridge: %s\n' "$PROFILE" "$ENABLE_MOTION"
echo '[go2] Verify physical pose and Costmaps before the operator sends any goal.'
trap go2_stop_launch EXIT
go2_launch launch go2_slam_nav nav.launch.py \
    database_path:="$SESSION_DB" localize_only:=true restart_map:=false \
    use_rviz:=false use_nav2_rviz:=true enable_motion:="$ENABLE_MOTION" \
    localization_profile:="$PROFILE" first_door_only:="${GO2_FIRST_DOOR_ONLY:-false}" \
    record_diagnostics:="${GO2_RECORD_DIAGNOSTICS:-true}" \
    record_obstacle_sensors:="${GO2_RECORD_OBSTACLE_SENSORS:-false}" \
    diagnostics_dir:="$SESSION_DIR/diagnostics"
