#!/usr/bin/env bash
# One-command LiDAR + RTAB-Map mapping. Usage: bash scripts/run_mapping.sh [new_map.db]
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MAP_DIR="$(realpath -m -- "${GO2_MAP_DIR:-$HOME/go2_maps}")"
mkdir -p -- "$MAP_DIR"

if (( $# > 1 )); then
    echo 'Usage: bash scripts/run_mapping.sh [new_map.db]' >&2
    exit 2
fi
DB="$(realpath -m -- "${1:-$MAP_DIR/go2_$(date +%Y%m%d_%H%M%S).db}")"
if [[ "$DB" != *.db ]]; then
    echo 'ERROR: database output path must end with .db' >&2
    exit 2
fi
if [[ -e "$DB" ]]; then
    printf 'ERROR: map database already exists; refusing overwrite: %s\n' "$DB" >&2
    exit 1
fi
mkdir -p -- "$(dirname -- "$DB")"

# shellcheck disable=SC1091
source "$SCRIPT_DIR/_env.sh"

remember_map() {
    if [[ -s "$DB" ]]; then
        printf '%s\n' "$DB" > "$MAP_DIR/.last_map"
        printf '\n[go2] Saved map DB: %s\n' "$DB"
        echo '[go2] Next: bash scripts/run_nav.sh  (or pass the DB file explicitly)'
    else
        printf '\n[go2] No populated DB detected at %s; latest map unchanged.\n' "$DB" >&2
    fi
}
trap remember_map EXIT

printf '[go2] Mapping new DB: %s\n' "$DB"
echo '[go2] L1 + RGB-D mapping (start the camera on Go2 first); stop with Ctrl+C to flush the database.'
ros2 launch go2_slam_nav mapping.launch.py \
    database_path:="$DB" \
    localize_only:=false \
    restart_map:=false \
    use_rtabmapviz:=true
