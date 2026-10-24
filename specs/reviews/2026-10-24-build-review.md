---
id: R004
title: Independent review of the Phase 3 build loop
type: review
target: src/sparkwright/runner/build.py
status: approved
reviewers: [independent-code-reviewer]
date: 2026-10-24
---

A fresh-context reviewer attacked the build loop in a scratch copy and
reproduced seven findings. Each fix has a regression test in
`tests/test_build_security.py` (`test_h<N>_...`, `test_m<N>_...`, `test_l<N>_...`).

| ID | Severity | Finding | Decision |
| --- | --- | --- | --- |
| H1 | high | Agent-made `git commit` bypassed path enforcement | fixed: agent commits are unwound (`reset --soft`) before enforcement |
| H2 | high | Code Reviewer step was not enforced | fixed: reviewer changes are discarded (`reset --hard`, `clean`) |
| H3 | high | Runner-mode `files` could rewrite `.git`, escape via `..`, absolute paths or symlinks | fixed: paths validated and refused before writing |
| H4 | high | Test Author could edit other tasks' locked tests; runner re-locked them; `check` only covered the builder | fixed: tests locked at base are protected; only this task's tests are locked; `check` uses git commit order for every agent role; runner commits may only add test locks |
| H5 | high | Run log could be forged to `ready`; guard not workspace-aware; Bash glob bypass | fixed: final gate re-derives evidence from git and writes a `ready` marker commit; `ready` requires the marker; guard maps workspace paths and denies run state |
| M1 | medium | Zero mutants scored 1.0; test files mutated; partial flag ignored | fixed: zero mutants reported; test globs excluded; partial reported |
| M2 | medium | Deleted test crashed the red check; pre-existing failures passed red | fixed: deletions reverted; suite must pass at base before a build starts |
| M3 | medium | Blocked or changed builds could never be rebuilt | fixed: `--restart`, and automatic new run after re-approval |
| M4 | medium | `done` set by any builder commit | fixed: `done` requires the runner's `ready` marker commit |
| M5 | medium | Builds started from a dirty main tree | fixed: refuse when specs or config are uncommitted |
| M6 | medium | Change-request rounds never counted | fixed: rebuilds after an applied CR increment `rounds`; more than 2 blocks the CR |
| L1 | low | Ignored files escape enforcement | rejected: ignored files can never be committed to the branch; the final gate runs on committed content |
| L2 | low | Round counting | accepted as documented: "max 2 rounds" means two returns before blocking |
| L3 | low | Spec defects from the Test Author; malformed replies opened CRs | fixed: malformed replies are treated as no defect; the Test Author may report defects (persona allows it) |
| L4 | low | `--result` read any path | fixed: must be inside `.sparkwright/runs/` |
| L5 | low | Test lock hashed the working-tree file | fixed: hashes the committed blob |
