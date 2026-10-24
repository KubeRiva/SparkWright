---
id: D005
title: Test-only tasks guard existing behaviour; the final gate resumes after interruption
type: decision
status: in-review
---

## Question

ChessTutor task C1.4.1.T1 only adds a test for behaviour the code already has
(the policy package never imports the chess library). The red check rejects it:
tests that pass before any implementation "do not test the task". Separately,
the final gate re-ran the whole test suite, the checks and mutation testing in
one step, which took longer than a remote session could hold a command open.

## Decision

1. A task whose declared `files` all match `test_globs` is a test-only task.
   Its new tests must PASS when written (they guard existing behaviour), it has
   no Builder step, failed checks and high review findings go back to the Test
   Author, and its commit is `tests (guard)` instead of `tests (red)`. Code and
   Security Review still run; mutation testing has no changed source to mutate.
2. The final gate caches the red check, the project checks and the mutation
   result per branch tip in the build state, and reuses the Saboteur's result
   when only `specs/` changed since it ran. An interrupted gate resumes.

## Consequences

A test-only task cannot prove its tests would catch a regression the way a red
check does; reviewers must judge that. Found by the ChessTutor dogfood.
