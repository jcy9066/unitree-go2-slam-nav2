---
name: go2-navigation-verify
description: Verify Go2 Nav2 Global/Local Costmaps, NavFn path, DWB trajectories, command timing and 90 cm doorway passage readiness. Use before and after navigation parameter changes.
---

# Navigation verification

## Precondition
Review `AGENTS.md` and the canonical HTML. Confirm RTAB-Map localization is valid first. Do not command robot motion.

## Procedure
1. Check effective Local Costmap resolution 0.02 m, Global Costmap nominal resolution 0.05 m, two 0.42 m inflation radii, and the proposed 70×40 cm Footprint with 1 cm padding.
2. Inspect static occupied cells and LiDAR-marked cells separately from Inflation costs.
3. Observe Global NavFn Path and DWB scored/rejected local trajectories. A valid Global Path does not guarantee safe local motion.
4. Compare DWB `max_vel_theta=1.0` with Velocity Smoother `0.6`, plus `trans_stopped_velocity=0.25` against max translational speed `0.15`.
5. Inspect `/cmd_vel_nav`, `/cmd_vel`, Unitree Sport request frequency and the `sport_ctrl` 0.25 s command timeout without publishing motion commands.
6. Check progress checker 0.5 m/10 s and default BT path recomputation/recovery behavior.
7. Require non-motion collision checks, walking-footprint validation and an operator-controlled emergency stop before field tests.
8. If the operator supplies real-run observations, record doorway dimensions, initial yaw, path, status, rear/side stepping, replanning, closest clearance and contact.

## Change policy
Tune one parameter group per commit. Keep NavFn and DWB until a specific failure mode demonstrates an algorithmic limitation.
