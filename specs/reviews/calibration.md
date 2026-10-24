---
id: calibration
title: Reviewer calibration
type: review
status: in-review
---

Suite: 15 cases (built-in planted flaws and clean controls, plus any in `.sparkwright/calibration/`).
Catch: a high or medium finding that names the flaw and points at the flawed requirement. False alarm: a high finding on a clean control. Noise: medium findings per clean control (often fair critique, but cost reader time). Missing or unparseable replies are not scored.

| Persona | Tier | Flawed cases | Caught | Catch rate | Clean cases | False alarms | False-alarm rate | Noise | Missed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buildability-checker | host | 3 | 3 | 1.00 | 3 | 2 | 0.67 | 2.0 | — |
| contradiction-hunter | host | 2 | 2 | 1.00 | 3 | 0 | 0.00 | 2.3 | — |
| coverage-auditor | host | 2 | 2 | 1.00 | 3 | 2 | 0.67 | 2.0 | — |
| devils-advocate | host | 2 | 2 | 1.00 | 3 | 3 | 1.00 | 1.3 | — |
| newcomer | host | 2 | 2 | 1.00 | 3 | 3 | 1.00 | 4.0 | — |
| security-reviewer | host | 2 | 2 | 1.00 | 3 | 0 | 0.00 | 1.0 | — |

## Proposal

Minimum catch rate: 0.50 (`calibration.min_catch_rate`).

No change proposed.
