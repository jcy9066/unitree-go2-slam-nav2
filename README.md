# Unitree-Go2 Robot: SLAM and Nav2 Demos

*By: Hossein Naderi*

Welcome to the **Unitree-Go2 Robot SLAM and Nav2** repository! This project demonstrates the integration of SLAM (Simultaneous Localization and Mapping) and autonomous navigation using Nav2 on the Unitree-Go2 robot. The repository includes demonstration videos, source code, and comprehensive documentation to assist in replicating and building upon the showcased capabilities.&#8203;:contentReference[oaicite:0]{index=0}

---

## Table of Contents

1. [Overview](#overview)
2. [Demo Videos](#demo-videos)
3. [Project Structure](#project-structure)
4. [Workspace Setup](#workspace-setup)
5. [Launch Files](#launch-files)
6. [Detailed Project Explanations](#detailed-project-explanations)

---

## Overview

- **Robot Platform**: [Unitree-Go2](https://www.unitree.com/products/go2)
- **SLAM**: ROS 2 RTAB-Map
- **Navigation**: ROS 2 Nav2

### Key Features

- **Real-time mapping** in indoor and outdoor environments
- **Obstacle avoidance** using Nav2 and sensor data
- **Sensor fusion** combining RGB Depth Camera with LiDAR point cloud
- **Autonomous path planning** to specified goals
- **Facial recognition** capabilities for identifying individuals during navigation

---

## Demo Videos

1. **SLAM Demo Video**  
   *Demonstration of integrated SLAM with Unitree-Go2 using RTAB-Map in ROS2.*

   [![SLAM Demo Video](https://github.com/user-attachments/assets/99b8062b-3fb6-4a19-bc97-b03568393300)](https://github.com/user-attachments/assets/99b8062b-3fb6-4a19-bc97-b03568393300)

2. **Autonomous Navigation Demo Video**  
   *Demonstration of integrated Autonomous Navigation with Unitree-Go2 using Nav2 Stack in ROS2.*

   [![Autonomous Navigation Demo Video](https://github.com/user-attachments/assets/3f4abc8c-d612-4665-a894-e6b635843b2e)](https://github.com/user-attachments/assets/3f4abc8c-d612-4665-a894-e6b635843b2e)



## Dependencies



- **Unitree SDK**: [https://github.com/unitreerobotics/unitree_ros2](https://github.com/unitreerobotics/unitree_ros2)
- **LiDAR SDK**: [https://github.com/RoboSense-LiDAR/rslidar_sdk](https://github.com/RoboSense-LiDAR/rslidar_sdk)
- **LiDAR Messages**: [https://github.com/RoboSense-LiDAR/rslidar_msg](https://github.com/RoboSense-LiDAR/rslidar_msg)


---

## Workspace Setup



1. **Create your workspace:**
   ```bash
   mkdir -p ~/ws/src
   cd ~/ws/src
   ```

2. **Clone this repository:**
   ```bash
   git clone --branch fix/nav2-narrow-passage https://github.com/jcy9066/unitree-go2-slam-nav2.git

   ```
3. **Navigate to the repository:**

   ```bash
   cd ~/ws/src
   ```

4. **Import dependencies using `vcs`:**

   ```bash
   vcs import < unitree-go2-slam-nav2/dependencies.repo
   ```   
5. **Install dependencies and build the workspace:**

   ```bash
   cd ~/ws
   rosdep install --from-paths src --ignore-src -r -y
   colcon build
   ```

6. **Source the workspace:**

   ```bash
   source ~/ws/install/setup.bash
   ```

---

## Launch Files

1. **Launch the Intel RealSense camera node:**
    ```sh
    ros2 launch realsense2_camera rs_launch.py enable_gyro:=true enable_accel:=true unite_imu_method:=1 enable_infra1:=true enable_infra2:=true enable_sync:=true
    ```

2. **Launch everything on the robot for mapping with the LiDAR only:**
    ```sh
    ros2 launch go2_slam_nav mapping.launch.py
    ```

3. **Launch the robot with the RealSense camera and the LiDAR:**
    ```sh
    ros2 launch go2_slam_nav mapping_camera.launch.py
    ```
4. **Launch the navigation:**
    ```sh
    ros2 launch go2_slam_nav nav.launch.py
    ```

5. **Launch the exploration node only:**
    ```sh
    ros2 launch frontier frontier_update.launch.xml
    ```



Feel free to reach out if you have any questions or need further assistance with setting up the project.

## Detailed Project Explanations

For comprehensive explanations and insights into each project component, please refer to my portfolio:

- **SLAM Project**: [SLAM Project](https://h-naderi.github.io/projects/1-slam)
- **Autonomous Navigation**: [Navigation Project](https://h-naderi.github.io/projects/3-auto-nav-and-exploration)



---

## One-command Go2 mapping / localization / Nav2 (fork PR #1)

> **Environment:** ROS 2 Humble, Nav2, RTAB-Map, Unitree ROS 2 SDK, RoboSense LiDAR SDK, and a built colcon workspace. Scripts use the **LiDAR-only** pipeline; Intel RealSense RGB-D is not automatically started. Do not send a Nav2 goal until localization is verified.

The `run_*.sh` scripts assume the repository is at `~/ws/src/unitree-go2-slam-nav2`. Set `GO2_WS_ROOT=/path/to/ws` if your workspace is elsewhere. They source ROS 2 and your workspace automatically and run `colcon build --packages-select go2_slam_nav go2_cmd_processor` each time so installed launch/config changes are current. Set `GO2_SKIP_BUILD=1` to skip rebuilding an already built workspace.

**Mapping: make a new database (existing files never overwritten)**

```bash
cd ~/ws/src/unitree-go2-slam-nav2
bash scripts/run_mapping.sh
# or: bash scripts/run_mapping.sh "$HOME/go2_maps/lab_test.db"
# Ctrl+C at the end to allow RTAB-Map to save.
```

- Sets `localize_only:=false`, `restart_map:=false`.
- Starts the RoboSense LiDAR SDK, ICP odometry, RTAB-Map SLAM, and RTAB-Map visualization in one terminal.
- Uses a unique `~/go2_maps/go2_YYYYMMDD_HHMMSS.db` by default and records a completed DB path in `~/go2_maps/.last_map`.

**Navigation: load an existing database**

```bash
cd ~/ws/src/unitree-go2-slam-nav2
bash scripts/run_nav.sh "$HOME/.ros/rtabmap.db"  # replace with the real DB path
# or, after using run_mapping.sh:
bash scripts/run_nav.sh
```

- Validates that the DB file exists; **copies** it into a new `~/go2_maps/nav_sessions/` session directory to protect the original.
- Starts the RoboSense LiDAR SDK, ICP odometry, RTAB-Map **localization only**, Nav2 controller/planner/behavior/velocity smoother, Unitree sport command bridge, and **one Nav2 RViz2** instance.
- Does not regenerate the SLAM map or modify the original DB. Nav2 activation **does not prove** that the correct initial pose has been recovered.

**Environment / required checks**

```bash
echo "$ROS_DOMAIN_ID"                 # must agree with the Go2/ROS 2 DDS network
ros2 topic info /rslidar_points      # LiDAR data must be available
ros2 topic info /api/sport/request   # confirm Unitree command bridge/network
```

Also verify the robot's `base_link → base_laser` transform against the actual sensor mount; the upstream launch uses a fixed +0.20m Z offset. Before commanding movement, compare RViz2 robot pose with the real Go2 and inspect both Costmaps. If your existing workspace already contains a second original clone created by the old `dependencies.repo`, resolve duplicate ROS package directories before building.

**PR #1 experimental geometry:** local resolution `0.05→0.02m`, footprint `82×70→70×40cm` (unverified walking envelope), footprint padding explicitly `0.01m`, inflation `0.55→0.42m` (global and local). The Go2 walking footprint is **an assumption, not a measured safety boundary**. Do collision and no-motion checks before supervised, low-speed testing at the 90cm doorway. Do not assume a valid global plan proves collision safety.

**If tests still fail:** first inspect the map vs. Global/Local Costmap obstacle and inflation cells; then DWB rejected trajectories and `cmd_vel_nav → cmd_vel → /api/sport/request` timing, Progress Checker and default Behavior Tree periodic replanning. Investigate initial localization/`map→odom` separately. Change algorithms or Critics only with evidence and in separate commits. No GitHub Actions or automatic merge.
