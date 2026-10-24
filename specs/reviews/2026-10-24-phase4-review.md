---
id: R005
title: Independent review of Phase 4 (property tests, risk tiers, descend)
type: review
status: in-review
---

Fresh-context reviewer, no access to the authoring conversation. 12 findings.
Regression tests: `tests/test_phase4.py::TestPhase4ReviewFixes`.

| ID | Severity | Requirements | Finding | Fix | Decision |
| --- | --- | --- | --- | --- | --- |
| F1 | high | S3.1 | `descend collect` trusted the run log (owner path, component ID, risk, parent) — path escape, front-matter injection, unapproved parent | `collect` re-derives the plan from the specs; every write must resolve under `specs/`; front matter is YAML-dumped | fixed |
| F2 | high | S6.2 | A risk change on a `building`/`done` task was hidden by build events | Risk mismatch is checked before build events and yields `draft` | fixed |
| F3 | medium | S6.2 | Legacy approvals (no recorded risk) match any risk; case-sensitive compare | Compare case-insensitively. Legacy approvals keep matching: the tier at approval time is unknown and voiding every existing approval would block current projects. New approvals record the tier | partly fixed (accepted risk) |
| F4 | medium | S6.2 | Build read `risk` from the live spec, so editing it mid-build dropped the Security Reviewer | Tier frozen in build state at prepare; effective tier is frozen OR live | fixed |
| F5 | medium | S5.4 | Property check never ran the tests | Static checks: must assert, must not skip/xfail, must carry the task annotation. Running property tests alone needs per-file test commands (not in config yet); mutation testing and the Code Reviewer still cover them | partly fixed |
| F6 | medium | S5.4, S6.5 | Property Tester could add `conftest.py`/`__init__.py` or edit tracked files; Test Author could later rewrite property tests | Property Tester may only add new `test_*` files; Test Author may not touch files from the property-tests commit | fixed |
| F7 | medium | S6.2, S6.7 | Review `collect` took risk, personas and injection hits from the run log | Recomputed from the spec; a missing required Security Reviewer is a high finding | fixed |
| F8 | medium | S3.1 | Architect controlled component front matter and could add non-component requirements | Allowlist title/risk/lite; risk is the higher of parent and draft; only component requirements accepted | fixed |
| F9 | medium | S8 | Guard compared `.sparkwright/` case-sensitively on Windows/macOS | Case-folded matching on case-insensitive file systems. Binding result files to a run: not done; `collect` validates every reply | partly fixed |
| F10 | low | S3.1 | Task blocks split by a different parser than validation; duplicates overwrote | Block IDs must equal validated IDs; files opened exclusively; lite append verified by re-parse and hash comparison | fixed |
| F11 | low | S3.1 | Trailing backslash in a title broke task front matter | YAML-dumped front matter | fixed |
| F12 | low | S5.4 | Property check shared the Test Author's round counter | Separate `props` counter | fixed |
