---
name: sparkwright-adopt
description: Bring an existing codebase under SparkWright — a fresh Surveyor agent drafts System, Component and Task specs bottom-up from the code, all as drafts, and the current commit becomes the baseline. Use when the user wants to start using SparkWright on a project that already has code but no specs.
cli: sparkwright adopt
personas: [surveyor]
---

# Adopt an existing codebase

1. If `.sparkwright/config.yaml` does not exist, run `sparkwright init --json`.
2. Run `sparkwright adopt --prepare --json` (add `--path <dir>` to survey only
   part of a large repository).
3. {{run_surveyor}}
4. Run the command in `data.then` with `--json`. Show the user the drafted
   files and any warnings.
5. Tell the user the drafts describe what the code does today, not what it
   should do: they should correct them, run an owner interview to replace the
   assumed Vision, and then review SYSTEM. Never approve anything yourself.
