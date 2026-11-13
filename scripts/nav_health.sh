#!/usr/bin/env bash
# Inspect the current session; no startup, Goal, velocity or bridge activation.
set -Eeuo pipefail
GO2_HEALTH_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export GO2_WS_ROOT="${GO2_WS_ROOT:-$(dirname -- "$(dirname -- "$GO2_HEALTH_DIR")")/unitree_go2_pr1_ws}"
export GO2_SKIP_BUILD=1
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}" ROS_LOCALHOST_ONLY=0
export CYCLONEDDS_URI="${CYCLONEDDS_URI:-<CycloneDDS><Domain><General><Interfaces><NetworkInterface name=\"eno1\"/></Interfaces></General></Domain></CycloneDDS>}"
source "$GO2_HEALTH_DIR/_env.sh"
exec python3 "$GO2_HEALTH_DIR/nav_health.py" "$@"
