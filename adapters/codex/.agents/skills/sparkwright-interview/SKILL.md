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
5. Spawn ONE fresh Codex subagent: the custom agent `sparkwright_theme-synthesizer` (dashes in the persona name become underscores), and ONLY this task text: "Read <absolute path of data.prompt> and follow it. Reply with only the JSON object." Pass no conversation history, summaries or opinion. You conducted the interview, so you must not write the themes yourself. Write the agent's reply verbatim to `data.result_file`.
6. Run `sparkwright interview collect <run_id> --json` and tell the owner which
   evidence file was written.

## Transcript of a user interview

1. Ask how consent was obtained, then run
   `sparkwright interview ingest <file> --consent "<how>" --redact "<names>" --prepare --json`.
2. Continue from step 5 above.

Never mark real interviews `--simulated`, and never use simulated evidence to
back a Vision requirement. After evidence exists, help the owner cite it in
`specs/vision.md` with the line grammar `- **V<n>** [E<n>] <requirement>`.

## Interview guide for real users

1. Run `sparkwright interview guide --about "<who the users are and what to learn>" --prepare --json`
   (add `--minors` when any target users are under 18).
2. Spawn ONE fresh Codex subagent: the custom agent `sparkwright_<data.step>` (dashes in the persona name become underscores), and ONLY this task text: "Read <absolute path of data.prompt> and follow it. Reply with only what it asks for." Pass no conversation history, summaries or opinion. Write the agent's reply verbatim to `data.result_file`.
3. Run the command in `data.then` with `--json`. While `data.step` is not `done`,
   repeat step 2 for the agent it names, then run `data.then` again.
4. Show the user the guide path and the gate. If it failed, the user (not you)
   rewrites the flagged questions; then run the review again with a fresh run.
