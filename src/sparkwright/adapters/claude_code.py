"""Claude Code adapter generator (SYSTEM S8.1–S8.4).

Capability mapping:
  spawn_agent      -> plugin agents (read-only tools, omitClaudeMd) launched with the Agent tool
  create_workspace -> not provided by the plugin; the Runner supplies branches (S8.2)
  enforce_paths    -> PreToolUse hook running `sparkwright guard`
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
                   "buildability-checker", "security-reviewer", "code-reviewer", "theme-synthesizer", "architect",
                   "guide-writer", "question-auditor", "surveyor"]

RUN_SURVEYOR = (
    "Launch ONE fresh agent with the Agent tool, `subagent_type` `sparkwright:sparkwright-surveyor`, and ONLY this task "
    "text: \"Read <absolute path of data.prompt> and follow it. Reply with only the JSON object.\" Write the agent's "
    "reply verbatim to `data.result_file`."
)

RUN_GUIDE_AGENT = (
    "Launch ONE fresh agent with the Agent tool, `subagent_type` `sparkwright:sparkwright-<data.step>`, and ONLY this "
    "task text: \"Read <absolute path of data.prompt> and follow it. Reply with only what it asks for.\" Write the "
    "agent's reply verbatim to `data.result_file`."
)

RUN_ARCHITECT = (
    "Launch ONE fresh agent with the Agent tool, `subagent_type` `sparkwright:sparkwright-architect`, "
    "and ONLY this task text: \"Read <absolute path of data.prompt> and follow it. Reply with only the Markdown it asks for.\" "
    "Pass no conversation history or opinion. Write the agent's reply verbatim to `data.result_file`."
)

RUN_SYNTHESIZER = (
    "Launch ONE fresh agent with the Agent tool, `subagent_type` `sparkwright:sparkwright-theme-synthesizer`, "
    "and ONLY this task text: \"Read <absolute path of data.prompt> and follow it. Reply with only the JSON object.\" "
    "You conducted the interview, so you must not write the themes yourself. Write the agent's reply verbatim to `data.result_file`."
)
BUILD_PERSONAS = ["test-author", "property-tester", "builder"]  # need to edit files and run tests in the task workspace

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
        "- Read only the file named in your task.\n"
        "- You have no conversation history and must not ask for it.\n"
        "- Do not edit any file. Return only the JSON your instructions describe.\n"
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
        body = skill.render(run_agents=RUN_AGENTS, run_build_agent=RUN_BUILD_AGENT, run_synthesizer=RUN_SYNTHESIZER, run_architect=RUN_ARCHITECT, run_guide_agent=RUN_GUIDE_AGENT, run_surveyor=RUN_SURVEYOR)
        put(f"skills/{skill.name}/SKILL.md",
            f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n{body.strip()}\n")
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
                                             "command": "sparkwright guard"}]}]},
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
