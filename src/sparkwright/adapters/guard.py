"""SparkWright guard for host agents (SYSTEM S6.5, S8.4).

Run as `sparkwright guard` from a PreToolUse hook: reads the hook JSON on stdin and
prints a permission decision. Shipping it inside the CLI keeps it cross-platform.
"""
import json, os, re, sys
from pathlib import Path

HUMAN_GATED = {"specs/constitution.md", "agents.md", "claude.md", ".sparkwright/config.yaml"}
GATED_PREFIXES = ("personas/", ".claude/")
FOLD = sys.platform.startswith(("win", "darwin"))  # case-insensitive file systems


def norm(rel):
    return rel.lower() if FOLD else rel


def locked_tests(root, ws=None):
    out = set()
    for appr in [root / "specs" / "approvals.jsonl"] + ([ws / "specs" / "approvals.jsonl"] if ws else []):
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
        rel = p.resolve().relative_to(root).as_posix()
    except ValueError:
        return None, ""
    ws = None
    flags = re.I if FOLD else 0  # case-insensitive file systems: .SPARKWRIGHT is .sparkwright
    m = re.match(r"^\.sparkwright/worktrees/([^/]+)/(.*)$", rel, flags)
    if m:  # a build workspace: apply the same rules relative to the workspace root
        ws, rel = root / ".sparkwright" / "worktrees" / m.group(1), m.group(2)
    elif norm(rel).startswith(".sparkwright/"):
        if re.match(r"^\.sparkwright/runs/[^/]+/([\w.-]+\.json|transcript\.md|[\w-]+\.result\.md)$", rel, flags) \
                and not rel.lower().endswith(".jsonl"):
            return None, ""  # host agents hand their replies and transcripts to the CLI through these files
        return "deny", "SparkWright run state is written only by the sparkwright CLI."
    rel = norm(rel)
    if rel == norm("specs/approvals.jsonl") or rel == norm("specs/events.jsonl"):
        return "deny", "Approvals and events are recorded only by the sparkwright CLI."
    if norm(rel) == ".git" or norm(rel).startswith(".git/"):
        return "deny", "Agents may not edit git internals."
    if rel in locked_tests(root, ws):
        return "deny", f"{rel} is a locked test; changing it needs an approved change request."
    if rel in {norm(h) for h in HUMAN_GATED} or rel.lower() in HUMAN_GATED or rel.startswith(GATED_PREFIXES):
        return "ask", f"{rel} is human-gated in SparkWright; confirm this change."
    return None, ""


def decide_bash(cmd):
    if re.search(r"approv[^\s/]*\.jsonl|approv\w*\*|events\.jsonl|\.sparkwright/runs/[^\s'\"]*\.jsonl|\.sparkwright/ledger", cmd, re.I):
        return "deny", "Agents may not touch approvals, events or SparkWright run state."
    if re.search(r"\bsparkwright\b[^|;&\n]*\bapprove\b", cmd, re.I):
        return "deny", "`sparkwright approve` records a human decision; ask the user to run it."
    if re.search(r"constitution\.md|\.sparkwright/config\.yaml|AGENTS\.md|CLAUDE\.md|\.claude/|personas/", cmd, re.I):
        return "ask", "This command touches a SparkWright human-gated file; confirm it."
    return None, ""


def main():
    try:
        data = json.loads(sys.stdin.read() or "{}")
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
