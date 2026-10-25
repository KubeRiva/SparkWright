---
id: D007
title: Trust hardening after the R007 system review
type: decision
status: in-review
---

## Question

The R007 system review found nine high-severity gaps in how SparkWright decides
whom to trust: agents or other people could edit protected files, approvals were
not tied to a person's key, AI-written code could read the user's secret keys,
and anyone could close a serious review finding. What should change? (Owner
decisions, 2026-10-24: "Only you may change them", "Warn now, sign for risky
work", "Hide keys always", "Only you dismiss serious findings".)

## Decision

1. **Protected files (S6.5).** A commit with no role or role `human` that
   changes an `always_protected` path or a locked test must be authored by an
   approver. Role-protected paths such as `src/**` stay protected only from
   the agent roles, because humans edit code normally.
2. **Signing (S6.3).** `require_signed: high-risk` is the default: approvals of
   `risk: high` items must be signed. It is enforced for commits after
   `signing_from`; until that is set, `check` warns and explains how to turn
   signing on, so existing repositories keep passing.
3. **Secrets (S6.10).** Every command that runs AI-written code gets the
   environment with secret-like variables removed. `sandbox.keep_env` lets a
   human keep named variables. Blocking network access is left for later.
4. **Review findings (S6.11).** Only an approver, in a human commit, may move a
   high finding's Decision off `open`. The Runner may add review files but never
   edit one.
5. **Stronger approval lock (S2.4).** Approvals also record `hash2`, which
   covers parent links, the task YAML and acceptance criteria. Old approvals
   still count; `approve` refreshes them without a change request.
6. **Append-only per commit (S6.9).** A commit that removes or rewrites a log
   line fails `check`, even if a later commit hides it.
7. **Call cap (S4.5).** Tiers without prices stop at
   `budgets.max_calls_per_run` (default 40) instead of costing "zero".

## Independent review of this change

A reviewer that had not seen the work found 5 high and 5 medium gaps. Fixed:
review closings are now judged by comparing whole findings tables (renamed IDs,
deleted rows or files, findings added already closed, edits inside merges);
the append-only rule compares lines as a multiset, covers merges, accepts a
missing final newline and union merges, and allows approver waivers
(`log_waivers`); the signing rule uses the item's current risk, not only the
risk written on the approval line, and can bind an approver to a
`signing_key`; a bad `signing_from` is a config error; role trailers are
case-insensitive; the secret filter no longer removes `GIT_AUTHOR_*` or
`TOKENIZERS_PARALLELISM` and now removes `DATABASE_URL`, webhooks, `*_PAT`
and the SSH/GPG agent sockets; a zero price counts as unpriced.

**Known limit (accepted).** Author emails are not proof of identity: an agent
running under the user's own git identity, without a role trailer, looks like
the user until commits are signed with a key bound to the approver
(`signing_key`). Until then, the host guards (S8) are what stop agents editing
protected files. Secrets in files under the home folder (for example
`~/.aws/credentials`) and network access are not blocked yet.

## Consequences

- Repositories that have a second contributor touching `AGENTS.md`,
  `.sparkwright/config.yaml` or other protected files must list them as
  approvers or route the change through an approver.
- Teams that want signing set it up once, then set `signing_from`.
- None of the affected requirements had been approved (only S6.2 had), so no
  change request was needed; S6.2 is untouched.
