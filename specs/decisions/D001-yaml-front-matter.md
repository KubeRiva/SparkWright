---
id: D001
title: Use PyYAML (safe_load) for front matter and config
type: decision
status: approved
---

## Question

The constitution says "standard library first". Front matter and config need a
parser. Options: hand-rolled YAML subset, TOML via `tomllib`, or PyYAML.

## Options considered

| Option | For | Against |
| --- | --- | --- |
| Hand-rolled YAML subset | No dependency | Correctness risk (anchors, multiline, type coercion); maintenance burden |
| TOML via `tomllib` | Standard library, strict, no coercion surprises | Needs Python 3.11+; many target machines (including the founder's dev VM) run 3.10; TOML front matter is unfamiliar in Markdown tooling |
| PyYAML `safe_load` | Ubiquitous, familiar `---` front matter, works on 3.10 | One third-party dependency |

## Decision

Use PyYAML with `safe_load` only. Reject documents that use anchors/aliases or
non-string keys. Generated files (ledger, run logs, approvals) use JSON / JSON
lines so they need no YAML at all.

## Consequences

- Single runtime dependency, pinned `PyYAML>=6.0`.
- Revisit when 3.10 reaches end of life (Oct 2026+): `tomllib` becomes an option.
