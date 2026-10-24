---
id: R001
title: Inspector review of SYSTEM v0.1 — merged findings and decisions
type: review
target: SYSTEM
reviewers: [coverage-auditor+contradiction-hunter, newcomer+buildability-checker+devils-advocate]
date: 2026-10-24
status: approved
---

Two fresh-context reviewers read VISION, SYSTEM and CONSTITUTION with no access
to the authoring conversation. Both independently flagged F1. All findings below
are applied in SYSTEM v0.2 unless marked otherwise.

## High

| ID | Finding | Decision |
| --- | --- | --- |
| F1 | Saboteur (mutation testing) was ordered before any code existed; no round limit; equivalent mutants unhandled | Accepted. Order is now: tests → red check against stub → tests locked → Builder → checks → Saboteur on the diff only, threshold `mutation.min`, max 2 rounds |
| F2 | No grammar for requirement lines; per-requirement hash had nowhere to live | Accepted. Grammar `- **<ID>** [<refs>] <text>`; hash = SHA-256 of whitespace-normalised text |
| F3 | Approval forgeable: `status: approved` is an editable field; lock hashes not rebuildable from sources | Accepted. Append-only `specs/approvals.jsonl` is the source of truth for approvals and hashes |
| F4 | No CLI verb records human approval; no gate rule for change requests | Accepted. Added `sparkwright approve` and change-request gate rules |
| F5 | Vision never reviewed by fresh-context agents, contradicting V2 | Accepted. Vision gate = Inspector pass (evidence coverage) + human |
| F6 | Evidence links and assumptions had no System requirement or ID format | Accepted. `A<n>` IDs; Vision lines must cite `E` or `A` IDs; coverage gap otherwise |
| F7 | State machine missing `blocked`, `rejected`, `building → changed`; change-request statuses undefined | Accepted |
| F8 | "Enforced in git" impossible — git has no path permissions | Accepted. Layered enforcement: Runner refuses writes; `check` fails on role-trailer path violations; CODEOWNERS/branch protection documented |
| F9 | Flat `T<n>` IDs collide across parallel branches | Accepted. Tasks are scoped to their component: `C2.3.1.T3` |
| F10 | Drift mapping from files to tasks undefined | Accepted. Tasks declare `files:` globs |

## Medium and low (all accepted)

- Run logs no longer trigger the agent-config human gate (only `config.yaml` and persona overrides do).
- One retry policy per (task, role): fail → escalate one tier → one retry → `blocked`.
- Failed proofs block the merge gate, not spec approval. Prover, adoption and calibration are post-MVP.
- v1 interviews: CLI owner interview and transcript ingest only (keeps every feature CLI-capable).
- Constitution rules given System requirements: `--json` schemas, no hidden database, human gate on constitution and risk overrides, Buildability Checker in the role list.
- Data model: task `files`, `invariants`, `prove`; change-request `rounds`; Persona entity; per-role run telemetry.
- Role-to-tier mapping in config; per-run and per-level cost ceilings; default persona priority until calibrated; minimum 2 Inspectors.
- `adopt` records a baseline commit; trailer checks apply only after it.
- `changed` tasks re-enter `build` after their parent is re-approved.
- Lite mode is per Component; tasks then live in a `## Tasks` section of the component file.
- Change-request target = nearest ancestor the Builder cites, default the task's parent. The engine writes the CR file (Builder cannot write `specs/`).
- Only `component` and `task` gates are configurable; `check` rejects others.
- Library Checker v1 checks symbols against the installed pinned version; docs lookup deferred.
- PR description must list every changed file; `check` verifies it.
- Saturation = 3 consecutive interviews with no new theme IDs.
- Ledger is generated (gitignored), rebuilt by `check`; output sorted, no timestamps.
- Runtime dependencies capped at 5.

## Recommendations adopted from Devil's Advocate

- MVP narrowed to offline traceability plus `review` and owner interview; `descend`, `build` and `change` follow as compositions of steps.
- Mutation testing scoped to the task diff with a time budget; full runs nightly or at the Component gate.
- Hand-rolled YAML rejected; see D001 (PyYAML `safe_load`).
