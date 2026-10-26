# Quickstart: SparkWright with Claude Code (Windows)

This runs SparkWright on your Claude Code subscription: Claude Code's own
agents do the interviewing, reviewing, testing and building, and the
`sparkwright` CLI enforces the rules. No API key is needed.

Commands are for PowerShell; they work the same in bash or zsh on macOS and Linux.

## 1. Install the CLI (once)

```powershell
uv tool install git+https://github.com/KubeRiva/SparkWright.git
uv tool update-shell          # puts sparkwright on PATH; open a new terminal afterwards
sparkwright --version
```

Without uv: `pip install git+https://github.com/KubeRiva/SparkWright.git`.
To work on SparkWright itself, clone it and use `uv tool install --editable <clone>`.

The Claude Code plugin calls `sparkwright guard` before every file edit and
shell command, so the CLI must be on PATH for Claude Code too.

## 2. Install the Claude Code plugin (once)

```powershell
claude plugin marketplace add KubeRiva/SparkWright
claude plugin install sparkwright@sparkwright
```

This adds eight skills (`sparkwright-interview`, `sparkwright-review`,
`sparkwright-descend`, `sparkwright-build`, `sparkwright-adopt`,
`sparkwright-calibrate`, `sparkwright-check`, `sparkwright-mutate`), the
fresh-context agents they use, and the guard hook.

To update later, run `uv tool upgrade sparkwright`, then `claude plugin marketplace update sparkwright` then
`claude plugin update sparkwright@sparkwright`, and restart Claude Code. If
an update is not picked up, uninstall and install it again.

## 3. Start a project

```powershell
mkdir my-app; cd my-app
git init
git commit --allow-empty -m "start"
sparkwright init
```

Open `.sparkwright\config.yaml` and check that `approvers` lists your name and
git email, set `checks: {test: "python -m pytest -q"}` (or your own test
command), and add `guard: {strict: true}` if Claude should only change code
inside task builds. Commit, then start Claude Code in the folder:

```powershell
git add -A; git commit -m "SparkWright init"
claude
```

For an existing codebase, run `sparkwright init` there and ask Claude to
"adopt this codebase with the sparkwright-adopt skill".

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
| Change a spec | "Open a change request for C1.2.1" | `sparkwright change new C1.2.1 [more IDs] --reason "..."` |

Approvals count only when **you** commit them with the git email listed under
`approvers:` in `.sparkwright/config.yaml`. The same goes for protected files
(`AGENTS.md`, `.sparkwright/config.yaml`, `specs/approvals.jsonl`, locked tests)
and for closing a high-severity review finding.

**Signing risky approvals.** Approvals of `risk: high` work should be in
signed commits. Until you set it up, `check` only warns. To switch it on:
`git config commit.gpgsign true` (with a GPG or SSH signing key), then set
`signing_from: <last commit before signing>` in `.sparkwright/config.yaml`.

**Secret keys.** Tests and AI-written code run without variables that look
like secrets (`*_API_KEY`, `*TOKEN*`, `AWS_*` …). If a test needs one, list
it under `sandbox: {keep_env: [NAME]}`.

**Keep Claude on the rails.** Set `guard: {strict: true}` in
`.sparkwright/config.yaml` and Claude Code can change code only inside a task
build; it is told to draft or build a task instead. Run `sparkwright check` in
CI as a required status check so nothing untraced reaches main.

**Sandbox.** Tests and AI-written code run with HOME pointed at an empty folder,
so credentials in your home folder are not at their usual paths. If your tests
need your real home folder, set `sandbox: {isolate_home: false}`. On Linux,
`sandbox: {network: false}` also cuts network access.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `sparkwright: command not found` inside Claude Code | run `uv tool update-shell`, restart the terminal and Claude Code |
| Build stops with "commit or stash spec and config changes" | commit your spec edits first; builds start from committed specs |
| Build is `blocked` | read the reason in `sparkwright build <task> --next`; fix the spec or code, then `sparkwright build <task> --restart --next` |
| Build is `changed` | the agent found a spec defect: edit the change request in `specs/changes/`, approve it, `sparkwright change apply CR<n>`, edit the requirement, review its file, then re-approve with `--cr CR<n>` (approval is refused until a review saw the new text) |
| "task X is building … may overlap" | another build touches the same files; merge it, or `sparkwright build X --abandon` |
| Tests are slow in every build | make sure `env: UV_PROJECT_ENVIRONMENT` is set in `.sparkwright/config.yaml` |
