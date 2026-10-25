---
id: CR1
title: Change S6.2
type: change
status: applied
target: S6.2
raised_by: human
rounds: 0
---

## Reason

D006: high-risk builds with source diffs under security_review.min_changed_lines (default 20) skip the build-time Security Reviewer; spec reviews unchanged.

## ADDED

## MODIFIED

- **S6.2** [V5] When an artifact has `risk: high`, its spec review shall add the Security Reviewer and require a human, overriding `gates` config; its build shall add a Security Reviewer step when the source diff (excluding tests and specs) has at least `security_review.min_changed_lines` changed lines (default 20). Changing an artifact's `risk` shall require a human gate.

## REMOVED
