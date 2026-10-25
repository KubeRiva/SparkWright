---
id: CR3
title: Change 3 requirements
type: change
status: approved
target: [S5.2, S6.4, S6.5]
raised_by: human
rounds: 0
---

## Reason

High findings from the review of CR2: red-check rule, human approval of every change request, runner test-lock exception, missing approvers (D008)

## ADDED

## MODIFIED

- **S5.2** [V3] Red check: before the Builder runs, every new test file shall compile, and the whole `checks.test` command run after the Test Author's commit shall exit non-zero. An import error of the code under test counts as red; a syntax error in a test file, or a broken test runner (no tests collected, the runner itself missing), does not.
- **S6.4** [V5] Every change request shall require a human approval (S6.3), whatever level or risk its targets have; an Inspector pass never approves one.
- **S6.5** [V8] Protected paths shall be enforced in layers: the Runner shall refuse to write outside a role's allowed paths (Builder: the task's `files`; Test Author: `test_globs`); `check` shall fail when a commit with a `SparkWright-Role` trailer other than `human` changes a path protected for that role or a path in `always_protected`, except that a commit with role `runner` may append test-lock lines (role `runner`, id `test:<path>`) to `specs/approvals.jsonl` and add files under `specs/reviews/`, but never edit or delete a review file. `check` shall also fail when a commit with no role or role `human` changes a path in `always_protected` or a locked test and its author email is not listed under `approvers`; while no approvers are configured such commits are reported as a warning and every human approval fails (S6.3). With signing enforced (S6.3) such a commit must be signed (error with `require_signed: true`, warning with `high-risk`). Host adapters install their own guard (S8).

## REMOVED
