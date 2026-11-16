# Go2 SLAM / Nav2 — Agent Rules

Scope: this repository, its Codex agents, and all subagents. Read this file first. Read only the relevant skill for the task. Check the current Git branch and latest remote head before editing.

## Goal and baseline
- Platform: Unitree Go2, ROS 2 Humble laptop, internal L1 + D435i, native Go2 odometry, RTAB-Map, Nav2 (NavFn + DWB). Legacy RoboSense launches are not the default pipeline.
- Target test: a 90 cm doorway. Preserve the original RTAB-Map database.
- PR #2 (`fix/l1-rgbd-forward-only`) is merged; PR #1 is historical. Current task branch: `feat/slam-nav2-tutorial-map-manager`, based on `main`. Never edit main directly.
- Canonical validation record: `slam_nav2_tutorial.html`.
- Nav mode: `localize_only=true`, `Mem/IncrementalMemory=false`. RTAB-Map localizes while Nav2 updates its Costmaps. Do not describe this as continuous map extension.

## Discuss unknowns before deciding
- Distinguish confirmed facts, agreed requirements and proposed choices. If a requirement is unclear or a choice changes the agreed scope, explain the alternatives and their effects and ask the user first. The user makes that decision.
- Wait for the user's answer before implementing work that depends on that choice. Continue only independent work already agreed. Silence, elapsed time and a preselected suggestion are not decisions.
- Do not copy existing defaults into a new feature merely because they are present in the repository. Do not assume authorization for additional device access or deployment settings.

## Environment source of truth
- Manage installation dependencies, package/channel versions, external source revisions, build settings and deployment defaults in the root `environment.json`. Do not add a competing `requirements.txt`, Conda YAML or hardcoded installer package list.
- The project Conda environment is named `go2_nav2`. Install ROS 2 Humble and the project runtime inside that environment. Select its Python ABI from the compatible RoboStack package set and record it in `environment.json`.
- Create it with `conda create --name go2_nav2` in the existing Conda installation's default envs location. Do not place a Conda environment in the repository or invent a separate permanent installation prefix. Use temporary source-build directories and install their results into the selected Conda environment.
- Retain `rtabmap_viz`: earlier logs confirm its use and the Mapping entry point starts it. Its source version and installation method belong in `environment.json`.
- Keep root `01_setup_env.sh` as the setup entry point. Inspect the actual `go2_nav2` packages, versions, activation variables, modules, ROS packages and build record before deciding to install. Reuse a matching environment without rebuilding; if an existing environment differs, list the mismatch and require interactive y/n consent before changing anything (n/noninteractive = no mutation). For a missing environment create, install, build and verify. Print exactly one applicable final success line: `[env] 기존 환경 검증 완료`, `[env] 환경 신규 구축 및 검증 완료`, or `[env] 기존 환경 수정 및 검증 완료`. Keep explicit read-only `plan` and `verify` modes.
- Build and run with the selected Conda interpreter and ROS environment. User-facing Mapping and Nav2 scripts automatically activate the verified `go2_nav2` environment if no Conda environment is active. Do not source `/opt/ros` or reuse system-built Unitree/project overlays in the Conda deployment; retain explicitly requested legacy system ROS mode only. A system Python bootstrap may read JSON before Conda activation.
- Preserve required ROS `package.xml` metadata and check its dependencies against the environment specification. Generated activation files, resolved package snapshots and compatibility exports derive from `environment.json`; do not maintain them as independent configuration sources.
- Keep existing Conda environments, original maps and credentials intact. Runtime robot-network interface and data paths may be explicit installation overrides; do not silently reconfigure the host network.
- Setup covers environment creation, dependency installation, builds and verification. Do not add robot SSH targets, NIC selection, map paths or motion/profile settings to the installer or its manifest unless the user explicitly requests them. Existing operator runtime settings stay separate.

## Shell entry points and camera operation
- Keep exactly four user-facing shell entry points at repository root: `01_setup_env.sh`, `02_create_map.sh`, `03_run_nav.sh`, `setup_maps.sh`. Keep `scripts/_env.sh` as the single internal shared shell helper; Python implementations remain under `scripts/`. Standalone administrator files `map_manager.py` and `map_manager.html` live at the repository root but are NOT tutorial entry points.
- Tutorial commands must use root-relative `bash ./01_setup_env.sh`, `bash ./02_create_map.sh` and `bash ./03_run_nav.sh` paths. Mapping and Nav2 stay separate. Store all newly created Mapping DBs under `~/maps/<unique ID>/rtabmap.db`; preserve explicit DB paths only within that root. Preserve original DB protection, shutdown validation and owned-process cleanup. Keep repository `maps/` archive policy and `setup_maps.sh` unchanged until separately approved.
- The camera is started with the existing ROS 2 RealSense command on Go2, independently of PC-side Mapping/Nav2. The final tutorial contains only that copy/paste camera command, not connection instructions, SSH terminal setup, or user-edited connection parameters. Do not deploy this repository to Go2 or introduce automatic camera SSH startup.
- Keep used health diagnostics and localization-profile selection as internal Nav2 subcommands rather than separate sh files. Beginner-facing HTML uses `bash ./03_run_nav.sh` as the default, motion-disabled map/pose view; optional health command is not another tutorial step. Select saved maps via `03_run_nav.sh select` without invoking Map Manager. Explicit `drive` mode is retained solely for operator-authorized physical motion. The shared runtime helper auto-detects one linked physical Ethernet interface (prefer Go2's 192.168.123.x subnet) and defaults ROS_DOMAIN_ID to 0 without prompting; ambiguous network connectivity must fail closed, and host network settings are never changed. Map Manager is completely independent from tutorial and shows only name, date and real preview; no creator/owner tracking. The tutorial map viewer is **serverless**. Its one-shot `scripts/open_tutorial.py` scans valid maps, generates ignored `maps_manifest.js` and `viewer_maps/` display-only PNG copies, opens the canonical HTML, and exits. It must never start a server, background process, robot control, or expose/modify original RTAB-Map databases, map metadata or Nav2 `.selected_map`. Re-run the launcher to index manually added maps; direct HTML opening uses the most recent saved index. Mapping captures both preview and (within size limits) full-resolution `map.png` without changing the original DB.

## Git and parallel Codex workflow
1. Never commit to `main`. Do not merge or enable auto-merge without explicit user authorization.
2. Do not create, edit, view, trigger, or use GitHub Actions. Use local checks only.
3. For concurrent agents, allocate a separate task branch and Git worktree to each writer. Do not let two agents edit the same file concurrently. Share changes through review or separate PRs; assign one integrator to the current task Draft PR.
4. Before editing, check `git status --short`, `git branch --show-current`, current PR/branch head and unmerged work. Do not overwrite another agent's changes.
5. Keep independent code/config changes in separate commits. Use a short Korean/English commit subject with explicit before → after values. Put rationale, expected effects, limitations and verification evidence in commit body and Draft PR.
   **Mandatory immediate commit and push:** After every individual file edit or independently completed modification, create a dedicated commit and push it to the current task branch immediately, before starting the next edit. Do not batch multiple edits into a later commit, postpone a push, or leave completed modifications uncommitted/unpushed. Never push directly to `main`. This applies to code, configuration, scripts, documentation, and validation records.
6. Do not force-push, rewrite shared history, or delete branches by default.
7. After changing code, configuration, scripts or validation evidence, update the **single canonical** `slam_nav2_tutorial.html` with current commands, date and factual verification scope in a separate docs commit. Never create a competing tutorial HTML or reintroduce obsolete command examples.

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
- Verify in order: environment; sensor reception; Mapping DB and optional preview; existing map selection; TF/initial pose/Costmaps; view (no motion); operator-supervised drive. Record failed or unavailable steps instead of skipping. Do not fabricate old T00–T10 checklists.
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
