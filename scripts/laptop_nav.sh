#!/usr/bin/env bash
# Current laptop entry point. All physical navigation is operator-controlled.
set -Eeuo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
export GO2_WS_ROOT="${GO2_WS_ROOT:-$(dirname -- "$REPO_ROOT")/unitree_go2_pr1_ws}"
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export ROS_LOCALHOST_ONLY=0
if [[ -z "${CYCLONEDDS_URI:-}" ]]; then
    export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="eno1"/></Interfaces></General></Domain></CycloneDDS>'
fi
MODE="${1:-view}"
MAP="${2:-$HOME/GH/go2_l1_nav2_ws/analysis/saved_map_fix_20261109/navigation_map.db}"
if [[ "$MODE" != check && "$MODE" != view && "$MODE" != drive ]]; then
    echo 'Usage: bash scripts/laptop_nav.sh [check|view|drive] [map.db]' >&2
    exit 2
fi
if (( $# > 2 )); then
    echo 'ERROR: too many arguments' >&2
    exit 2
fi
if [[ ! -s "$MAP" ]]; then
    printf 'ERROR: map not found: %s\n' "$MAP" >&2
    exit 1
fi
if [[ "$MODE" == check ]]; then
    source "$SCRIPT_DIR/_env.sh"
    printf '[go2] Workspace ready: %s\n[go2] Source map: %s\n' "$GO2_WS_ROOT" "$MAP"
    echo '[go2] Check complete; no ROS nodes or motion bridge started.'
    exit 0
fi
# Live ROS startup needs the robot Ethernet link. Do not alter network settings.
if [[ ! -r /sys/class/net/eno1/carrier ]] || [[ "$(cat /sys/class/net/eno1/carrier 2>/dev/null || true)" != 1 ]]; then
    echo 'ERROR: eno1 has no Ethernet link. Power on/connect Go2 first.' >&2
    exit 1
fi
# Operators explicitly select drive after checking localization in view mode.
export GO2_ENABLE_MOTION=false
if [[ "$MODE" == drive ]]; then
    export GO2_ENABLE_MOTION=true
fi
exec bash "$SCRIPT_DIR/run_nav.sh" "$MAP"
