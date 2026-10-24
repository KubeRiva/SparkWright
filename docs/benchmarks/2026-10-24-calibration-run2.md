# Reviewer calibration, run 2 (2026-10-24)

Same method as run 1 (Claude Code subagents, model Claude Sonnet, one fresh
agent per job, no hint of the flaw), on suite v2 with Inspector personas v2.
37 jobs. Raw replies: `2026-10-24-run2-replies.json` (unedited this time).

Changes since run 1:

- Clean controls rewritten to be complete with respect to their parents.
- Six subtler planted flaws added (21 cases; 3-4 flawed cases per persona).
- All six Inspector personas share explicit severity rules ("high" only for
  wrong or unsafe behaviour or costly-to-reverse problems; an empty review is
  a good result).

## Results

| Persona | Catch rate | False-alarm rate | Noise (medium per control) |
| --- | --- | --- | --- |
| buildability-checker | 1.00 (4/4) | 0.00 | 0.7 |
| contradiction-hunter | 1.00 (3/3) | 0.00 | 0.7 |
| coverage-auditor | 1.00 (3/3) | 0.00 | 0.0 |
| devils-advocate | 1.00 (3/3) | 0.33 | 2.0 |
| newcomer | 1.00 (3/3) | 0.00 | 2.0 |
| security-reviewer | 1.00 (3/3) | 0.00 | 0.0 |

Run 1 for comparison: false-alarm rates 0.00-1.00 (mean 0.56), noise up to 4.0.

## Reading

- The severity rules and cleaner controls cut false alarms from a mean of
  0.56 to 0.06 without losing any catches. Three personas returned `[]` on at
  least one control.
- The Devil's Advocate still rates one design choice on a correct spec as
  high (a stored balance counter instead of a ledger); that is the persona's
  job, and a human can accept it as a low-cost "noted".
- Every planted flaw was still caught, including the subtler v2 ones (a
  moved-class case missing from a component, UTC vs local time across levels,
  an undefined export format, a single-PC database, "a reasonable time", a
  recoverable password). The suite still needs harder cases to separate
  models and tiers; with 3-4 cases per persona the catch rates carry wide
  uncertainty.

## Next

- Add cross-file and long-context cases where the flaw needs two documents.
- Run per tier in Runner mode and on Codex and Gemini CLI.
