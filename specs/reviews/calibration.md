---
id: calibration
title: Reviewer calibration
type: review
status: in-review
---

Suite: 21 cases (built-in planted flaws and clean controls, plus any in `.sparkwright/calibration/`).
Catch: a high or medium finding that names the flaw and points at the flawed requirement. False alarm: a high finding on a clean control. Noise: medium findings per clean control (often fair critique, but cost reader time). Missing or unparseable replies are not scored.

| Persona | Tier | Flawed cases | Caught | Catch rate | Clean cases | False alarms | False-alarm rate | Noise | Missed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| buildability-checker | host | 4 | 4 | 1.00 | 3 | 0 | 0.00 | 0.7 | — |
| contradiction-hunter | host | 3 | 3 | 1.00 | 3 | 0 | 0.00 | 0.7 | — |
| coverage-auditor | host | 3 | 3 | 1.00 | 3 | 0 | 0.00 | 0.0 | — |
| devils-advocate | host | 3 | 3 | 1.00 | 3 | 1 | 0.33 | 2.0 | — |
| newcomer | host | 3 | 3 | 1.00 | 3 | 0 | 0.00 | 2.0 | — |
| security-reviewer | host | 3 | 3 | 1.00 | 3 | 0 | 0.00 | 0.0 | — |

## Proposal

Minimum catch rate: 0.50 (`calibration.min_catch_rate`).

No change proposed.
