---
id: R003
title: Independent code review of MVP 1 and MVP 2 implementation
type: review
target: src/sparkwright
status: approved
reviewers: [independent-code-reviewer]
date: 2026-10-24
---

A fresh-context reviewer read SYSTEM and the code, then reproduced suspected
bugs in a scratch copy. Each fix has a regression test in
`tests/test_regressions.py` (named `test_f<N>_...`).

| ID | Severity | Finding | Decision |
| --- | --- | --- | --- |
| F1 | high | Personas returning unparseable output counted toward the 2-Inspector minimum | fixed |
| F2 | high | Foreman merge crashed when findings with and without IDs were mixed | fixed |
| F3 | high | Unknown baseline / shallow clone / missing git silently skipped commit checks | fixed: `git.log-failed` error, `git.unavailable` warning |
| F4 | high | Non-ASCII paths (git C-quoting) bypassed role and drift checks | fixed: `core.quotePath=false` |
| F5 | high | A builder commit could rewrite config to disable its own guardrails | fixed: always-protected paths for every agent role; config can only add protected paths |
| F6 | high | Claude Code guard covered only edit tools; relative paths; case folding; `.claude/` settings | fixed: Bash matcher, path resolution, case folding, `.claude/**` gated |
| F7 | high | Run IDs could write outside `.sparkwright/runs` | fixed: run ID validation |
| F8 | medium | Reported line numbers were one too low | fixed |
| F9 | medium | Approved evidence could be rewritten undetected | fixed: evidence body hash re-checked |
| F10 | medium | `--cr` accepted any change request ID | fixed: must be an approved CR file; `check` validates approvals too |
| F11 | medium | `trailers: off` read as boolean and rejected | fixed |
| F12 | medium | Quoting an injection phrase downgraded it | fixed: only code spans count as mentions; any match adds the Security Reviewer |
| F13 | medium | Non-UTF-8 file crashed commands; BOM dropped front matter | fixed |
| F14 | medium | Missing tier config gave a traceback | fixed: clean JSON error |
| F15 | medium | `risk` not required for components and tasks | fixed |
| F16 | medium | Saboteur skipped new files, crashed on missing binary, broke Windows paths | fixed |
| F17 | medium | Locked-test hashes differed across CRLF/LF checkouts | fixed: CRLF normalised before hashing |
| F18 | medium | Spec claims not met: S4.4 blocked status, S4.5 ceiling semantics, S8.1 interface, S9.1 open findings, S11.6 JSON errors | S4.5, S8.1, S9.1, S11.6 fixed; S4.4 task blocking deferred to the Phase 3 build loop (no tasks are built yet) |
| F19 | low | Phone redaction removed dates and order numbers | fixed |
| F20 | low | Status update dropped CRLF line endings | fixed |
| F21 | low | One corrupt run-log line broke resume | fixed |
