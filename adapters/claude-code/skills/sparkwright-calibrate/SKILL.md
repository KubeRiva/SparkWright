---
name: sparkwright-calibrate
description: Measure how well each SparkWright Inspector persona catches planted spec flaws and how often it raises false alarms, and write the calibration report. Use when the user asks to calibrate, benchmark or check the quality of the reviewers.
---

# Calibrate the Inspectors

1. Run `sparkwright calibrate --prepare --json`. It returns `data.jobs`, one per
   persona and test case.
2. For EACH job in `data.jobs` (up to 6 at a time), launch the Agent tool in parallel with `subagent_type` set to: `subagent_type` `sparkwright:sparkwright-<job.persona>`, with ONLY this task text: "Review the artifact in <absolute path of job.context>. Return only the JSON array." Never tell an agent what flaw to look for. Write each reply verbatim to `job.result_file`. Wait for all jobs.
3. Run the command in `data.then` with `--json`.
4. Show the user the report path, each persona's catch and false-alarm rate,
   and any personas proposed for disabling. Disabling is a config change only
   the user makes; never edit `.sparkwright/config.yaml` yourself.
