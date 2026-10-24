---
name: sparkwright-build
description: Build one approved SparkWright task end to end — tests first by a separate agent, then code, project checks, library check, mutation testing, test locking and code review — on its own git branch. Use when the user asks to build or implement a task ID.
---

# Build a task

For several tasks, first run `sparkwright build <id> <id> ... --plan --json`.
Tasks in the same batch cannot touch the same files: you may drive their
build loops side by side (each in its own fresh agents). Start the next batch
only after the user has merged the previous one.

You are the orchestrator. You never write tests or code yourself: each agent
step runs in a fresh agent so no role grades its own work.

1. Run `sparkwright build <task-id> --next --json`. Agent steps are, in order: test-author,
   property-tester (only when the task declares invariants), builder, code-reviewer, and
   security-reviewer (only for `risk: high` tasks). Every merge of a high-risk task needs a human.
2. Look at `data.kind` in the output:
   - `agent`: spawn ONE fresh Codex subagent: the custom agent `sparkwright_<data.persona>` (dashes in the persona name become underscores), and ONLY this task text: "Read <absolute path of data.prompt> and follow it. Work only inside <data.workspace>. When finished, reply with only the JSON the instructions ask for." Pass no conversation history or opinion. Write the agent's final reply verbatim to `data.result_file`.
     Then run the command in `data.then` with `--json`, and go back to step 2.
   - `human` with `step` `ready`: tell the user the branch name and mutation
     score, and that they should review and merge it. Stop.
   - `human` with `step` `changed`: the spec is wrong. Show the user the change
     request path and target. Stop; do not edit specs yourself.
   - `human` with `step` `blocked`: show the reason. Stop.
3. Never run `sparkwright approve`, never edit `specs/approvals.jsonl`, and never
   edit files in the workspace yourself between steps; SparkWright reverts
   changes a role is not allowed to make.
