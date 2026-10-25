---
name: sparkwright-calibrate
description: Measure how well each SparkWright Inspector persona catches planted spec flaws and how often it raises false alarms, and write the calibration report. Use when the user asks to calibrate, benchmark or check the quality of the reviewers.
cli: sparkwright calibrate
personas: [coverage-auditor, contradiction-hunter, newcomer, devils-advocate, buildability-checker, security-reviewer]
---

# Calibrate the Inspectors

1. Run `sparkwright calibrate --prepare --json`. It returns `data.jobs`, one per
   persona and test case. For a cheaper check (one job per persona covering all
   its cases, less independent), add `--batch`; each batch reply is one JSON
   object mapping case ids to findings arrays.
2. {{run_calibration_jobs}}
3. Run the command in `data.then` with `--json`.
4. Show the user the report path, each persona's catch and false-alarm rate,
   and any personas proposed for disabling. Disabling is a config change only
   the user makes; never edit `.sparkwright/config.yaml` yourself.
