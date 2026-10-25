---
id: D006
title: Token economy for host-agent runs
type: decision
status: approved
---

## Question

In the ChessTutor dogfood every fresh host agent cost about 75k tokens before
doing any work, so one build cost 300-400k tokens and a calibration run 2-3M.
How can SparkWright cut that without weakening isolation? (Owner decision,
2026-10-24.)

## Decision

1. Generated Claude Code agents that judge or test (Inspectors, Code and
   Security Reviewer, Test Author, Property Tester, Theme Synthesizer,
   Question Auditor) use `model: sonnet`; the Builder, Architect, Surveyor and
   Guide Writer inherit the user's model.
2. `security_review.min_changed_lines` (default 20): a high-risk build whose
   source diff (excluding tests and specs) is smaller skips the Security
   Reviewer. High-risk spec reviews always include it. This narrows S6.2 and
   needs a change request to S6.2 before release (see CR below).
3. `sparkwright calibrate --prepare --batch` runs one agent per persona over
   all its cases. One agent per case remains the default for published
   benchmarks, because batching lets a reviewer see several cases at once.
4. A Test Author can report that earlier work already delivered a task
   (`already_implemented`); no Builder runs and the reviewers check the claim.

## Consequences

Small high-risk changes lose an independent security read; the Code Reviewer
still sees them, and spec-level security review is unchanged.
