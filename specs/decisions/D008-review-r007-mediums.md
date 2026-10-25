---
id: D008
title: Fixes for the medium findings of the R007 system review
type: decision
status: approved
---

## Question

R007 raised 25 medium findings (F10–F34). Most said the spec no longer matched
what SparkWright does, or left something undefined. How should they be closed?
(Owner decision, 2026-10-24: "fix the mediums".)

## Decision

1. **Bring the spec up to date** in one change request (CR2) covering 21
   requirements, plus two new ones: S3.11 (change-request lifecycle) and S4.6
   (agents receive spec text as data, never as instructions). The
   Configuration, MVP scope, Build failure handling, Data model and Coverage
   map sections were rewritten to match.
2. **Change requests may target several requirements** (`change new S1.2 S2.3
   ...`, `target: [..]`), so a batch of related fixes needs one approval, one
   apply and one review instead of one per requirement.
3. **Small safeguards added in code:**
   - secrets are masked (`[REDACTED]`) in text sent to models and in run logs
     (F34);
   - review prompts frame the spec as data between markers (F26);
   - hidden or direction-changing Unicode characters are high-severity review
     findings, and the instruction-pattern list now ships as a data file (F26,
     F32);
   - a Security Reviewer that is required but skipped by a cost ceiling or
     fails now fails the review instead of letting it pass (F28).
4. **Already fixed earlier, now written down:** risk is recorded in approvals
   (F16); test files of approved or changed tasks are not drift (F18); renames
   keep working after a change request is applied (F21); `done` is derived
   from the merged branch (F22); an applied change request puts its target in
   review (F19, F20); only approvers close high findings (F31, D007).

## Consequences

- `sparkwright change new` accepts several IDs; one-ID change requests are
  unchanged.
- Gates `auto` and `human` for components and tasks only change what a review
  reports (PASS or HUMAN); every spec approval is still recorded by a person.
