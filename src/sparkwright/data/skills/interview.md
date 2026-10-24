---
name: sparkwright-interview
description: Gather evidence for a SparkWright Vision by interviewing the project owner one question at a time, or by ingesting a user-interview transcript. Use when the user wants to start a new product spec or add user evidence.
cli: sparkwright interview
personas: [interviewer, theme-synthesizer]
---

# Gather evidence

Owner interview (recommended first step for any new product):

- Tell the user to run `sparkwright interview owner` in their own terminal.
  It asks for consent, then asks one question at a time and writes
  `specs/evidence/E<n>-owner-interview.md`. You cannot answer for the owner.

Transcript ingest:

- Ask the user how consent was obtained, then run
  `sparkwright interview ingest <file> --consent "<how>" --redact "<names>"`.
- Never mark real interviews `--simulated`, and never use simulated evidence
  to back a Vision requirement.

After evidence exists, help the user cite it in `specs/vision.md` using the
line grammar `- **V<n>** [E<n>] <requirement>`.
