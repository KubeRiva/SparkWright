# Contributing to SparkWright

SparkWright is built with SparkWright. Changes follow the same rules the tool
enforces on its users.

## How a change lands

1. **Spec first.** Behaviour changes start as a change to `specs/` (a new or
   modified requirement line). Approved requirements change only through a
   change request in `specs/changes/`.
2. **Review.** Run `sparkwright review <ID>` (or the Claude Code skill). Resolve
   high-severity findings or record why you rejected them in the review file's
   Decision column.
3. **Code and tests.** Annotate tests with the requirement they verify:
   `# sparkwright: S2.4`. Run `sparkwright mutate --base main` on your change.
4. **Check.** `sparkwright check` and `cd tests && python -m unittest` must pass.
5. **Approval.** A maintainer runs `sparkwright approve` — never an agent.

## Developer Certificate of Origin

All commits must be signed off (`git commit -s`), certifying the
[Developer Certificate of Origin](https://developercertificate.org/): you wrote
the change or have the right to submit it under the Apache 2.0 licence.

## AI-assisted contributions

Welcome, with two rules: a human reviews and signs off every commit, and agents
never edit `specs/approvals.jsonl`, locked tests, or human-gated files
(`specs/constitution.md`, `.sparkwright/config.yaml`, `AGENTS.md`).
