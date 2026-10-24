---
id: R006
title: Independent review of Phase 5 (S3.10, S3.8, S7.2, S7.7, S2.7, S10, S5.6)
type: review
status: in-review
---

Fresh-context reviewer, no access to the authoring conversation. 11 findings.
Regression tests: `tests/test_phase5.py::TestPhase5ReviewFixes`.

| ID | Severity | Requirements | Finding | Fix | Decision |
| --- | --- | --- | --- | --- | --- |
| F1 | high | S3.10 | `approve --cr` with a different CR skipped the review requirement | The CR must target the requirement or an ancestor and must have been applied; review is required whenever the requirement has a `cr-applied` event, whatever its reason | fixed |
| F2 | high | S3.10 | Descendant tasks could be re-approved (and rebuilt) while the CR target was still in review | Descendants are refused until the target is re-approved after its last `cr-applied` event | fixed |
| F3 | high | S3.10 | Collecting an old or repeated review run recorded `reviewed` events for text nobody reviewed | `collect` refuses a second collect and refuses when the rebuilt context differs from the prepared `context.md` | fixed |
| F4 | high | S6.1 | One persona listed twice counted as two Inspectors; non-Inspector personas were accepted | Persona names are de-duplicated and must be Inspectors | fixed |
| F5 | medium | S3.8 | Run-log `base`/`branch` reached `git diff` unchecked (option injection, file overwrite) | Only a hex commit and a `sparkwright/<task>` branch are accepted; `--` and leading-dash guard | fixed |
| F6 | medium | S5.6 | Agent-chosen file names reached the prove command; empty file list passed trivially | Commands run without a shell (verified: `split_cmd` + argv), and names outside `[\w./ -]` or starting with `-` are refused; empty list fails | fixed |
| F7 | medium | S3.8 | Parallel branches conflict on `specs/approvals.jsonl` | `init` adds `merge=union` for the append-only logs to `.gitattributes` (added to this repo and the lab) | fixed |
| F8 | medium | S2.7 | Run-log `head` written into config.yaml unchecked | Must be a commit hash; replacement via a function | fixed |
| F9 | medium | S10.2 | ID-only findings counted as catches; medium findings on clean controls ignored; missing replies counted as misses | A catch must name the flaw (non-ID keyword) and point at it; medium or high on a control is a false alarm; missing replies are not scored | fixed |
| F10 | low | S10.3 | Per-tier proposals combined could leave a level with one Inspector | One proposal over the union of weak personas, checked against the 2-Inspector rule | fixed |
| F11 | low | S7.7 | Minors check always passed because the engine's own section mentions parents | Judged on the writer's draft before insertion | fixed |
