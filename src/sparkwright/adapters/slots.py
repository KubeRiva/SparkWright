"""Host-specific wording for the neutral skill slots (SYSTEM S8.3).

Each host says how to start a fresh-context agent for a persona; everything else in the
instructions is shared, so every host gets the same isolation rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Host:
    launch: str                    # how to start one fresh agent, e.g. "launch ONE fresh agent with the Agent tool,"
    agent: Callable[[str], str]    # persona expression -> how to name that agent for this host
    parallel: str                  # how to run several at once


def slots(h: Host) -> dict[str, str]:
    one = lambda who, task, after="": (  # noqa: E731
        f"{h.launch[0].upper() + h.launch[1:]} {h.agent(who)}, and ONLY this task text: \"{task}\" "
        f"Pass no conversation history, summaries or opinion. {after}Write the agent's reply verbatim to `data.result_file`.")
    return {
        "run_agents": (
            f"For EACH name in `personas`, {h.parallel}: {h.agent('<persona>')}. Give each agent ONLY this task text: "
            "\"Review the artifact in <absolute path of context>. Return only the JSON array.\" Do not pass any "
            "conversation history, summaries or your own opinion. When each agent returns, write its reply verbatim "
            "to `<outputs_dir>/<persona>.json`. Wait for all agents before continuing."),
        "run_build_agent": (
            f"{h.launch} {h.agent('<data.persona>')}, and ONLY this task text: \"Read <absolute path of data.prompt> and "
            "follow it. Work only inside <data.workspace>. When finished, reply with only the JSON the instructions ask "
            "for.\" Pass no conversation history or opinion. Write the agent's final reply verbatim to `data.result_file`."),
        "run_synthesizer": one("theme-synthesizer", "Read <absolute path of data.prompt> and follow it. Reply with only "
                               "the JSON object.", "You conducted the interview, so you must not write the themes yourself. "),
        "run_architect": one("architect", "Read <absolute path of data.prompt> and follow it. Reply with only the Markdown "
                             "it asks for."),
        "run_guide_agent": one("<data.step>", "Read <absolute path of data.prompt> and follow it. Reply with only what it "
                               "asks for."),
        "run_surveyor": one("surveyor", "Read <absolute path of data.prompt> and follow it. Reply with only the JSON object."),
        "run_calibration_jobs": (
            f"For EACH job in `data.jobs` (up to 6 at a time), {h.parallel}: {h.agent('<job.persona>')}, with ONLY this "
            "task text: \"Review the artifact in <absolute path of job.context>. Return only the JSON array.\" Never tell "
            "an agent what flaw to look for. Write each reply verbatim to `job.result_file`. Wait for all jobs."),
    }


CLAUDE = Host("launch ONE fresh agent with the Agent tool,",
              lambda p: f"`subagent_type` `sparkwright:sparkwright-{p}`",
              "launch the Agent tool in parallel with `subagent_type` set to")
CODEX = Host("spawn ONE fresh Codex subagent:",
             lambda p: f"the custom agent `sparkwright_{p}` (dashes in the persona name become underscores)",
             "spawn Codex subagents in parallel, one per item, each the custom agent named")
GEMINI = Host("delegate to ONE fresh subagent:",
              lambda p: f"`@sparkwright-{p}`",
              "delegate to subagents in parallel, one per item, each")
