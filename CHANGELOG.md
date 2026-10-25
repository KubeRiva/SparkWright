# Changelog

## 0.1.0 (unreleased)

First public release.

- Offline core: requirement grammar, coverage, approvals with hash locks,
  derived status, drift and role checks, `trace`, `status`, CI-friendly `check`.
- Evidence: owner interviews, transcript ingest with redaction and consent,
  theme synthesis and saturation, interview guides for real users with a
  leading-question review and parental consent for minors.
- Specs: Inspector reviews with fresh-context personas, risk tiers with a
  Security Reviewer and human gates, `descend` (Architect), `adopt`
  (Surveyor) for existing codebases, change requests with re-review.
- Build loop: tests first by a separate Test Author, Property Tester for
  invariants, Builder, project checks, Prover hook, Library Checker,
  mutation testing (Saboteur), test locks, Code and Security Review, a final
  gate re-derived from git, parallel builds.
- Reviewer calibration with a planted-flaw suite.
- Hosts: Claude Code plugin, Codex and Gemini CLI adapters, AGENTS.md; Runner
  mode for any OpenAI-compatible or Anthropic model.
- Trust hardening (D007): only approvers may change protected files or close
  high review findings; signed approvals for high-risk work
  (`require_signed`, `signing_from`); secret keys hidden from AI-written code
  (`sandbox.keep_env`); approval locks cover parent links and acceptance
  criteria; per-commit append-only logs; a call cap for unpriced models.
