#!/usr/bin/env bash
# Read-only-in-motion comparison: copies the DB through the normal view runner.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if (( $# < 1 || $# > 2 )); then
    echo 'Usage: bash scripts/localization_compare.sh [aligned|reference] [optional_map.db]' >&2
    exit 2
fi
case "$1" in
    aligned)
        export GO2_LOCALIZATION_PROFILE=aligned_visual
        MAP="${2:-$HOME/GH/go2_l1_nav2_ws/analysis/left_door_repair_20261110/navigation_map.db}"
        ;;
    reference)
        export GO2_LOCALIZATION_PROFILE=reference_visual
        MAP="${2:-$HOME/go2_lidar_slam/maps/visual/active/rtabmap.db}"
        # Different map coordinates: old route masks/waypoints cannot be reused.
        export GO2_FIRST_DOOR_ONLY=false
        ;;
    *) echo 'Expected aligned or reference' >&2; exit 2 ;;
esac
export GO2_ENABLE_MOTION=false
exec bash "$SCRIPT_DIR/laptop_nav.sh" view "$MAP"
