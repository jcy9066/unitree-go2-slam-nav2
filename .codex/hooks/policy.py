#!/usr/bin/env python3
"""Codex lifecycle guardrails (advisory; not a server-side security boundary)."""

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = "jcy9066/unitree-go2-slam-nav2"
ALLOWED_MCP_WRITES = {
    "create_branch", "create_or_update_file", "push_files",
    "create_pull_request", "update_pull_request", "pull_request_review_write",
}
FORBIDDEN_MCP = {
    "merge_pull_request", "enable_auto_merge", "delete_file",
    "delete_branch", "delete_repository", "actions_run_trigger",
    "update_pull_request_branch",
}


def root(cwd):
    result = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, timeout=4, check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else Path(cwd)


def current_branch(cwd):
    result = subprocess.run(
        ["git", "-C", cwd, "branch", "--show-current"],
        capture_output=True, text=True, timeout=4, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))


def risk_reason(tool, args, cwd):
    """Return a reason to deny or None; this is not a shell parser."""
    arg = args if isinstance(args, dict) else {}
    name = tool.rsplit("__", 1)[-1].lower()

    if tool.lower().startswith("mcp__") and ("github" in tool.lower() or "merge" in name):
        if name in FORBIDDEN_MCP or "merge_pull_request" in name or "actions" in name:
            return "GitHub merge, branch updates via PR, deletion, and Actions are prohibited."
        if name in ALLOWED_MCP_WRITES:
            owner = arg.get("owner")
            repo = arg.get("repo")
            if (owner, repo) != ("jcy9066", "unitree-go2-slam-nav2"):
                return "GitHub writes are limited to jcy9066/unitree-go2-slam-nav2."
            if name in {"push_files", "create_or_update_file"}:
                target = str(arg.get("branch", "")).removeprefix("refs/heads/")
                if not target or target in {"main", "master"}:
                    return "Do not write directly to main/master or an unspecified branch."
            if name == "create_branch" and arg.get("branch") in {"main", "master"}:
                return "Creating or replacing main/master is prohibited."
            if name == "create_pull_request":
                if arg.get("draft") is not True:
                    return "Only Draft pull requests are allowed."
                if str(arg.get("head", "")) in {"main", "master"}:
                    return "The PR head must be a task branch."
            if name == "update_pull_request":
                if arg.get("draft") is False or arg.get("state") == "closed":
                    return "Do not mark a Draft PR ready or close it without user approval."
            if name == "pull_request_review_write":
                if str(arg.get("method", "")).lower().startswith("delete"):
                    return "Deleting existing reviews is prohibited."
                if str(arg.get("event", "")).upper() in {"APPROVE", "DISMISS"}:
                    return "Codex may comment or request changes, not approve or dismiss reviews."
        elif name.startswith(("delete_", "update_ref", "create_repository", "fork_repository")):
            return "This GitHub write tool is outside the allowed operation list."

    if tool.lower() in {"bash", "exec_command", "shell_command"}:
        command = str(arg.get("command", "") or "")
        lower = command.lower()
        # Do not treat a mention in a document as a shell action. Review compound
        # commands carefully: these simple checks are not a complete parser.
        patterns = [
            (r"\bgh\s+pr\s+merge\b", "GitHub PR merge is prohibited."),
            (r"\bgh\s+pr\s+ready\b", "Only Draft PRs are allowed."),
            (r"\bgh\s+(?:run|workflow)\b", "GitHub Actions commands are prohibited."),
            (r"\bgh\s+api\b.*(?:/merge\b|actions/)", "Direct GitHub merge/Actions API calls are prohibited."),
            (r"\bcurl\b.*(?:/merge\b|actions/)", "Direct GitHub merge/Actions API calls are prohibited."),
            (r"\bgit\s+push\b[^\n]*(?:--force\b|--mirror\b|\s-f\b)", "Force or mirror pushes are prohibited."),
            (r"\bgit\s+push\b[^\n]*(?:\bmain\b|\bmaster\b|HEAD:(?:refs/heads/)?main\b)", "Push to main/master is prohibited."),
            (r"\b(?:ros2\s+topic\s+pub|ros2\s+action\s+send_goal)\b", "Codex must not publish motion commands or send navigation goals."),
            (r"\b(?:rm|shred)\b[^\n]*\.db\b", "Deleting the RTAB-Map database is prohibited."),
            (r"(?:restart_map:=true|--delete_db_on_start)", "Destructive RTAB-Map restart is prohibited."),
        ]
        for regex, reason in patterns:
            if re.search(regex, lower, re.IGNORECASE):
                return reason
        if re.search(r"\bgit\s+(?:commit|push)\b", lower) and current_branch(cwd) in {"main", "master"}:
            return "Git commit/push is blocked while on main/master."
    return None


def static_checks(repo_root):
    report = []
    shell = [repo_root / "scripts" / p for p in ("_env.sh", "run_mapping.sh", "run_nav.sh")]
    for path in shell:
        if not path.exists():
            report.append(f"FAIL missing {path.relative_to(repo_root)}")
            continue
        try:
            p = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True,
                               timeout=7, check=False)
            report.append(f"{'PASS' if p.returncode == 0 else 'FAIL'} bash -n {path.name}")
        except (OSError, subprocess.TimeoutExpired):
            report.append(f"BLOCKED bash -n {path.name}")
    py = list((repo_root / "go2_slam_nav" / "launch").glob("*.launch.py"))
    py += [repo_root / "go2_slam_nav" / "setup.py", Path(__file__)]
    for path in py:
        if not path.exists():
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            report.append(f"FAIL Python syntax {path.name}")
    doc = repo_root / "docs" / "go2_navigation_validation.html"
    if not doc.is_file():
        report.append("FAIL canonical HTML missing")
    elif "<html" not in doc.read_text(encoding="utf-8").lower():
        report.append("FAIL canonical HTML structure")
    else:
        report.append("PASS canonical HTML exists")
    return report


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}
    event = data.get("hook_event_name")
    cwd = str(data.get("cwd") or Path.cwd())

    if event == "SessionStart":
        print(
            "Go2 Nav2 repository guardrails: check AGENTS.md; no Actions or Merge. "
            "Use separate branches/worktrees. Preserve existing RTAB-Map DB. "
            "Update docs/go2_navigation_validation.html after code changes. "
            "Robot motion is operator-only. MCP tools are allowlisted; this is "
            "not a GitHub server-side Merge permission restriction."
        )
    elif event == "PreToolUse":
        reason = risk_reason(data.get("tool_name", ""), data.get("tool_input", {}), cwd)
        if reason:
            deny(reason)
    elif event == "Stop":
        checks = static_checks(root(cwd))
        print(json.dumps({
            "systemMessage": (
                "Go2 static check only: " + "; ".join(checks) +
                ". ROS 2 runtime and physical Go2 tests remain NOT TESTED unless "
                "actual operator evidence is present."
            )
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
