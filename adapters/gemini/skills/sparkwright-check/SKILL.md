---
name: sparkwright-check
description: Run SparkWright's offline traceability checks, trace a requirement up to evidence and down to code, or show project status. Use when the user asks whether specs and code are consistent, why some code exists, or what is left.
---

# Check, trace, status

- `sparkwright check` runs grammar, coverage, approval-lock, drift and
  protected-path checks with no model calls. Fix grammar and reference errors
  yourself when asked; never edit `specs/approvals.jsonl`.
- `sparkwright trace <ID>` explains why a requirement exists (up to evidence)
  and what implements and verifies it (down to tasks, tests and commits).
- `sparkwright status` summarises levels, gaps, drift and agent cost.

Approvals are human-only. If an approval is needed, tell the user to run
`sparkwright approve <ID> --as <their name>` themselves. Never run it for them.
