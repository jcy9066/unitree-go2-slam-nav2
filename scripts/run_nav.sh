#!/usr/bin/env bash
# One-command existing RTAB-Map DB -> localization -> Nav2 + RViz2.
# Usage: bash scripts/run_nav.sh [existing_map.db]
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MAP_DIR="$(realpath -m -- "${GO2_MAP_DIR:-$HOME/go2_maps}")"

if (( $# > 1 )); then
    echo 'Usage: bash scripts/run_nav.sh [existing_map.db]' >&2
    exit 2
fi
if (( $# == 1 )); then
    DB="$1"
elif [[ -s "$MAP_DIR/.last_map" ]]; then
    IFS= read -r DB < "$MAP_DIR/.last_map"
else
    echo 'ERROR: no map selected. Pass the existing .db path or run run_mapping.sh first.' >&2
    exit 1
fi
DB="$(realpath -m -- "$DB")"
if [[ ! -s "$DB" ]]; then
    printf 'ERROR: RTAB-Map database not found or empty: %s\n' "$DB" >&2
    exit 1
fi

# shellcheck disable=SC1091
source "$SCRIPT_DIR/_env.sh"

# Localization may write session data. Always work on a copy to protect the source map.
SESSION_DIR="$MAP_DIR/nav_sessions/$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p -- "$SESSION_DIR"
SESSION_DB="$SESSION_DIR/rtabmap.db"
cp -p -- "$DB" "$SESSION_DB"
printf '%s\n' "$DB" > "$SESSION_DIR/source_db_path.txt"

printf '[go2] Original map (unchanged): %s\n' "$DB"
printf '[go2] Nav session map copy:    %s\n' "$SESSION_DB"
echo '[go2] Starting L1 + RGB-D localization + Nav2 + RViz2.'
echo '[go2] Motion bridge is disabled unless GO2_ENABLE_MOTION=true is explicitly set.'
echo '[go2] Confirm localized robot pose and costmaps in RViz2 BEFORE sending any goal.'
ros2 launch go2_slam_nav nav.launch.py \
    database_path:="$SESSION_DB" \
    localize_only:=true \
    restart_map:=false \
    use_rviz:=false \
    use_nav2_rviz:=true \
    enable_motion:="${GO2_ENABLE_MOTION:-false}" \
    record_diagnostics:="${GO2_RECORD_DIAGNOSTICS:-true}" \
    record_obstacle_sensors:="${GO2_RECORD_OBSTACLE_SENSORS:-false}" \
    diagnostics_dir:="$SESSION_DIR/diagnostics"
