# Codex ↔ GitHub MCP access policy

Repository: `jcy9066/unitree-go2-slam-nav2`  
Project Branch: `fix/nav2-narrow-passage`  
Draft PR: [#1](https://github.com/jcy9066/unitree-go2-slam-nav2/pull/1)  
Canonical test log: [go2_navigation_validation.html](go2_navigation_validation.html)

## 1. Allowed actions

| Capability | Method | Scope |
| --- | --- | --- |
| Inspect code, branches, commits, PRs | GitHub MCP read tools | Single repository |
| Create task branch | GitHub MCP `create_branch`; local `git switch -c` | Task branches only |
| Change files | Local Codex editor, MCP `create_or_update_file` | No `main` edits |
| Commit and push | Local `git commit`, `git push`; MCP `push_files` | Task branches only |
| Open and edit PR | MCP `create_pull_request`, `update_pull_request` | Draft PRs only |
| Read and write reviews | MCP `pull_request_read`, `pull_request_review_write` | Comments and requests for changes only |
| Merge PR | **DENIED** | No agent merge |
| GitHub Actions | **DENIED** | No read, run, create, or inspect |
| Delete DB / robot movement | **DENIED** | Operator-only physical tests |

`git switch` is a **local Git command**. GitHub MCP tools manage remote repository data; they do not change a local worktree's current branch.

## 2. MCP tool allowlist

The checked-in `.codex/config.toml` uses the official GitHub MCP Docker image and **only** these tools:

```text
get_file_contents
get_commit
list_branches
list_commits
create_branch
create_or_update_file
push_files
create_pull_request
update_pull_request
list_pull_requests
pull_request_read
pull_request_review_write
search_pull_requests
```

It also explicitly excludes `merge_pull_request`. **Do not** enable broad `repos` or `pull_requests` toolsets. Toolsets are additive and may expose tools that were not in the allowlist. Do not enable `actions`.

These settings restrict **the MCP interface**. They do not revoke the credential's other GitHub API privileges or local terminal access. The project hooks add a second, advisory layer of command checks. They are not a server-side authorization rule.

## 3. Local setup — manual user action required

You must configure a GitHub fine-grained token on the machine that runs Codex. ChatGPT's GitHub connection **does not automatically authenticate the local Codex process**.

1. In GitHub, create a **fine-grained personal access token** restricted to the repository `jcy9066/unitree-go2-slam-nav2`.
2. Grant repository permissions: **Contents — Read and write**, **Pull requests — Read and write**; Metadata is read implicitly. Do **not** grant Administration, Actions, Workflows, or other permissions.
3. In the local terminal, export the token for that terminal session; never commit it:

   ```bash
   read -r -s -p "GitHub PAT: " GITHUB_PERSONAL_ACCESS_TOKEN
   echo
   export GITHUB_PERSONAL_ACCESS_TOKEN
   ```

4. Ensure Docker and Codex CLI are installed and Docker runs. Open this repository in Codex, **trust its project configuration**, and review project hooks with `/hooks`.
5. Restart Codex if it was already running. Verify the configured server and tools:

   ```bash
   docker info >/dev/null
   codex mcp list
   ```

   Inside Codex, open `/mcp`. Confirm `github_go2` exposes the listed tools and **does not expose** `merge_pull_request` or `actions_*`.

Token handling: do not place the PAT in `config.toml`, `hooks.json`, `AGENTS.md`, a Git commit, command-line arguments, or a file in this repository. The checked-in MCP command passes it from the host environment into the official Docker container.

## 4. Server-side Merge enforcement — not configured here

**Current GitHub inspection (2026-11-10 KST):** the ruleset list for this repository returned an empty array. Branch-protection details could not be read (GitHub integration returned 403), so existing legacy protection cannot be confirmed.

A fine-grained PAT with Contents/PR write permission may still be capable of merging a PR by using GitHub's API directly. A Codex MCP tool allowlist and Hooks do **not** remove this possibility. To make Merge impossible for the Codex identity:

1. Prefer a **dedicated GitHub App/bot identity**, not a PAT that acts as the owner's own account.
2. Open **Repository → Settings → Rules → Rulesets**. Create a ruleset targeting the `main` branch.
3. Restrict updates to `main`. Make only the human maintainer an authorized bypass actor where the plan and UI allow it; **do not add the Codex App/bot to the bypass list**.
4. Also require Pull Requests and human review where appropriate, and block force pushes and deletions.
5. Test using the bot identity: it must be able to push its **task branch** but must fail to push or merge into `main`. Test the human maintainer's intended Merge separately.

**Important:** if Codex uses a PAT created under the same human GitHub account, GitHub's actor-level rules generally see the same identity. You cannot grant that token a unique `no merge` permission while granting the human owner Merge using account identity alone. Separate identity or external policy enforcement is required.

Do not add a GitHub Actions workflow to enforce this rule.

## 5. Parallel work and reviews

- Use an independent task branch and `git worktree` per Codex agent, for example `fix/nav2-costmap-check` and `fix/nav2-localization-check`.
- One designated integrator updates the shared Draft PR #1. Other agents open separate Draft PRs targeting the task integration branch or provide reviewed commits.
- A code review may comment, request changes, or propose fixes. Do not approve PRs on behalf of the human maintainer.
- Preserve the original RTAB-Map DB. Do not run Go2 motion commands.
- Update the **same** `docs/go2_navigation_validation.html` on later changes. Record Before → After, reason, evidence, and `PASS` / `FAIL` / `BLOCKED` / `NOT TESTED`.
- Never auto-merge or enable auto-merge.

## 6. Hook check and troubleshooting

Project hooks: `.codex/hooks.json` → `.codex/hooks/policy.py`.

```bash
python3 -m py_compile .codex/hooks/policy.py
python3 - <<'PY'
import tomllib
with open('.codex/config.toml', 'rb') as f:
    cfg = tomllib.load(f)
assert 'github_go2' in cfg['mcp_servers']
print('config.toml: syntax PASS')
PY
```

To test policy without a network call:

```bash
printf '%s\n' '{"hook_event_name":"PreToolUse","tool_name":"mcp__github_go2__merge_pull_request","tool_input":{}}' |
  python3 .codex/hooks/policy.py
```

Expected: JSON with `permissionDecision: "deny"`.

Project Hooks must be reviewed/trusted by the local Codex client. If they are disabled, bypassed or unsupported by the active tool path, their protection will not apply. Enforce **non-merge** at the GitHub actor/branch level for a hard guarantee.

## 7. Status

- Repository MCP configuration: **committed**.
- Allowed tool list and Merge exclusion: **configured; local server not authenticated or started by this chat**.
- Hook policy: **committed; activation requires project trust and `/hooks` review**.
- GitHub Ruleset: **none reported** as of 2026-11-10.
- GitHub branch protection: **not confirmed** due to 403.
- Codex live MCP connection and denied-merge integration test: **NOT TESTED**.
