---
id: D009
title: Fixes for the R008 system review and a strict guard mode
type: decision
status: in-review
---

## Question

R008 left 8 high, 33 medium and 11 low findings. The owner asked to fix them
and to add a strict guard mode so Claude cannot skip SparkWright in a plain
chat (owner decisions, 2026-10-24).

## Decision

1. **Mutation testing never passes by default.** With no mutants the result is
   `not-run`: fine for test-only tasks, but a task that changed source the
   Saboteur cannot mutate is blocked unless an approver sets
   `mutation.allow_not_run`.
2. **Sandbox, step two.** Agent-written code runs with HOME pointed at an empty
   folder (`sandbox.isolate_home`, default on) and, on Linux, optionally without
   network (`sandbox.network: false`). It is still not a full sandbox; the
   spec says so.
3. **Strict guard mode** (`guard.strict`, S8.5): agents may change code only
   inside a task build; untraced commits need the user's OK.
4. **Trust boundary stated, not hidden.** Approvals stay email-based until
   signing is on (the owner's D007 choice); `status` shows "Approver identity:
   advisory" until then, `init` turns enforcement on when git signing is
   already configured, and a repository with no approvers fails `check` when
   protected files change.
5. **Tighter rules:** config values that switch a protection off are reported;
   more files are protected (CI, hooks, other agents' instruction files); a
   legacy approval is refreshed only if its links and criteria are unchanged
   since it was recorded; a test author may re-lock a task's own tests only
   during a change-request rebuild; a Security Reviewer can be forced by path;
   model-written text is cleaned of secrets and hidden characters; transcripts
   with unredacted full names need `--redact` or `--keep-names`.
6. **Precise spec.** Exact hash definitions with a worked example, glob rules,
   record formats, the merge rule, round counting, the change-request
   lifecycle and the config table; calibration reports moved out of
   `specs/reviews/`.

## Consequences

- Test suites that rely on files in the real home folder (for example git
  identity) need `sandbox.isolate_home: false` or their own setup.
- Non-Python projects must accept `mutation.allow_not_run` until more
  languages are supported.
