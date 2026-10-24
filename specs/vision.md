---
id: VISION
title: SparkWright — from a spark of an idea to verified, traceable code
type: vision
status: in-review
risk: high
---

## Problem

AI coding agents build fast but drift fast. The plan lives in one chat, the code
in another, reviews are copied between tools by hand, and nothing proves the
finished code still matches what users needed. Existing spec-driven tools
review a single flat spec, let the builder write its own tests, and find drift
only after the fact.

## Users

- **Solo builders** running several AI-assisted projects with limited time,
  who want the plan → build → review → fix loop to run without manual hand-offs.
- **Engineering teams** that need to show why each piece of code exists and
  that it was checked independently.
- **Open-source maintainers** who want contributions to arrive with specs,
  tests and traceability.

## What done means

A user can take an idea through interviews and a pyramid of specs into merged
code, on any coding agent and any model, and at any time answer: *why does this
code exist, who asked for it, and how do we know it works?*

## Requirements

- **V1** [E01] **End-to-end traceability.** Every commit shall trace to a task, every task through the spec levels to the Vision, and every Vision requirement to evidence or an explicit assumption.
- **V2** [E01] **Multi-level specs with independent review.** The system shall support Vision, System, Component and Task levels, and each level shall be reviewed by fresh-context agents for quality and for coverage of its parent.
- **V3** [E01] **Verified build loop.** When a task is built, tests shall be written from its acceptance criteria by an agent other than the builder before code exists, the tests shall themselves be checked by mutation testing, and executable checks (tests, property tests, library checks and, where requested, proofs) shall outrank agent opinions.
- **V4** [E01] **Upward change, no silent drift.** When the build shows a spec is wrong, the system shall raise a change request to the level that owns the decision, re-review that level, and reissue affected tasks.
- **V5** [E01] **Human gates scaled by risk.** Humans shall approve Evidence, Vision, System, high-risk work, agent configuration and merges; lower-risk levels shall advance automatically when checks pass.
- **V6** [E01] **Evidence from interviews.** The system shall interview the owner by default and optionally real users, store anonymized evidence with consent, and flag requirements that lack evidence.
- **V7** [E01] **Platform agnostic.** All features shall work from a standalone CLI with any model provider and any CI system; host coding agents connect through adapters only.
- **V8** [E01] **Tamper-proof specs.** Approved specs and tests shall be locked so that only an approved change request can alter them, only verified humans can approve, no agent may edit the artifacts that judge its own work, and every change an agent makes shall be visible in review.
- **V9** [E01, A2] **Measured, affordable verification.** The system shall route roles to model tiers, enforce cost ceilings, and publish each reviewer persona's catch rate and false-alarm rate.
- **V10** [E01, A1] **Adoptable in real projects.** The system shall adopt existing codebases bottom-up, express changes as deltas, offer a lite mode for small work, and let teams use the traceability checks in CI without any agents.
- **V11** [E01, A3] **Safe to run with autonomous agents and automation.** The system shall treat spec and evidence text as data rather than instructions, keep secrets out of files and logs, store all state as plain text, and give every command machine-readable output.

## Assumptions (not yet backed by user evidence)

- **A1** [] Teams beyond the founder will accept a spec pyramid if lite mode and CI-only use lower the entry cost. Validate with 5+ external interviews.
- **A2** [] Published reviewer calibration scores will be a reason to choose SparkWright over other spec tools. Validate during benchmark launch.
- **A3** [] Users will only let agents run SparkWright workflows unattended if it resists prompt injection and never leaks secrets. Validate with early adopters' security questions.

## Non-goals

- A new agent runtime or model.
- A project-management tool (no sprints, people or estimates).
- Fully autonomous delivery without human ownership of decisions and merges.
