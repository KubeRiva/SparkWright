"""Adapter contract (SYSTEM S8.1, S8.2).

Every host adapter maps four capabilities. A capability the host lacks is
declared `None`, and the Runner supplies it.
"""
from __future__ import annotations

from typing import Optional, Protocol


class Adapter(Protocol):
    name: str

    def spawn_agent(self, persona: str, inputs: dict) -> str:
        """Run `persona` in a fresh context on `inputs` (paths, task text); return its raw output."""

    def create_workspace(self, task_id: str) -> str:
        """Create an isolated workspace for a task; return its path."""

    def enforce_paths(self, rules: dict[str, list[str]]) -> None:
        """Install or apply protected-path rules for agent roles."""

    def model_for(self, tier: str) -> str:
        """Return the model the host uses for a provider-neutral tier."""


#: Who supplies each capability, per host. "runner" means SparkWright's Runner fills the gap (S8.2).
CAPABILITIES: dict[str, dict[str, Optional[str]]] = {
    "cli": {
        "spawn_agent": "runner: direct model API call with a clean context",
        "create_workspace": "runner: git branch and working copy (build loop, Phase 3)",
        "enforce_paths": "runner + `sparkwright check` role-trailer checks",
        "model_for": "runner: .sparkwright/config.yaml tiers",
    },
    "claude-code": {
        "spawn_agent": "host: plugin agents (read-only tools, omitClaudeMd) via the Agent tool",
        "create_workspace": None,
        "enforce_paths": "host: PreToolUse guard hook (Write/Edit/Bash) + `sparkwright check`",
        "model_for": "host: model: inherit",
    },
    "codex": {
        "spawn_agent": "host: custom agents in .codex/agents/*.toml spawned by the main agent",
        "create_workspace": None,
        "enforce_paths": "host: .codex/hooks.json PreToolUse guard (Bash, apply_patch) + `sparkwright check`",
        "model_for": "host: session model",
    },
    "gemini": {
        "spawn_agent": "host: extension subagents (agents/*.md, own context window)",
        "create_workspace": None,
        "enforce_paths": "host: hooks/hooks.json BeforeTool guard (write_file, replace, run_shell_command) + `sparkwright check`",
        "model_for": "host: model: inherit",
    },
    "agents-md": {
        "spawn_agent": None,
        "create_workspace": None,
        "enforce_paths": None,
        "model_for": None,
    },
}


def missing(host: str) -> list[str]:
    """Capabilities the Runner must supply for this host."""
    return sorted(k for k, v in CAPABILITIES[host].items() if v is None)
