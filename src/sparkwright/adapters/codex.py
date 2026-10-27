"""OpenAI Codex adapter generator (SYSTEM S8.1-S8.4).

Capability mapping:
  spawn_agent      -> custom agents in .codex/agents/*.toml, spawned by the main Codex agent
  create_workspace -> not provided; the Runner supplies branches (S8.2)
  enforce_paths    -> .codex/hooks.json PreToolUse hook running `sparkwright guard --host codex`
                      (Codex asks you to trust project hooks once, with /hooks)
  model_for        -> inherits the session model; Runner tiers apply to CLI runs
Skills go to .agents/skills/<name>/SKILL.md, where Codex discovers repository skills.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..runner.personas import load_all
from .claude_code import BUILD_PERSONAS, REVIEW_PERSONAS
from .neutral import load_skills
from .slots import CODEX, slots

READ_ONLY_RULES = ("\n\n## Isolation rules for this host\n\n- Read only the files named in your task.\n"
                   "- You have no conversation history and must not ask for it.\n"
                   "- Do not create, edit or delete any file, and do not run commands that change anything.\n"
                   "- Return only the output your instructions describe.\n")
BUILD_RULES = ("\n\n## Rules for this host\n\n- Your task text names a prompt file and a workspace. Read the prompt file first.\n"
               "- Edit files only inside the workspace. SparkWright reverts anything you change outside your allowed paths.\n"
               "- Never touch specs/approvals.jsonl or run `sparkwright approve`.\n"
               "- Finish with only the JSON reply the instructions ask for.\n")


def agent_name(persona: str) -> str:
    return "sparkwright_" + persona.replace("-", "_")


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # JSON string escapes are valid TOML basic-string escapes


def _agent_toml(persona, build: bool) -> str:
    kind = "Builds in a task workspace" if build else "Read-only SparkWright Inspector"
    return (f"name = {_toml_str(agent_name(persona.name))}\n"
            f"description = {_toml_str(f'{kind}. {persona.job}')}\n"
            f"developer_instructions = {_toml_str(persona.prompt.strip() + (BUILD_RULES if build else READ_ONLY_RULES))}\n")


def generate(out_dir: Path | str, root: Path | str | None = None) -> list[str]:
    out = Path(out_dir)
    written: list[str] = []

    def put(rel: str, text: str) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
        written.append(rel)

    personas = load_all(root)
    for name in REVIEW_PERSONAS:
        put(f".codex/agents/{agent_name(name)}.toml", _agent_toml(personas[name], build=False))
    for name in BUILD_PERSONAS:
        put(f".codex/agents/{agent_name(name)}.toml", _agent_toml(personas[name], build=True))
    sl = slots(CODEX)
    for skill in load_skills():
        put(f".agents/skills/{skill.name}/SKILL.md",
            f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n{skill.render(**sl).strip()}\n")
    hooks = {"hooks": {"PreToolUse": [{"matcher": "Bash|apply_patch",
                                       "hooks": [{"type": "command", "command": "sparkwright guard --host codex",
                                                  "timeout": 30, "statusMessage": "SparkWright guard"}]}]}}
    put(".codex/hooks.json", json.dumps(hooks, indent=2) + "\n")
    return written
