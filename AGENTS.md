# Go2 SLAM / Nav2 — Agent Rules

Scope: this repository, its Codex agents, and all subagents. Read this file first. Read only the relevant skill for the task. Check the current Git branch and latest remote head before editing.

## Goal and baseline
- Platform: Unitree Go2, ROS 2 Humble laptop, internal L1 + D435i, native Go2 odometry, RTAB-Map, Nav2 (NavFn + DWB). Legacy RoboSense launches are not the default pipeline.
- Target test: a 90 cm doorway. Preserve the original RTAB-Map database.
- Current integration Draft PR: #2, branch `fix/l1-rgbd-forward-only`, base `main`. PR #1 (`fix/nav2-narrow-passage`) is historical context.
- Canonical validation record: `docs/go2_navigation_validation.html`.
- Nav mode: `localize_only=true`, `Mem/IncrementalMemory=false`. RTAB-Map localizes while Nav2 updates its Costmaps. Do not describe this as continuous map extension.

## Environment source of truth
- Manage installation dependencies, package/channel versions, external source revisions, build settings and deployment defaults in the root `environment.json`. Do not add a competing `requirements.txt`, Conda YAML or hardcoded installer package list.
- The project Conda environment is named `go2_nav2`. Install ROS 2 Humble and the project runtime inside that environment. Select its Python ABI from the compatible RoboStack package set and record it in `environment.json`.
- Keep `scripts/install_student.sh` as the setup entry point. Its default command must create the Conda environment, install declared dependencies, build Unitree/project packages and verify the installation. Print `go2_nav2 환경 설정이 완료되었습니다.` only after every required step succeeds. Keep an explicit read-only `plan` mode.
- Build and run with the selected Conda interpreter and ROS environment. Do not source `/opt/ros` or reuse system-built Unitree/project overlays in the Conda deployment. A system Python bootstrap may read JSON before Conda activation.
- Preserve required ROS `package.xml` metadata and check its dependencies against the environment specification. Generated activation files, resolved package snapshots and compatibility exports derive from `environment.json`; do not maintain them as independent configuration sources.
- Keep existing Conda environments, original maps and credentials intact. Runtime robot-network interface and data paths may be explicit installation overrides; do not silently reconfigure the host network.

## Git and parallel Codex workflow
1. Never commit to `main`. Do not merge or enable auto-merge without explicit user authorization.
2. Do not create, edit, view, trigger, or use GitHub Actions. Use local checks only.
3. For concurrent agents, allocate a separate task branch and Git worktree to each writer. Do not let two agents edit the same file concurrently. Share changes through review or separate PRs; assign one integrator to the current integration PR #2.
4. Before editing, check `git status --short`, `git branch --show-current`, current PR/branch head and unmerged work. Do not overwrite another agent's changes.
5. Keep independent code/config changes in separate commits. Use a short Korean/English commit subject with explicit before → after values. Put rationale, expected effects, limitations and verification evidence in commit body and Draft PR.
   **Mandatory immediate commit and push:** After every individual file edit or independently completed modification, create a dedicated commit and push it to the current task branch immediately, before starting the next edit. Do not batch multiple edits into a later commit, postpone a push, or leave completed modifications uncommitted/unpushed. Never push directly to `main`. This applies to code, configuration, scripts, documentation, and validation records.
6. Do not force-push, rewrite shared history, or delete branches by default.
7. After changing code, configuration, scripts or validation evidence, update the **same** HTML file and its revision notes in a separate docs commit. Never create a second competing validation HTML.

## Safety and non-destructive operation
- Do not initiate physical robot motion, `NavigateToPose` goals, `/cmd_vel` publication or Unitree Sport motion commands. The operator must perform live movement and safety checks.
- Do not claim physical validation from static analysis, compile checks, simulated data, or RViz screenshots alone.
- Do not use `restart_map:=true`, `--delete_db_on_start`, or overwrite/delete an existing .db. Navigation must use a copy of the original DB.
- Current 70×36 cm configured Footprint, 1 cm padding, 20 cm Local Inflation Radius, and 30 cm Global Inflation Radius are the operator-requested reduced profile based on the official 70×31 cm standing dimensions and reported 47×30 cm foot stance. They remain **unverified for the dynamic walking envelope at 0.5 m/s**. The 80×42 cm / 45 cm laptop baseline and earlier 70×40 cm / 42 cm PR settings are historical profiles, not proven collision boundaries.
- Treat initial localization separately from door-passage path planning; verify `map → odom → base_link` before navigation.
- Inspect sensor TF, time synchronization and Costmaps before modifying algorithms. No Planner/Controller/Critic replacement without a reproducible reason and comparison.
- Do not make uncontrolled changes to robot firmware, safety settings, command timeouts or network configuration.

## Verification
- Evidence statuses: `PASS`, `FAIL`, `BLOCKED`, `NOT TESTED`. Never report `PASS` without the command/log/observation proving it.
- First perform read-only inspection, static checks, and no-motion tests. Only the user/operator runs supervised, low-speed motion tests.
- Run `bash -n` on shell scripts; `python3 -m ast` or `ast.parse` on Python; build via `colcon` only when the local ROS environment is installed.
- Follow `T00–T10` in `docs/go2_navigation_validation.html`; record failed steps and reason without silently skipping.
- Keep evidence separated by environment: GitHub source inspection, static checks, ROS 2 runtime, RViz evaluation, physical Go2 movement.
- No GitHub Actions for verification.

## Skills
Use the most specific skill under `.agents/skills/`:
- `go2-config-audit`: parameters, TF, Footprint, Costmaps.
- `go2-mapping-verify`: RTAB-Map Mapping and database integrity.
- `go2-localization-verify`: existing DB, ICP, initial Pose.
- `go2-navigation-verify`: NavFn, DWB, velocity and real-time Costmaps.
- `go2-failure-analysis`: evidence-based fault isolation.
- `go2-validation-report`: update the canonical HTML and PR.

## GitHub MCP permissions and mandatory review flow
- Codex MCP configuration: `.codex/config.toml`; setup and security limitations: `docs/codex_github_access.md`.
- Allowed: inspect this repository; create/switch task branches (switch is a **local git** command); modify/commit/push task branches; create/update **Draft** PRs; write review comments or request changes.
- Prohibited: PR Merge or auto-merge, PR approvals on the owner's behalf, direct `main` writes, force push, GitHub Actions, destructive Git/DB operations, unapproved robot motion.
- The MCP server uses a **tool allowlist** and excludes `merge_pull_request`. No broad toolsets may be enabled. Do not request other MCP connectors to perform a forbidden operation.
- Repository-level restrictions are **not** established just by these files. GitHub repo rulesets currently reported none; the user must separately configure a bot identity and `main` protection for hard No-Merge enforcement.
- Never commit PATs, OAuth tokens, secrets or credential files. A local Codex GitHub token is not inherited from ChatGPT's connected GitHub integration.
- Verify the available MCP tool list in `/mcp` and locally approve/review hooks in `/hooks` before using Codex.

Hooks are a convenience guardrail, not a complete security boundary. Consult `.codex/hooks.json` and trust the project hooks through `/hooks` after review.
