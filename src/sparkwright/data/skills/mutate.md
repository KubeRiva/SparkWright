---
name: sparkwright-mutate
description: Run SparkWright's Saboteur (diff-scoped mutation testing) to check whether the tests actually catch bugs in recently changed code. Use after code changes, before review or merge.
cli: sparkwright mutate
personas: []
---

# Test the tests

1. Run `sparkwright mutate --base <revision>` (for example `--base main`).
   The test command comes from `checks.test` in `.sparkwright/config.yaml`.
2. For each surviving mutant, the tests failed to notice a real behaviour
   change on that line. Strengthen the tests, not the code.
3. Do not edit tests that are locked (`sparkwright check` reports locked tests);
   ask the user to open a change request instead.
