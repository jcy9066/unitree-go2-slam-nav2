#!/usr/bin/env bash
# Payload executed by laptop_slam.sh over an owned SSH PTY. No motion commands.
set -Eeuo pipefail
domain="${1:-0}"
[[ "$domain" =~ ^[0-9]+$ ]] && (( domain <= 232 )) || exit 2
if [[ ! -f "$HOME/ros2_realsense_456_ws/activate.bash" ]]; then
    echo 'ERROR: Go2 RealSense environment missing: ~/ros2_realsense_456_ws/activate.bash' >&2
    exit 1
fi
set +u
source "$HOME/ros2_realsense_456_ws/activate.bash"
set -u
export ROS_DOMAIN_ID="$domain" ROS_LOCALHOST_ONLY=0
camera_pid=''
cleanup() {
    trap - EXIT HUP INT TERM
    if [[ -n "$camera_pid" ]] && kill -0 "$camera_pid" 2>/dev/null; then
        kill -INT -- "-$camera_pid" 2>/dev/null || true
        wait "$camera_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
setsid ros2 launch realsense2_camera rs_launch.py \
    camera_namespace:=/ camera_name:=camera \
    depth_module.depth_profile:=640x480x30 rgb_camera.color_profile:=640x480x15 \
    enable_color:=true enable_depth:=true enable_infra1:=false enable_infra2:=false \
    enable_sync:=false align_depth.enable:=true pointcloud.enable:=false \
    enable_accel:=false enable_gyro:=false \
    depth_module.emitter_enabled:=1 depth_module.emitter_on_off:=false &
camera_pid=$!
wait "$camera_pid"
