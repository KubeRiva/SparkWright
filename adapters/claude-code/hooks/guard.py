#!/usr/bin/env python3
"""SparkWright guard: protects approvals and locked tests; asks before human-gated files."""
import json, os, re, sys
from pathlib import Path

HUMAN_GATED = {"specs/constitution.md", "agents.md", "claude.md", ".sparkwright/config.yaml"}
GATED_PREFIXES = ("personas/", ".claude/")
FOLD = sys.platform.startswith(("win", "darwin"))  # case-insensitive file systems


def norm(rel):
    return rel.lower() if FOLD else rel


def locked_tests(root):
    out = set()
    appr = root / "specs" / "approvals.jsonl"
    if appr.is_file():
        for line in appr.read_text(encoding="utf-8").splitlines():
            try:
                i = json.loads(line).get("id", "")
            except ValueError:
                continue
            if i.startswith("test:"):
                out.add(norm(i[5:]))
    return out


def decide_path(root, target):
    p = Path(target)
    if not p.is_absolute():
        p = root / p
    try:
        rel = norm(p.resolve().relative_to(root).as_posix())
    except ValueError:
        return None, ""
    if rel == norm("specs/approvals.jsonl"):
        return "deny", "Approvals are recorded only by a human running `sparkwright approve`."
    if rel in locked_tests(root):
        return "deny", f"{rel} is a locked test; changing it needs an approved change request."
    if rel in {norm(h) for h in HUMAN_GATED} or rel.lower() in HUMAN_GATED or rel.startswith(GATED_PREFIXES):
        return "ask", f"{rel} is human-gated in SparkWright; confirm this change."
    return None, ""


def decide_bash(cmd):
    if re.search(r"approvals\.jsonl", cmd, re.I):
        return "deny", "Agents may not touch specs/approvals.jsonl; approvals are human-only."
    if re.search(r"\bsparkwright\b[^|;&\n]*\bapprove\b", cmd, re.I):
        return "deny", "`sparkwright approve` records a human decision; ask the user to run it."
    if re.search(r"constitution\.md|\.sparkwright/config\.yaml|AGENTS\.md|CLAUDE\.md|\.claude/|personas/", cmd, re.I):
        return "ask", "This command touches a SparkWright human-gated file; confirm it."
    return None, ""


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or ".").resolve()
    tool_input = data.get("tool_input") or {}
    if data.get("tool_name") == "Bash" or ("command" in tool_input and "file_path" not in tool_input):
        decision, reason = decide_bash(str(tool_input.get("command", "")))
    else:
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
        decision, reason = decide_path(root, target) if target else (None, "")
    if decision:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": decision,
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
