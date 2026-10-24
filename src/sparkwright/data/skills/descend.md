---
name: sparkwright-descend
description: Draft the next level of a SparkWright spec under one approved requirement — a component under a System requirement, or tasks under a component requirement — by a fresh Architect agent, then send it to review. Use when the user asks to break down, decompose or plan the next level for a requirement ID.
cli: sparkwright descend
personas: [architect]
---

# Draft the next spec level

1. Run `sparkwright descend <ID> --prepare --json`. If it stops because the
   parent is not approved, tell the user; only approved requirements descend.
2. {{run_architect}}
3. Run the command in `data.then` with `--json`. If the draft is rejected, show
   the reasons, run step 1 again for a fresh run, and pass the reasons to the
   new Architect agent as extra task text. Stop after two rejections.
4. Tell the user which files and IDs were drafted, list any open questions,
   and suggest the review command in `data.next`. The draft stays `status:
   draft` until Inspectors review it and a human approves it.

Never write or edit the drafted spec yourself, and never approve it.
