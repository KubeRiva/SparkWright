# Quickstart: SparkWright with Claude Code (Windows)

This runs SparkWright on your Claude Code subscription: Claude Code's own
agents do the interviewing, reviewing, testing and building, and the
`sparkwright` CLI enforces the rules. No API key is needed.

Commands are for PowerShell. Paths assume SparkWright lives in `D:\SparkWright`.

## 1. Install the CLI (once)

```powershell
uv tool install --editable D:\SparkWright
uv tool update-shell          # puts sparkwright on PATH; open a new terminal afterwards
sparkwright --version
```

Without uv: `py -m pip install -e D:\SparkWright`.

The Claude Code plugin calls `sparkwright guard` before every file edit and
shell command, so the CLI must be on PATH for Claude Code too.

## 2. Install the Claude Code plugin (once)

```powershell
claude plugin marketplace add D:\SparkWright
claude plugin install sparkwright@sparkwright
```

This adds eight skills (`sparkwright-interview`, `sparkwright-review`,
`sparkwright-descend`, `sparkwright-build`, `sparkwright-adopt`,
`sparkwright-calibrate`, `sparkwright-check`, `sparkwright-mutate`), the
fresh-context agents they use, and the guard hook.

If you installed the plugin before, update it after pulling SparkWright
changes: `claude plugin marketplace update sparkwright` then
`claude plugin update sparkwright@sparkwright`, and restart Claude Code. If
an update is not picked up, uninstall and install it again.

## 3. Continue the ChessTutor hint-ladder slice (lab copy)

The lab copy is at `D:\SparkWright\lab\chesstutor` on branch `sparkwright/dogfood`.
Task `C1.1.1.T1` is already built and merged there.

```powershell
cd D:\SparkWright\lab\chesstutor
$env:UV_PROJECT_ENVIRONMENT = "$PWD\.venv-sparkwright"
uv sync --all-groups          # once: the shared build environment from .sparkwright/config.yaml
sparkwright check
sparkwright status
claude
```

In Claude Code, ask for one task at a time:

> Build task C1.1.2.T1 with the sparkwright-build skill.

Claude Code runs the loop: a fresh Test Author writes failing tests (plus a
fresh Property Tester when the task declares `invariants`), a fresh Builder
implements, SparkWright runs your checks, the library check and mutation
testing, locks the tests, a fresh Code Reviewer reviews, and a final gate
re-checks everything from git. C1 is `risk: high`, so a fresh Security
Reviewer also reviews each diff after the Code Reviewer. When it reports **ready**:

```powershell
git diff sparkwright/dogfood...sparkwright/C1.1.2.T1     # review
git merge --no-ff sparkwright/C1.1.2.T1
sparkwright check
```

Remaining tasks, in a sensible order:
`C1.1.2.T1`, `C1.1.3.T1`, `C1.2.1.T1`, `C1.2.2.T1`, `C1.3.1.T1`, `C1.3.2.T1`, `C1.4.1.T1`.

## 4. The full flow on a new feature

| Step | In Claude Code, ask… | Or run |
| --- | --- | --- |
| Existing code, no specs | "Adopt this codebase with the sparkwright-adopt skill" | `sparkwright adopt --prepare` |
| Evidence | "Interview me with the sparkwright-interview skill" | `sparkwright interview owner --host --consent "..."` |
| Real-user interviews | "Write an interview guide for parents of kids learning chess" | `sparkwright interview guide --about "..." --minors --prepare` |
| Vision / System | write them with Claude, then "Review VISION with the sparkwright-review skill" | `sparkwright review VISION --prepare` |
| Component / Tasks | "Descend S2.1 with the sparkwright-descend skill", then review the draft | `sparkwright descend S2.1 --prepare` |
| Approve (you, never an agent) | — | `sparkwright approve SYSTEM --as Srikanth` then commit |
| Build | "Build task C2.1.1.T1 with the sparkwright-build skill" | `sparkwright build C2.1.1.T1 --next` |
| Several tasks | "Plan builds for C2.1.1.T1 C2.1.2.T1 C2.2.1.T1" | `sparkwright build C2.1.1.T1 C2.1.2.T1 C2.2.1.T1 --plan` |
| Reviewer quality | "Calibrate the reviewers" | `sparkwright calibrate --prepare` |
| Check traceability | "Run sparkwright check and trace V1" | `sparkwright trace V1` |
| Change a spec | "Open a change request for C1.2.1" | `sparkwright change new C1.2.1 --reason "..."` |

Approvals count only when **you** commit them with the git email listed under
`approvers:` in `.sparkwright/config.yaml`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `sparkwright: command not found` inside Claude Code | run `uv tool update-shell`, restart the terminal and Claude Code |
| Build stops with "commit or stash spec and config changes" | commit your spec edits first; builds start from committed specs |
| Build is `blocked` | read the reason in `sparkwright build <task> --next`; fix the spec or code, then `sparkwright build <task> --restart --next` |
| Build is `changed` | the agent found a spec defect: edit the change request in `specs/changes/`, approve it, `sparkwright change apply CR<n>`, edit the requirement, review its file, then re-approve with `--cr CR<n>` (approval is refused until a review saw the new text) |
| "task X is building … may overlap" | another build touches the same files; merge it, or `sparkwright build X --abandon` |
| Tests are slow in every build | make sure `env: UV_PROJECT_ENVIRONMENT` is set in `.sparkwright/config.yaml` |
