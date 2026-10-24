---
id: D004
title: Keep readable hierarchical IDs; record re-parenting as renames
type: decision
status: in-review
---

## Question

`C2.3.1.T3` shows where a task sits but must be renamed when it moves, breaking
trailers, test annotations and approvals. Opaque IDs (`T-0137`) survive moves
but lose meaning. (R002 medium, Devil's Advocate.)

## Decision

Keep hierarchical IDs. A change request may declare `renames: {OLD: NEW}` in its
front matter. Once that change request is approved, the ledger treats `OLD` in
commit trailers, test annotations and approvals as `NEW`. Leading zeros are not
significant (`E01` and `E1` are the same ID).

## Owner confirmation

Confirmed by the owner in interview E02 (Q3). Awaiting `sparkwright approve` by the owner.

## Consequences

People keep readable IDs; re-parenting costs one change request instead of a
history rewrite. The rename map is plain text and reviewable.
