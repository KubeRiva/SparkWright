# ChessTutor lab: finish the hint-ladder slice on Windows

Where things stand (2026-10-25): every C1 spec change you decided is approved
and recorded. Merged so far: C1.1.1.T1, C1.1.2.T1, C1.1.3.T1, C1.2.1.T1,
C1.2.2.T1, C1.3.1.T1, C1.4.1.T1. Eleven builds remain; all touch the same file,
so build them one at a time, merging each before starting the next.

## Once

```powershell
cd D:\SparkWright
uv tool install --editable D:\SparkWright --force
claude plugin marketplace update sparkwright
claude plugin update sparkwright@sparkwright   # if nothing changes: uninstall, then install again
cd D:\SparkWright\lab\chesstutor
# The lab's build environment was created on Linux; let uv rebuild it for Windows:
Remove-Item -Recurse -Force .venv-sparkwright
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.venv-sparkwright"
uv sync --all-groups
sparkwright check        # should say PASS
claude
```

## Then, for each task in this order

In Claude Code: "Build task <ID> with the sparkwright-build skill." When it
reports **ready**, look at the diff and merge:

```powershell
git diff sparkwright/dogfood...sparkwright/<branch shown>
git merge --no-ff <branch shown>
sparkwright check
```

| # | Task | What it is | Expect |
| --- | --- | --- | --- |
| 1 | C1.1.1.T1 | Re-check: staircase has 2 or 4 steps | Likely "already implemented"; no code change |
| 2 | C1.1.2.T1 | Re-check: hint moves up one step | Likely "already implemented" |
| 3 | C1.1.3.T1 | Re-check: one staircase per puzzle | Small change if needed |
| 4 | C1.1.3.T2 | Same puzzle, different depth is an error | New code |
| 5 | C1.1.3.T3 | `start_exercise` resets only that puzzle | New code |
| 6 | C1.2.1.T1 | Leak guard fails closed (`leak_check_failed`) | Code change |
| 7 | C1.2.2.T1 | Re-check: last step allows the answer | Likely "already implemented" |
| 8 | C1.3.2.T1 | Skip jumps to the last step; no staircase is an error | New code |
| 9 | C1.3.3.T1 | Opening or moving to a puzzle builds a fresh staircase | New code |
| 10 | C1.3.4.T1 | The hint action moves up one step | New code |
| 11 | C1.3.5.T1 | Other actions do nothing | New code |

Rebuilt tasks start a new branch, for example `sparkwright/C1.1.1.T1-2`.

## Open points logged for later (not blocking)

- What the tutor shows when a draft is blocked (retry, fallback message): a
  task for the tutor loop, outside C1.
- Answers described in words ("take the pawn with the knight"): a later
  semantic leak check (Vision V1 now says so).
- Details are in `specs/reviews/2026-10-25-*.md`.
