---
id: D002
title: Human approvals are verified against an approver allowlist in git history
type: decision
status: in-review
---

## Question

`sparkwright approve --as <name>` accepts any name, and `specs/approvals.jsonl`
is a plain file. How does `check` know a human approved something? (R002 F-high,
raised by Devil's Advocate and Newcomer.)

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Trust the `--as` name | Simple | Any agent with a shell can forge approvals; V8 is hollow |
| Signed commits only | Strong identity | Many solo users never set up signing; blocks adoption |
| Allowlisted commit authors, signatures optional | Works for everyone; CI verifiable; can be tightened | Author email can be set locally, so it relies on branch protection for full strength |

## Decision

1. `approvers:` in `.sparkwright/config.yaml` (human-gated) lists approver
   names and git author emails.
2. `check` verifies every committed line of `specs/approvals.jsonl` after the
   baseline was added by a commit whose author email is on the allowlist and
   whose `approver` field matches that person. Optional
   `require_signed: true` also requires `git verify-commit` to pass.
3. `approvals.jsonl` is append-only: the file at the baseline commit must be a
   prefix of the current file.
4. Uncommitted approval lines are reported as `approval.pending` (warning); CI
   runs on a clean checkout, so everything it sees is verified.

## Owner confirmation

Confirmed by the owner in interview E02 (Q1). Awaiting `sparkwright approve` by the owner.

## Consequences

Full strength needs protected branches (documented). Solo users get a useful
check with zero setup beyond listing their own email.
