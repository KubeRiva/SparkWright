---
name: sparkwright-review
description: Review a SparkWright spec (vision, system, component or task) with fresh-context Inspector agents, merge their findings and apply the gate. Use when the user asks to review a spec or a requirement ID.
cli: sparkwright review
personas: [coverage-auditor, contradiction-hunter, newcomer, devils-advocate, buildability-checker, security-reviewer]
---

# Review a spec with fresh-context Inspectors

You are the orchestrator. You must NOT review the spec yourself: a review in
your own context is not an Inspector review, because you may have seen the
conversation that produced it.

1. Run `sparkwright check`. If it fails with grammar errors in the target file,
   report them and stop.
2. Run `sparkwright review <ID> --prepare --json`. Note `run_id`, `context`,
   `outputs_dir` and `personas` from the output.
3. {{run_agents}}
4. Run `sparkwright review <ID> --collect <run_id>`.
5. Tell the user the gate result and the path of the review file, and list
   the high-severity findings in one line each. Do not fix findings unless the
   user asks; do not approve anything.
