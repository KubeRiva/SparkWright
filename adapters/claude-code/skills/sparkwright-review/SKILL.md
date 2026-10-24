---
name: sparkwright-review
description: Review a SparkWright spec (vision, system, component or task) with fresh-context Inspector agents, merge their findings and apply the gate. Use when the user asks to review a spec or a requirement ID.
---

# Review a spec with fresh-context Inspectors

You are the orchestrator. You must NOT review the spec yourself: a review in
your own context is not an Inspector review, because you may have seen the
conversation that produced it.

1. Run `sparkwright check`. If it fails with grammar errors in the target file,
   report them and stop.
2. Run `sparkwright review <ID> --prepare --json`. Note `run_id`, `context`,
   `outputs_dir` and `personas` from the output.
3. For EACH name in `personas`, launch the Agent tool in parallel with `subagent_type` set to: `subagent_type` `sparkwright:sparkwright-<persona>`. Give each agent ONLY this task text: "Review the artifact in <absolute path of context>. Return only the JSON array." Do not pass any conversation history, summaries or your own opinion. When each agent returns, write its reply verbatim to `<outputs_dir>/<persona>.json`. Wait for all agents before continuing.
4. Run `sparkwright review <ID> --collect <run_id>`.
5. Tell the user the gate result and the path of the review file, and list
   the high-severity findings in one line each. Do not fix findings unless the
   user asks; do not approve anything.
