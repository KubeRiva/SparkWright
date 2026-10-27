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
3. For EACH name in `personas`, delegate to subagents in parallel, one per item, each: `@sparkwright-<persona>`. Give each agent ONLY this task text: "Review the artifact in <absolute path of context>. Return only the JSON array." Do not pass any conversation history, summaries or your own opinion. When each agent returns, write its reply verbatim to `<outputs_dir>/<persona>.json`. Wait for all agents before continuing.
4. Run `sparkwright review <ID> --collect <run_id>`.
5. Tell the user the gate result and the path of the review file, and list
   the high-severity findings in one line each. Do not fix findings unless the
   user asks; do not approve anything.
6. When the user asks you to act on findings, keep each level to its job
   (D010): a Vision states outcomes and boundaries, a System what the product
   does, a Component how a part works, a Task one buildable change. A finding
   about a lower level's job (mechanisms such as PINs, credentials, storage,
   platforms, lockout rules) is NOT fixed by adding detail here: suggest the
   Decision `deferred to <level>` and leave the text alone. Reviews never reach
   zero findings; suggest approving once no high finding about this level's
   own job remains, and say how many rounds have run. After three rounds on
   the same file, say plainly that further rounds are likely to add detail
   rather than quality.
