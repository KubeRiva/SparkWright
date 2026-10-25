"""SparkWright guard for host agents (SYSTEM S6.5, S8.4).

Run as `sparkwright guard` from a PreToolUse hook: reads the hook JSON on stdin and
prints a permission decision. Shipping it inside the CLI keeps it cross-platform.
"""
import json, os, re, sys
from pathlib import Path

HUMAN_GATED = {"specs/constitution.md", "agents.md", "claude.md", "gemini.md", ".sparkwright/config.yaml"}
GATED_PREFIXES = ("personas/", ".claude/", ".codex/", ".agents/", ".gemini/")
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
    if ws is None and strict(root) and not exempt(root, rel):
        return "deny", (f"SparkWright strict mode: {rel} may only change inside a task build. Find or draft the task "
                        f"that covers it, have the user approve it, then run `sparkwright build <task> --next` "
                        f"(or open a change request with `sparkwright change new <ID>`).")
    return None, ""


_CFG = {}


def _config(root):
    key = str(root)
    if key not in _CFG:
        try:
            from sparkwright.core import config as config_mod
            _CFG[key] = config_mod.load(root)[0]
        except Exception:  # noqa: BLE001 - a guard must never crash the host
            _CFG[key] = {}
    return _CFG[key]


def strict(root):
    """D009 (S8.5): `guard: {strict: true}` keeps agents out of code that no task build covers."""
    return bool((_config(root).get("guard") or {}).get("strict"))


def exempt(root, rel):
    """Files that never need a task (the drift-exempt list, S2.6), e.g. specs and Markdown."""
    import fnmatch
    globs = _config(root).get("drift_exclude") or ["specs/**", ".sparkwright/**", "*.md", ".gitignore", ".gitattributes",
                                                     "LICENSE", "NOTICE", "personas/**", "templates/**"]
    try:
        from sparkwright.core.globs import match
        return match(rel, [norm(g) for g in globs])
    except Exception:  # noqa: BLE001
        return any(fnmatch.fnmatch(rel, norm(g)) for g in globs)


def decide_bash(cmd, root=None):
    if re.search(r"approv[^\s/]*\.jsonl|approv\w*\*|events\.jsonl|\.sparkwright/runs/[^\s'\"]*\.jsonl|\.sparkwright/ledger", cmd, re.I):
        return "deny", "Agents may not touch approvals, events or SparkWright run state."
    if re.search(r"\bsparkwright\b[^|;&\n]*\bapprove\b", cmd, re.I):
        return "deny", "`sparkwright approve` records a human decision; ask the user to run it."
    if re.search(r"constitution\.md|\.sparkwright/config\.yaml|AGENTS\.md|CLAUDE\.md|GEMINI\.md|\.claude/|\.codex/|"
                 r"\.agents/|\.gemini/|personas/", cmd, re.I):
        return "ask", "This command touches a SparkWright human-gated file; confirm it."
    if root is not None and strict(root) and re.search(r"\bgit\b[^|;&\n]*\bcommit\b", cmd) \
            and "SparkWright-Task" not in cmd and "sparkwright" not in cmd.lower():
        return "ask", ("SparkWright strict mode: commits should name their task (SparkWright-Task trailer) or come "
                       "from a task build; confirm this commit with the user.")
    return None, ""


PATCH_PATH = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.M)
RANK = {None: 0, "ask": 1, "deny": 2}


def _cmd(tool_input):
    c = tool_input.get("command", "")
    return " ".join(map(str, c)) if isinstance(c, list) else str(c)


def _targets(host, tool_name, tool_input):
    """(kind, values): kind is 'bash' with the command, or 'paths' with the files a tool call would write."""
    if host == "codex":
        if tool_name == "apply_patch":
            return "paths", PATCH_PATH.findall(_cmd(tool_input) or str(tool_input.get("input") or ""))
        return "bash", [_cmd(tool_input)]
    if host == "gemini":
        if tool_name == "run_shell_command":
            return "bash", [_cmd(tool_input)]
        target = tool_input.get("file_path") or tool_input.get("absolute_path") or tool_input.get("path")
        return "paths", [target] if target else []
    if tool_name == "Bash" or ("command" in tool_input and "file_path" not in tool_input):
        return "bash", [str(tool_input.get("command", ""))]
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    return "paths", [target] if target else []


def decide(host, root, tool_name, tool_input):
    kind, values = _targets(host, tool_name, tool_input or {})
    best = (None, "")
    for v in values:
        d = decide_bash(v, root) if kind == "bash" else decide_path(root, v)
        if RANK[d[0]] > RANK[best[0]]:
            best = d
    return best


def main(host="claude-code"):
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    env_root = {"claude-code": "CLAUDE_PROJECT_DIR", "gemini": "GEMINI_PROJECT_DIR"}.get(host, "")
    root = Path((env_root and os.environ.get(env_root)) or data.get("cwd") or ".").resolve()
    decision, reason = decide(host, root, data.get("tool_name"), data.get("tool_input") or {})
    if not decision:
        return 0
    if host == "gemini":  # Gemini CLI: decision deny/allow; no interactive ask from hooks
        reason = reason if decision == "deny" else reason + " Ask the user to make this change."
        print(json.dumps({"decision": "deny", "reason": reason}))
    elif host == "codex":  # Codex does not support "ask" yet: deny and tell the agent to ask the user
        reason = reason if decision == "deny" else reason + " Ask the user to make this change."
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": decision,
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
