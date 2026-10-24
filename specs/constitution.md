---
id: CONSTITUTION
title: SparkWright constitution — rules every spec level and every change must follow
type: constitution
status: draft
---

Inspectors check every spec, task and pull request against these rules. Changing
this file always requires a human gate.

## Product principles

1. **Traceable or it does not ship.** Every commit names a task; every task
   names its parents; every Vision requirement names evidence or is marked as
   an assumption.
2. **Checks that run beat opinions.** If a claim can be tested, measured or
   proved, that result outranks any agent's review.
3. **The author never grades its own work.** Reviews, tests and code are
   produced by different agents with different context.
4. **Humans own the big decisions.** Vision, System, risk-tier overrides,
   agent configuration and merges to the main branch need a person.
5. **Nothing changes silently.** Approved specs and tests change only through a
   change request.
6. **Portable by default.** No feature may require one specific coding agent,
   model provider or CI system. Host-specific code lives only in adapters.

## Engineering rules

- Core and Runner: Python 3.10+, standard library first (see D001 for the one exception). Third-party
  dependencies need a decision record (`specs/decisions/`).
- The core (spec parsing, ledger, coverage, locks) must run with no network
  and no model access.
- All persisted state is plain text in the repository (Markdown, YAML, JSON
  lines). No hidden database.
- Every CLI command supports `--json` output for automation.
- Every agent prompt and persona is a versioned file in the repo, never an
  inline string in code.
- Secrets (API keys) are read from the environment only and never written to
  any file, log or report.

## Writing rules for specs

- Requirements use EARS form where they describe behaviour:
  "When <trigger>, the system shall <response>."
- One requirement per bullet, each with a stable ID.
- No promotional adjectives (seamless, robust, blazing). State the mechanism.
- A requirement that cannot be tested is flagged by the Buildability Checker.
