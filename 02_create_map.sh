#!/usr/bin/env bash
# PC mapping entry point. Start the camera manually in the Go2 SSH terminal.
set -Eeuo pipefail
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
usage() {
    echo 'Usage: bash ./02_create_map.sh [start|check|plan|sensors] [new_map.db]'
    echo 'Default: start. Explicit DB paths remain supported. No camera SSH or motion commands.'
}
if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then usage; exit 0; fi
MODE=start
if [[ "${1:-}" =~ ^(start|check|plan|sensors)$ ]]; then MODE=$1; shift; fi
(( $# <= 1 )) && [[ "${1:-new.db}" == *.db ]] || { usage >&2; exit 2; }
source "$REPO_ROOT/scripts/_env.sh"
MAP_DIR="$(go2_map_directory)"
DB="$(realpath -m -- "${1:-$MAP_DIR/map_$(date +%Y%m%d_%H%M%S)_$$/rtabmap.db}")"
# Explicit names remain possible, but new Mapping DBs must stay under the shared map root.
[[ "$DB" == "$MAP_DIR/"*/rtabmap.db ]] || {
    echo 'ERROR: 신규 지도는 ~/maps/<지도 ID>/rtabmap.db 위치에 저장해야 합니다.' >&2
    exit 2
}
if [[ -e "$DB" || -L "$DB" ]]; then
    printf 'ERROR: map database already exists; refusing overwrite: %s\n' "$DB" >&2
    exit 1
fi
if [[ "$MODE" == plan ]]; then
    printf 'New database: %s\nCamera: run manually on Go2 before Mapping.\n' "$DB"
    echo 'No build, SSH, ROS nodes or map files created.'
    exit 0
fi
if [[ "$MODE" == check ]]; then export GO2_SKIP_BUILD=1; fi
go2_load_environment
if [[ "$MODE" == check ]]; then
    echo '[go2] Environment ready; no camera, ROS nodes or Mapping started.'
    exit 0
fi
go2_require_network
PYTHON_BIN=${GO2_PYTHON:-python3}
if [[ "$MODE" == sensors ]]; then
    exec "$PYTHON_BIN" "$REPO_ROOT/scripts/mapping_preflight.py" ready --timeout 20
fi
[[ -n ${DISPLAY:-} ]] || { echo 'ERROR: RViz needs a desktop/X11 DISPLAY.' >&2; exit 1; }
for dependency in setsid flock; do
    command -v "$dependency" >/dev/null || { echo "ERROR: missing $dependency" >&2; exit 1; }
done
mkdir -p -- "$MAP_DIR"
exec 9>"$MAP_DIR/.mapping.lock"
flock -n 9 || { echo 'ERROR: another Mapping session is running.' >&2; exit 1; }
RUN_DIR="$MAP_DIR/mapping_sessions/$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p -- "$RUN_DIR" "$(dirname -- "$DB")"
printf '%s\n' "$DB" > "$RUN_DIR/database_path.txt"
LAUNCH_STARTED=0
PREVIEW_PID=''
finish() {
    local status=$1
    trap - EXIT
    go2_stop_launch
    if [[ -n "$PREVIEW_PID" ]]; then
        kill -TERM "$PREVIEW_PID" 2>/dev/null || true
        wait "$PREVIEW_PID" 2>/dev/null || true
        PREVIEW_PID=''
    fi
    if [[ "$LAUNCH_STARTED" != 1 ]]; then return; fi
    if (( status != 0 && status != 130 )); then
        printf '[go2] Launch failed (%s); partial DB retained, latest map unchanged: %s\n' "$status" "$DB" >&2
    elif "$PYTHON_BIN" "$REPO_ROOT/scripts/mapping_preflight.py" validate-db "$DB"; then
        if ! "$PYTHON_BIN" "$REPO_ROOT/scripts/map_catalog.py" register "$DB"; then
            echo '[map] 메타데이터 저장 실패. 원본 DB는 보존하고 선택 상태는 변경하지 않습니다.' >&2
            exit 1
        fi
        for pointer in .last_map .selected_map; do
            printf '%s\n' "$DB" > "$MAP_DIR/$pointer.$$.tmp"
            mv -- "$MAP_DIR/$pointer.$$.tmp" "$MAP_DIR/$pointer"
        done
        printf '[map] 지도 저장 완료: %s\n' "$DB"
        echo '[map] 다음 단계: bash ./03_run_nav.sh view'
    else
        echo '[go2] DB validation failed; partial file preserved, latest map unchanged.' >&2
        if (( status == 0 )); then exit 1; fi
    fi
}
trap 'finish "$?"' EXIT
"$PYTHON_BIN" "$REPO_ROOT/scripts/mapping_preflight.py" idle --timeout 3 | tee "$RUN_DIR/idle.json"
echo '[go2] Waiting for the camera started on Go2, L1 and native odometry...'
"$PYTHON_BIN" "$REPO_ROOT/scripts/mapping_preflight.py" ready --timeout 90 | tee "$RUN_DIR/sensors.json"
printf '[go2] Mapping new DB: %s\n' "$DB"
echo '[go2] Move Go2 only with the operator controller. Ctrl+C saves and validates the DB.'
"$PYTHON_BIN" "$REPO_ROOT/scripts/map_preview_capture.py" --output "$(dirname -- "$DB")/preview.png" &
PREVIEW_PID=$!
LAUNCH_STARTED=1
go2_launch launch go2_slam_nav mapping.launch.py \
    database_path:="$DB" localize_only:=false restart_map:=false use_rtabmapviz:=true
