# SparkWright

**From a spark of an idea to verified, traceable code.**

SparkWright is an open-source, platform-agnostic framework for spec-driven
development with AI coding agents. Specs are written in levels (Evidence →
Vision → System → Component → Task), each level is challenged by fresh-context
agents that never saw the conversation that produced it, and every commit traces
back to a requirement and the user evidence behind it.

Part of the [KubeRiva](https://github.com/kuberiva) open-source family.

> Status: early development (0.1.0.dev0). Every workflow in `specs/system.md`
> is implemented: interviews and interview guides, review, descend, adopt,
> build (including parallel builds and the Prover hook), change requests and
> reviewer calibration, with a Claude Code adapter. Not yet done: a public
> benchmark run, a PyPI release and adapters beyond Claude Code and AGENTS.md.
> See `docs/quickstart-claude-code.md` to try it.

## Why

AI agents build fast and drift fast. SparkWright makes three promises:

1. **Traceable or it doesn't ship.** `sparkwright trace C2.3.1.T3` shows the
   user quote that justified it and the tests and commits that implement it.
2. **The author never grades its own work.** Reviews, tests and code come from
   different agents with different context. Mutation testing checks the tests.
3. **Nothing changes silently.** Approved specs and tests are hash-locked; only
   an approved change request can alter them.

## Install

```sh
git clone https://github.com/kuberiva/sparkwright
cd sparkwright && pip install -e .   # PyPI release coming
sparkwright init          # creates specs/, templates and .sparkwright/config.yaml
```

Python 3.10+. One runtime dependency (PyYAML).

## Commands

| Command | What it does | Needs a model? |
| --- | --- | --- |
| `sparkwright init` | Create `specs/`, templates and `.sparkwright/config.yaml` | No |
| `sparkwright check` | Grammar, coverage, approval locks, drift, protected paths | No |
| `sparkwright trace <ID>` | Why a requirement exists and what implements it | No |
| `sparkwright status` | Levels, gaps, drift, open findings, agent cost | No |
| `sparkwright approve <ID> --as <name>` | Record a human approval (append-only, hashed, records the risk tier) | No |
| `sparkwright interview owner` | Interview the owner one question at a time → evidence | Yes ¹ |
| `sparkwright interview ingest <file> --consent "..."` | Turn a user-interview transcript into anonymized evidence | Yes ¹ |
| `sparkwright interview guide --about "..."` | Draft an interview guide for real users; check it for leading questions (parental consent for minors) | Yes ¹ |
| `sparkwright adopt` | Draft System, Component and Task specs bottom-up from an existing codebase | Yes ¹ |
| `sparkwright review <ID>` | Fresh-context Inspector swarm, merged findings, gate | Yes ¹ |
| `sparkwright descend <ID>` | Architect drafts the next level (component or tasks) under an approved requirement | Yes ¹ |
| `sparkwright build <task>` | Tests first, property tests for invariants, code, checks, Prover (`prove: true`), library check, mutation, test lock, code and security review, on its own branch | Yes ¹ |
| `sparkwright build <task> <task> ... --plan` | Group tasks into batches whose files cannot overlap (build a batch in parallel) | No |
| `sparkwright calibrate` | Score each Inspector on planted-flaw specs: catch rate and false-alarm rate | Yes ¹ |
| `sparkwright verify` | Run the project's checks from config | No |
| `sparkwright mutate --base <rev>` | Saboteur: mutation-test the lines you changed | No |
| `sparkwright change new <ID> \| apply <CR>` | Open or apply a change request when an approved spec is wrong | No |
| `sparkwright adapt claude-code \| agents-md` | Generate host adapters | No |
| `sparkwright guard` | PreToolUse hook used by host adapters | No |

¹ Either a configured model provider (Runner mode), or a host coding agent
that runs the agent steps itself (host mode: `--prepare`/`--collect` for
interview, review, descend, adopt and calibrate, `--next`/`--done` for build).
In host mode no separate API key is needed.

**Risk tiers.** Component and task files declare `risk: low | medium | high`.
High-risk work always gets the Security Reviewer, in spec review and after
code review, and always needs a human gate. Changing an artifact's risk voids
its approvals until a human re-approves.

Every command accepts `--json`.

## Specs in one minute

Every requirement is one line:

```markdown
- **S2.4** [V8] When a requirement is approved, the system shall record its hash in specs/approvals.jsonl.
```

The ID says where it sits in the pyramid; the brackets say which parent it
serves. Vision lines cite evidence (`E01`) or an explicit assumption (`A1`).
Tasks may declare the files they own:

````markdown
- **C2.3.1.T3** [C2.3.1] When the student is stuck for 60s, the tutor shall offer hint level 1.

```yaml
files: ["src/tutor/hints/**"]
invariants: ["a hint never reveals more than one level at a time"]
```
````

## Models: any provider

`.sparkwright/config.yaml` maps tiers (`top`, `mid`, `fast`) to any provider:
Anthropic, any OpenAI-compatible server (OpenAI, hosted gateways, local servers
such as Ollama or vLLM). API keys are read from environment variables only.

## Coding agents: any host

- **Claude Code:** `claude plugin marketplace add kuberiva/sparkwright` then
  `claude plugin install sparkwright@sparkwright`. Interviews, reviews, descend
  and builds run on Claude Code's own subagents, so no separate API key is
  needed. A PreToolUse hook (`sparkwright guard`) stops agents from editing
  approvals, events, locked tests or git internals. See
  `docs/quickstart-claude-code.md`.
- **Everything else:** `sparkwright adapt agents-md` writes a section into
  `AGENTS.md`, which most coding agents read.
- **CI:** `sparkwright check` needs no network and no model.

## Dogfooding

SparkWright is specified in SparkWright: see `specs/`. The first Inspector
review (`specs/reviews/2026-10-24-system-review.md`) found 14 high-severity
issues in the System spec before any code was written.

## Credits and licence

Apache 2.0, © KubeRiva. The idea of reviewing specs with zero-context agents was inspired by
Google's [Elephant-Goldfish Model](https://github.com/google/elephant-goldfish-model);
see `NOTICE`. No code or text from that project is included.
