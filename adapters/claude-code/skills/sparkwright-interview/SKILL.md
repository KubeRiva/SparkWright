---
name: sparkwright-interview
description: Gather evidence for a SparkWright Vision by interviewing the project owner one question at a time in chat, or by turning a user-interview transcript into anonymized evidence. Use when the user wants to start a new product spec or add user evidence.
---

# Gather evidence

## Owner interview (no API key needed)

1. Ask the owner, in one message, whether they consent to the interview being
   saved as anonymized evidence in `specs/evidence/`. Stop if they decline.
2. Run `sparkwright interview owner --host --consent "<how they consented>" --json`.
3. Read the file in `data.prompt` and interview the owner in chat exactly as it
   says: one question per message, past behaviour over hypotheticals, never
   suggest answers. Usually 6–10 questions.
4. Write the transcript to `data.transcript`, then run the command in
   `data.then` with `--json`.
5. Launch ONE fresh agent with the Agent tool, `subagent_type` `sparkwright:sparkwright-theme-synthesizer`, and ONLY this task text: "Read <absolute path of data.prompt> and follow it. Reply with only the JSON object." You conducted the interview, so you must not write the themes yourself. Write the agent's reply verbatim to `data.result_file`.
6. Run `sparkwright interview collect <run_id> --json` and tell the owner which
   evidence file was written.

## Transcript of a user interview

1. Ask how consent was obtained, then run
   `sparkwright interview ingest <file> --consent "<how>" --redact "<names>" --prepare --json`.
2. Continue from step 5 above.

Never mark real interviews `--simulated`, and never use simulated evidence to
back a Vision requirement. After evidence exists, help the owner cite it in
`specs/vision.md` with the line grammar `- **V<n>** [E<n>] <requirement>`.
