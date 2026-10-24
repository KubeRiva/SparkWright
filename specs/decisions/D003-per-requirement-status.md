---
id: D003
title: Status is per requirement, derived from append-only events
type: decision
status: in-review
---

## Question

Status lived in file front matter, but workflows change the status of single
requirements and tasks, and lite mode puts many tasks in one file. (R002 F-high,
raised by Contradiction Hunter, Devil's Advocate and Newcomer.)

## Options considered

| Option | For | Against |
| --- | --- | --- |
| File-level status only | Simple | Cannot express one changed task among many |
| Status token on each requirement line | Visible in the file | Edits to the token change the file; agents could forge it |
| Derived from append-only events | Per ID, tamper-evident, no extra syntax | Status is not visible in the file itself (shown by `status` and `trace`) |

## Decision

Each requirement's status is derived, in order, from:
`specs/approvals.jsonl` (approved when the latest approval matches the current
hash), `specs/events.jsonl` (build and change-request transitions, append-only),
and otherwise the file's front matter status as a default (`draft` or
`in-review`). Front matter `approved`/`done` without matching records is an error,
as today. `trace` and `status` display the derived status.

## Owner confirmation

Confirmed by the owner in interview E02 (Q2). Awaiting `sparkwright approve` by the owner.

## Consequences

One change request can mark exactly the affected tasks `changed`. Events are
committed, so CI and other machines see the same status.
