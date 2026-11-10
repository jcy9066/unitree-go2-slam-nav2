---
name: go2-failure-analysis
description: Diagnose Go2 doorway navigation failures using ROS 2 traces, RTAB-Map pose, Global/Local Costmaps and DWB. Use for hesitation, replanning, oscillation or contact risk.
---

# Failure isolation

Start with the earliest failed stage. Do not change multiple parameter groups at once.

| Symptom | Confirm first | Candidate cause |
| --- | --- | --- |
| Existing map visible; wrong robot position | `map → odom`, ICP, initial yaw | Localization |
| Door appears blocked in Costmap | Obstacle cells vs inflation cells | LiDAR TF, clearing, footprint |
| Global Path exists; local motion fails | DWB rejected trajectories | Critics, sampled velocities |
| Back-and-forth motion | /cmd_vel_nav vs /cmd_vel | Oscillation, controller and smoother |
| Detour generated repeatedly | Global Costmap, BT 1 Hz replanning | Recovery and progress checks |
| Intermittent stop/Idle | command timestamps, DDS jitter | `sport_ctrl` 0.25 s timeout |
| Real foot contacts door | full walking foot/leg sweep | Invalid footprint assumption |

## Method
1. State the observed symptom and reproduce it under the same safe conditions.
2. Separate mapping, localization, planning, controller and actuation evidence.
3. List at least one competing explanation. Identify what evidence would distinguish them.
4. Propose the smallest reversible change, explicit before → after values, anticipated impact and potential risks.
5. Plan local checks first, then no-motion ROS checks. Physical motion stays with the operator.
6. Record whether the hypothesis is confirmed, rejected or not tested.
7. Update the canonical HTML and Draft PR after collecting evidence; never claim pass from plausibility alone.

Do not replace Planner/Controller or Critic without a documented reason and a baseline comparison.
