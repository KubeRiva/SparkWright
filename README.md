# SparkWright

**From a spark of an idea to verified, traceable code.**

SparkWright is an open-source, platform-agnostic framework for spec-driven
development with AI coding agents. Specs are written in levels (Evidence →
Vision → System → Component → Task), each level is challenged by fresh-context
agents that never saw the conversation that produced it, and every commit traces
back to a requirement and the user evidence behind it.

Part of the [KubeRiva](https://github.com/kuberiva) open-source family.

> Status: early development (0.1.0.dev0). The offline core, review and
> interview workflows, the Saboteur and the Claude Code adapter work today; the
> full build loop is next. See `specs/system.md`, section "MVP scope".

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
| `sparkwright check` | Grammar, coverage, approval locks, drift, protected paths | No |
| `sparkwright trace <ID>` | Why a requirement exists and what implements it | No |
| `sparkwright status` | Levels, gaps, drift, agent cost | No |
| `sparkwright approve <ID> --as <name>` | Record a human approval (append-only, hashed) | No |
| `sparkwright mutate --base <rev>` | Saboteur: mutation-test the lines you changed | No |
| `sparkwright interview owner` | Interview the owner one question at a time → evidence | Yes |
| `sparkwright interview ingest <file> --consent "..."` | Turn a user-interview transcript into evidence | Yes |
| `sparkwright review <ID>` | Fresh-context Inspector swarm, merged findings, gate | Yes |
| `sparkwright adapt claude-code \| agents-md` | Generate host adapters | No |

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
  `claude plugin install sparkwright@sparkwright`. Reviews run on Claude Code's
  own subagents, so no separate API key is needed.
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
