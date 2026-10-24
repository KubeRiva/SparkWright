# Reviewer calibration, run 1 (2026-10-24)

First run of `sparkwright calibrate` on the built-in suite (15 cases: 12 planted
flaws, 3 clean controls), in host mode.

## Method

- Host: Claude Code subagents, model Claude Sonnet, one fresh agent per job
  (31 jobs: each Inspector on the cases it should catch plus every clean
  control). Each agent got only its persona prompt and the case context, with
  no conversation history and no hint of the planted flaw.
- Scoring: `sparkwright calibrate --collect` (catch = a high or medium finding
  that names the flaw and points at the flawed requirement; false alarm = a
  high finding on a clean control; noise = medium findings per control).
- Replies are archived in `2026-10-24-run1-replies.json`. Findings that do not
  affect scoring (low severity, long fixes) were condensed when archived;
  severities, IDs and the wording that names each flaw were kept.

## Results

| Persona | Catch rate | False-alarm rate | Noise (medium per control) |
| --- | --- | --- | --- |
| contradiction-hunter | 1.00 (2/2) | 0.00 | 2.3 |
| security-reviewer | 1.00 (2/2) | 0.00 | 1.0 |
| buildability-checker | 1.00 (3/3) | 0.67 | 2.0 |
| coverage-auditor | 1.00 (2/2) | 0.67 | 2.0 |
| devils-advocate | 1.00 (2/2) | 1.00 | 1.3 |
| newcomer | 1.00 (2/2) | 1.00 | 4.0 |

## What this run tells us

1. **The planted flaws are too easy.** Every persona caught every flaw it was
   meant to catch, including the hidden prompt-injection comment. A useful
   benchmark needs subtler flaws (contradictions spread across levels,
   coverage gaps hidden behind similar wording, risks that need domain
   knowledge) and more cases per persona; with 2-3 cases each, the rates
   above have very wide uncertainty.
2. **The clean controls were not clean.** Most "false alarms" are real gaps
   in the controls: a waitlist and credits mentioned but never defined, no
   rule for two members booking the last spot, a 5-minute bound not carried
   down to the component. The controls must be rewritten to be genuinely
   complete before false-alarm rates mean much.
3. **Persona character shows anyway.** The Contradiction Hunter and Security
   Reviewer stayed inside their brief (no high findings on controls). The
   Newcomer and Devil's Advocate escalate ordinary gaps to high severity;
   their prompts should reserve "high" for issues that block building or are
   expensive to reverse.
4. **Scoring fix found by this run.** Case `bld-02` cited the wrong
   requirement ID in its answer key (`C1.1.1` instead of `C2.1.1`); fixed.
   Counting medium findings on controls as false alarms (review R006, F9)
   made every persona score 1.00, which hides the difference above; false
   alarms are now high findings only, with medium findings reported
   separately as noise.

## Next run

- Rewrite the clean controls so each is complete with respect to its parent.
- Add at least 5 flawed cases per persona, including subtle ones.
- Run per tier in Runner mode (`--tier fast --tier mid --tier top`) and with
  other hosts (Codex, Gemini CLI) to compare.
