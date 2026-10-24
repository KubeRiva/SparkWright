"""Claude Code adapter generator (SYSTEM S8.1–S8.4).

Capability mapping:
  spawn_agent      -> plugin agents (read-only tools, omitClaudeMd) launched with the Agent tool
  create_workspace -> not provided by the plugin; the Runner supplies branches (S8.2)
  enforce_paths    -> PreToolUse hook (hooks/guard.py)
  model_for        -> `model: inherit` (the user's Claude Code model); Runner tiers apply to CLI runs
"""
from __future__ import annotations

import json
from pathlib import Path

from .. import __version__
from ..runner.personas import load_all
from .neutral import load_skills

PLUGIN = "sparkwright"
REVIEW_PERSONAS = ["coverage-auditor", "contradiction-hunter", "newcomer", "devils-advocate",
                   "buildability-checker", "security-reviewer", "code-reviewer"]
BUILD_PERSONAS = ["test-author", "builder"]  # need to edit files and run tests in the task workspace

RUN_BUILD_AGENT = (
    "launch ONE agent with the Agent tool, `subagent_type` `sparkwright:sparkwright-<data.persona>`, "
    "and ONLY this task text: \"Read <absolute path of data.prompt> and follow it. Work only inside "
    "<data.workspace>. When finished, reply with only the JSON the instructions ask for.\" Pass no "
    "conversation history or opinion. Write the agent's final reply verbatim to `data.result_file`."
)

RUN_AGENTS = (
    "For EACH name in `personas`, launch the Agent tool in parallel with "
    "`subagent_type` set to `sparkwright:sparkwright-<persona>` (for example "
    "`sparkwright:sparkwright-coverage-auditor`). Give each agent ONLY this task text: "
    "\"Review the artifact in <absolute path of context>. Return only the JSON array.\" "
    "Do not pass any conversation history, summaries or your own opinion. When each "
    "agent returns, write its reply verbatim to `<outputs_dir>/<persona>.json`. "
    "Wait for all agents before continuing."
)

GUARD = r"""#!/usr/bin/env python3
""" + '"""SparkWright guard: protects approvals and locked tests; asks before human-gated files."""' + r"""
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
    m = re.match(r"^\.sparkwright/worktrees/([^/]+)/(.*)$", rel)
    if m:  # a build workspace: apply the same rules relative to the workspace root
        ws, rel = root / ".sparkwright" / "worktrees" / m.group(1), m.group(2)
    elif rel.startswith(".sparkwright/"):
        return "deny", "SparkWright run state is written only by the sparkwright CLI."
    rel = norm(rel)
    if rel == norm("specs/approvals.jsonl") or rel == norm("specs/events.jsonl"):
        return "deny", "Approvals and events are recorded only by the sparkwright CLI."
    if rel == ".git" or rel.startswith(".git/"):
        return "deny", "Agents may not edit git internals."
    if rel in locked_tests(root, ws):
        return "deny", f"{rel} is a locked test; changing it needs an approved change request."
    if rel in {norm(h) for h in HUMAN_GATED} or rel.lower() in HUMAN_GATED or rel.startswith(GATED_PREFIXES):
        return "ask", f"{rel} is human-gated in SparkWright; confirm this change."
    return None, ""


def decide_bash(cmd):
    if re.search(r"approv[^\s/]*\.jsonl|approv\w*\*|events\.jsonl|\.sparkwright/(runs|ledger)", cmd, re.I):
        return "deny", "Agents may not touch approvals, events or SparkWright run state."
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
"""


def _agent_md(persona, build: bool = False) -> str:
    desc = persona.job.replace("\n", " ")
    if build:
        return (
            "---\n"
            f"name: {PLUGIN}-{persona.name}\n"
            f"description: SparkWright {persona.name}. {desc}\n"
            "tools: [Read, Grep, Glob, Edit, Write, Bash]\n"
            "model: inherit\n"
            "omitClaudeMd: true\n"
            "---\n\n"
            f"{persona.prompt.strip()}\n\n"
            "## Rules for this host\n\n"
            "- Your task text names a prompt file and a workspace. Read the prompt file first.\n"
            "- Edit files only inside the workspace. SparkWright reverts anything you change outside your allowed paths.\n"
            "- You may run the project's tests with Bash inside the workspace.\n"
            "- Never touch specs/approvals.jsonl or run `sparkwright approve`.\n"
            "- Finish with only the JSON reply the instructions ask for.\n"
        )
    return (
        "---\n"
        f"name: {PLUGIN}-{persona.name}\n"
        f"description: SparkWright Inspector. {desc}\n"
        "tools: [Read, Grep, Glob]\n"
        "model: inherit\n"
        "omitClaudeMd: true\n"
        "---\n\n"
        f"{persona.prompt.strip()}\n\n"
        "## Isolation rules for this host\n\n"
        "- Read only the context file named in your task. It contains the artifact, its parents and the constitution.\n"
        "- You have no conversation history and must not ask for it.\n"
        "- Do not edit any file. Return only the JSON array described above.\n"
    )


def generate(out_dir: Path | str, root: Path | str | None = None) -> list[str]:
    out = Path(out_dir)
    written: list[str] = []

    def put(rel: str, text: str, mode: int | None = None) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        if mode:
            p.chmod(mode)
        written.append(rel)

    personas = load_all(root)
    agent_paths = []
    for name in REVIEW_PERSONAS:
        put(f"agents/{PLUGIN}-{name}.md", _agent_md(personas[name]))
        agent_paths.append(f"./agents/{PLUGIN}-{name}.md")
    for name in BUILD_PERSONAS:
        put(f"agents/{PLUGIN}-{name}.md", _agent_md(personas[name], build=True))
        agent_paths.append(f"./agents/{PLUGIN}-{name}.md")
    for skill in load_skills():
        body = skill.render(run_agents=RUN_AGENTS, run_build_agent=RUN_BUILD_AGENT)
        put(f"skills/{skill.name}/SKILL.md",
            f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n{body.strip()}\n")
    put("hooks/guard.py", GUARD, 0o755)
    manifest = {
        "name": PLUGIN,
        "version": __version__,
        "description": "SparkWright: evidence-backed, multi-level, verified spec-driven development.",
        "license": "Apache-2.0",
        "author": {"name": "KubeRiva"},
        "homepage": "https://github.com/kuberiva/sparkwright",
        "agents": agent_paths,
        "hooks": {"PreToolUse": [{"matcher": "Write|Edit|MultiEdit|NotebookEdit|Bash",
                                  "hooks": [{"type": "command",
                                             "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/guard.py\""}]}]},
    }
    put(".claude-plugin/plugin.json", json.dumps(manifest, indent=2) + "\n")
    put("README.md", (
        "# SparkWright plugin for Claude Code\n\n"
        "Generated by `sparkwright adapt claude-code`. Do not edit by hand; edit the neutral\n"
        "skills and personas in the SparkWright package and regenerate.\n\n"
        "Requires the `sparkwright` CLI on PATH (`pip install sparkwright`).\n\n"
        "Skills: " + ", ".join(s.name for s in load_skills()) + ".\n"
    ))
    return written


def write_marketplace(repo_root: Path | str, plugin_rel: str) -> Path:
    p = Path(repo_root) / ".claude-plugin" / "marketplace.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "name": PLUGIN,
        "owner": {"name": "KubeRiva"},
        "plugins": [{"name": PLUGIN, "source": f"./{plugin_rel}",
                     "description": "Evidence-backed, multi-level, verified spec-driven development."}],
    }, indent=2) + "\n", encoding="utf-8")
    return p
