"""The `build` workflow (SYSTEM S3.3–S3.6, S5.1–S5.5, "Build failure handling").

One engine, two modes:
  host mode   — `advance()` returns an agent step for the host (e.g. Claude Code) to perform;
                the host calls back with `submit()`.
  runner mode — `run()` performs agent steps itself through the Router.

Allowed paths are enforced after every agent step by diffing the workspace and
reverting anything the role may not change, so enforcement does not depend on
the host.
"""
from __future__ import annotations

import fnmatch
import json
import py_compile
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..core import approvals as approvals_mod, checks, config as config_mod, events as events_mod, ids, store
from ..core.approvals import Approval
from . import libcheck, mutate
from .personas import load_all
from .review import Finding, parse_findings
from .runlog import RunLog
from .verify import run_checks

MAX_ROUNDS = 2
AGENT_STEPS = {"test-author", "builder", "code-reviewer"}
TERMINAL = {"ready", "blocked", "changed"}
RUNNER_PATHS = ["specs/approvals.jsonl", "specs/events.jsonl", "specs/reviews/*"]


class BuildError(RuntimeError):
    pass


@dataclass
class State:
    phase: str = "prepare"
    base: str | None = None
    workspace: str | None = None
    branch: str | None = None
    rounds: dict = field(default_factory=lambda: {"red": 0, "builder": 0, "saboteur": 0})
    frozen: bool = False           # code frozen while the Test Author strengthens tests
    feedback: str = ""             # notes for the next agent step
    result: dict = field(default_factory=dict)


# ------------------------------------------------------------------ helpers
def _git(cwd: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(cwd), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise BuildError(f"git {' '.join(args[:3])} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _match(path: str, globs: list[str]) -> bool:
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return True
        if g.endswith("/**") and path.startswith(g[:-2]):
            return True
        if g.endswith("/") and path.startswith(g):
            return True
    return False


def _changed(ws: Path) -> list[str]:
    """Files changed in the working tree since HEAD, including untracked files."""
    out = _git(ws, "status", "--porcelain", "-uall", "--no-renames")
    files = []
    for line in out.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip().strip('"'))
    return sorted(set(files))


def _revert(ws: Path, paths: list[str]) -> None:
    tracked = set(_git(ws, "ls-files").splitlines())
    for p in paths:
        if p in tracked:
            _git(ws, "checkout", "HEAD", "--", p)
        else:
            target = ws / p
            if target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)


def _commit(ws: Path, task: str, role: str, subject: str, files: list[str]) -> str | None:
    if not files:
        return None
    _git(ws, "add", "-A", "--", *files)
    body = "\n".join(f"- {f}" for f in files)
    msg = f"{task}: {subject}\n\nFiles:\n{body}\n\nSparkWright-Task: {task}\nSparkWright-Role: {role}\n"
    _git(ws, "commit", "-q", "-m", msg)
    return _git(ws, "rev-parse", "HEAD").strip()


def _read(p: Path, limit: int = 60_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


# ------------------------------------------------------------------ the engine
class Build:
    def __init__(self, root: Path | str, task_id: str):
        self.root = Path(root).resolve()
        self.task = ids.canonical(task_id)
        if ids.kind_of(self.task) != "task":
            raise BuildError(f"{task_id} is not a task ID (expected C<n>.<m>.<k>.T<n>)")
        self.cfg, errors = config_mod.load(self.root)
        if errors:
            raise BuildError("; ".join(errors))
        self.repo = store.load(self.root)
        if self.task not in self.repo.requirements:
            raise BuildError(f"task {self.task} is not defined in specs/")
        self.req = self.repo.requirements[self.task]
        self.files = list(self.req.extras.get("files") or [])
        if not self.files:
            raise BuildError(f"task {self.task} declares no `files`; add a yaml block with files: [...] (S1.8)")
        self.test_globs = list(self.cfg["test_globs"])
        self.test_cmd = (self.cfg.get("checks") or {}).get("test")
        if not self.test_cmd:
            raise BuildError("set checks.test in .sparkwright/config.yaml so builds can run tests")
        self.log = RunLog(self.root, "build", f"build-{self.task}")
        self.state = self._load_state()

    # ---- persistence
    def _load_state(self) -> State:
        st = State()
        for rec in self.log.records():
            if rec.get("step") == "state":
                d = rec["state"]
                st = State(**d)
        return st

    def _save(self, note: str = "") -> None:
        self.log.append("state", status="done", state=self.state.__dict__, note=note)

    # ---- context for agents
    def _test_files(self, ws: Path) -> list[str]:
        if not self.state.base:
            return []
        out = _git(ws, "diff", "--name-only", self.state.base, "HEAD")
        cur = [f for f in out.splitlines() + _changed(ws) if _match(f, self.test_globs)]
        return sorted(set(cur))

    def _context(self, role: str) -> str:
        ws = Path(self.state.workspace)
        sf = self.repo.file_of[self.task]
        parts = [f"=== TASK {self.task} ===\n- **{self.task}** [{', '.join(self.req.refs)}] {self.req.text}\n"
                 f"Declared files: {json.dumps(self.files)}\nInvariants: {json.dumps(self.req.extras.get('invariants', []))}\n"
                 f"Test paths you may write: {json.dumps(self.test_globs)}\n"
                 f"Workspace (all paths are relative to it): {ws}"]
        parts.append(f"=== SPEC FILE ({sf.path}) ===\n" + _read(self.root / sf.path))
        seen = {sf.path}
        frontier = list(self.req.refs)
        while frontier:  # all ancestors' files
            rid = frontier.pop()
            owner = self.repo.file_of.get(rid)
            if owner and owner.path not in seen:
                seen.add(owner.path)
                parts.append(f"=== PARENT ({owner.path}) ===\n" + _read(self.root / owner.path))
            if rid in self.repo.requirements:
                frontier.extend(self.repo.requirements[rid].refs)
        const = self.root / "specs" / "constitution.md"
        if const.is_file():
            parts.append("=== CONSTITUTION ===\n" + _read(const))
        if role == "builder":
            for f in self._test_files(ws):
                parts.append(f"=== TEST ({f}) ===\n" + _read(ws / f))
            for f in self._existing_task_files(ws):
                parts.append(f"=== CURRENT SOURCE ({f}) ===\n" + _read(ws / f))
        if role == "test-author" and self.state.frozen:
            for f in self._existing_task_files(ws):
                parts.append(f"=== IMPLEMENTATION, FROZEN ({f}) ===\n" + _read(ws / f))
            for f in self._test_files(ws):
                parts.append(f"=== CURRENT TEST ({f}) ===\n" + _read(ws / f))
        if role == "code-reviewer":
            parts.append("=== DIFF ===\n" + _git(ws, "diff", self.state.base, "HEAD", "--", ".", ":(exclude)specs")[:80_000])
        if self.state.feedback:
            parts.append("=== FEEDBACK FROM THE PREVIOUS ATTEMPT ===\n" + self.state.feedback)
        return "\n\n".join(parts)

    def _existing_task_files(self, ws: Path) -> list[str]:
        out = []
        for g in self.files:
            for p in sorted(ws.glob(g)):
                rel = p.relative_to(ws).as_posix()
                if p.is_file() and not _match(rel, self.test_globs):
                    out.append(rel)
        return out

    # ---- events in the main repository
    def _event(self, kind: str, reason: str) -> None:
        events_mod.append(self.root, [events_mod.make(self.task, kind, run=self.log.run_id, reason=reason)])

    def _block(self, reason: str) -> dict:
        self.state.phase = "blocked"
        self.state.result = {"reason": reason}
        self._event("blocked", reason)
        self._save(reason)
        return self.instruction()

    def _spec_defect(self, defect: dict, role: str) -> dict:
        cited = ids.canonical(str(defect.get("cited_id", "")))
        ancestors = set()
        frontier = list(self.req.refs)
        while frontier:
            rid = frontier.pop()
            ancestors.add(rid)
            if rid in self.repo.requirements:
                frontier.extend(self.repo.requirements[rid].refs)
        target = cited if cited in ancestors or cited == self.task else self.req.refs[0]
        n = 1 + max([int(sf.id[2:]) for sf in self.repo.files if sf.id and ids.kind_of(sf.id) == "change"] or [0])
        cr = f"CR{n}"
        path = self.root / "specs" / "changes" / f"{cr}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"---\nid: {cr}\ntitle: Spec defect found while building {self.task}\ntype: change\nstatus: open\n"
            f"target: {target}\nraised_by: {role}\nrounds: 0\n---\n\n## Reason\n\n{defect.get('reason', '').strip()}\n\n"
            "## ADDED\n\n## MODIFIED\n\n## REMOVED\n", encoding="utf-8")
        self._event("changed", f"{cr}: {defect.get('reason', '')[:200]}")
        self.state.phase = "changed"
        self.state.result = {"change_request": f"specs/changes/{cr}.md", "target": target}
        self._save(f"spec defect -> {cr}")
        return self.instruction()

    # ---- path enforcement
    def _enforce(self, role: str) -> list[str]:
        ws = Path(self.state.workspace)
        changed = _changed(ws)
        if role == "test-author":
            bad = [f for f in changed if not _match(f, self.test_globs)]
        else:  # builder
            bad = [f for f in changed if not _match(f, self.files) or _match(f, self.test_globs) or f.startswith("specs/")]
        if bad:
            _revert(ws, bad)
        return bad

    # ---- public API
    def instruction(self) -> dict:
        st = self.state
        if st.phase in AGENT_STEPS:
            persona = load_all(self.root)[st.phase]
            run_dir = self.log.path.with_suffix("")
            run_dir.mkdir(parents=True, exist_ok=True)
            n = sum(st.rounds.values())
            prompt = run_dir / f"{st.phase}-{n}.md"
            prompt.write_text(persona.system_prompt() + "\n\n" + self._context(st.phase), encoding="utf-8")
            result_file = run_dir / f"{st.phase}-{n}.result.json"
            return {"task": self.task, "step": st.phase, "kind": "agent", "persona": st.phase,
                    "prompt": str(prompt.relative_to(self.root)), "workspace": st.workspace,
                    "result_file": str(result_file.relative_to(self.root)),
                    "then": f"sparkwright build {self.task} --done {st.phase} --result {result_file.relative_to(self.root).as_posix()}"}
        if st.phase == "ready":
            return {"task": self.task, "step": "ready", "kind": "human", "branch": st.branch, "workspace": st.workspace,
                    "message": f"Branch {st.branch} is ready. Review the diff, merge it into your main branch, then run `sparkwright check`.",
                    **st.result}
        if st.phase in ("blocked", "changed"):
            return {"task": self.task, "step": st.phase, "kind": "human", **st.result}
        return {"task": self.task, "step": st.phase, "kind": "auto"}

    def advance(self) -> dict:
        """Run automatic steps until an agent step or a terminal state is reached."""
        for _ in range(50):
            st = self.state
            if st.phase in AGENT_STEPS or st.phase in TERMINAL:
                return self.instruction()
            getattr(self, "_step_" + st.phase.replace("-", "_"))()
        raise BuildError("build did not settle after 50 automatic steps")

    def submit(self, step: str, output: str) -> dict:
        """Record an agent step's result (host mode) and continue."""
        st = self.state
        if step != st.phase:
            raise BuildError(f"expected result for step '{st.phase}', got '{step}'")
        self.log.append(f"agent:{step}", status="done", role=step, output=output[:4000])
        if step == "code-reviewer":
            findings = parse_findings(output)
            if findings is None:
                return self._block("Code Reviewer output was not a JSON findings array")
            self._write_code_review(findings)
            high = [f for f in findings if f.severity == "high"]
            if high:
                st.rounds["builder"] += 1
                if st.rounds["builder"] > MAX_ROUNDS:
                    return self._block("Code Reviewer still reports high-severity findings after 2 rounds")
                st.feedback = "Code Reviewer high-severity findings:\n" + "\n".join(f"- {f.finding} Fix: {f.fix}" for f in high)
                st.phase = "builder"
            else:
                st.feedback = ""
                st.phase = "finish"
            self._save("code review recorded")
            return self.advance()
        reply = _parse_reply(output)
        if "spec_defect" in reply:
            return self._spec_defect(reply["spec_defect"], step)
        if "files" in reply:  # runner mode: apply proposed files inside the workspace
            ws = Path(st.workspace)
            for rel, content in reply["files"].items():
                target = (ws / rel).resolve()
                if ws.resolve() not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        reverted = self._enforce(step)
        if reverted:
            self.log.append(f"enforce:{step}", status="done", reverted=reverted)
        st.feedback = (f"These changes were reverted because the {step} may not change them: {reverted}\n" if reverted else "")
        st.phase = "red-check" if step == "test-author" and not st.frozen else ("tests-pass" if step == "test-author" else "commit-build")
        self._save(f"{step} submitted")
        return self.advance()

    def run(self, router) -> dict:
        """Runner mode: perform agent steps with the configured models."""
        personas = load_all(self.root)
        ins = self.advance()
        while ins["kind"] == "agent":
            prompt = (self.root / ins["prompt"]).read_text(encoding="utf-8").split("\n\n", 1)[1]
            if ins["step"] != "code-reviewer":
                prompt += ("\n\nYou cannot edit files directly. Reply with ONE JSON object: "
                           '{"files": {"<relative path>": "<full new content>"}, "status": "ok"} '
                           'or {"spec_defect": {"cited_id": "...", "reason": "..."}}.')
            res = router.call(personas[ins["step"]], prompt, max_tokens=16000)
            self.log.append(f"call:{ins['step']}", status="done", role=ins["step"], tier=res.tier, model=res.model,
                            input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                            cost_usd=round(res.cost_usd, 6), duration_s=res.duration_s)
            ins = self.submit(ins["step"], res.text)
        return ins

    # ---- automatic steps
    def _step_prepare(self) -> None:
        status = checks.run(self.root, write_ledger=False).nodes[self.task].status
        if status not in ("approved", "building"):
            raise BuildError(f"task {self.task} is '{status}'; it must be approved before it is built "
                             f"(`sparkwright approve {self.task} --as <name>`)")
        base = _git(self.root, "rev-parse", "HEAD").strip()
        branch = f"sparkwright/{self.task}"
        ws = self.root / ".sparkwright" / "worktrees" / self.task
        if not ws.exists():
            _git(self.root, "worktree", "add", "-q", "-b", branch, str(ws), base)
        self.state.base, self.state.workspace, self.state.branch = base, str(ws), branch
        self._event("building", f"build started on {branch}")
        self.state.phase = "test-author"
        self._save("workspace ready")

    def _step_red_check(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        new_tests = [f for f in _changed(ws) if _match(f, self.test_globs)]
        problem = ""
        if not new_tests:
            problem = "No test files were written."
        for f in new_tests:
            if f.endswith(".py"):
                try:
                    py_compile.compile(str(ws / f), doraise=True)
                except py_compile.PyCompileError as exc:
                    problem = f"Test file {f} does not compile: {exc.msg}"
        if not problem:
            res = run_checks(ws, {"test": self.test_cmd})[0]
            if res.ok:
                problem = "The new tests pass before any implementation exists, so they do not test the task."
            elif _runner_broken(res.output):
                problem = ("The test command failed before running any test (collection or discovery error), so the "
                           "red check cannot tell whether the tests are meaningful. Output:\n" + res.output[-1500:])
        if problem:
            st.rounds["red"] += 1
            self.log.append("red-check", status="failed", reason=problem)
            if st.rounds["red"] > MAX_ROUNDS:
                self._block(f"Red check failed after {MAX_ROUNDS} rounds: {problem}")
                return
            st.feedback = problem
            st.phase = "test-author"
            self._save("red check failed")
            return
        _commit(ws, self.task, "test-author", "tests (red)", new_tests)
        self.log.append("red-check", status="done", tests=new_tests)
        st.feedback, st.phase = "", "builder"
        self._save("tests red and committed")

    def _step_tests_pass(self) -> None:
        """After the Test Author strengthens tests against frozen code, the tests must pass."""
        st, ws = self.state, Path(self.state.workspace)
        res = run_checks(ws, {"test": self.test_cmd})[0]
        if not res.ok:
            st.rounds["saboteur"] += 1
            if st.rounds["saboteur"] > MAX_ROUNDS:
                self._block("Strengthened tests fail against the frozen implementation after 2 rounds")
                return
            st.feedback = "Your new tests fail against the implementation, which is frozen:\n" + res.output[-2000:]
            st.phase = "test-author"
            self._save("strengthened tests fail")
            return
        _commit(ws, self.task, "test-author", "strengthen tests", [f for f in _changed(ws) if _match(f, self.test_globs)])
        st.frozen, st.feedback, st.phase = False, "", "saboteur"
        self._save("tests strengthened")

    def _step_commit_build(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        changed = _changed(ws)
        if not changed:
            st.rounds["builder"] += 1
            if st.rounds["builder"] > MAX_ROUNDS:
                self._block("Builder made no changes")
                return
            st.feedback, st.phase = "You made no changes. Implement the task.", "builder"
            self._save("no builder changes")
            return
        _commit(ws, self.task, "builder", "implement", changed)
        st.phase = "verify"
        self._save("build committed")

    def _builder_retry(self, why: str, output: str) -> None:
        st = self.state
        st.rounds["builder"] += 1
        if st.rounds["builder"] > MAX_ROUNDS:
            self._block(f"{why} after {MAX_ROUNDS} builder rounds")
            return
        st.feedback = f"{why}:\n{output[-3000:]}"
        st.phase = "builder"
        self._save(why)

    def _step_verify(self) -> None:
        ws = Path(self.state.workspace)
        results = run_checks(ws, self.cfg.get("checks") or {})
        self.log.append("verify", status="done", results=[{"name": r.name, "ok": r.ok} for r in results])
        failed = [r for r in results if not r.ok]
        if failed:
            self._builder_retry("Project checks failed", "\n\n".join(f"[{r.name}] {r.output}" for r in failed))
            return
        self.state.phase = "library"
        self._save("verify green")

    def _step_library(self) -> None:
        ws = Path(self.state.workspace)
        changed = _git(ws, "diff", "--name-only", self.state.base, "HEAD").splitlines()
        src = [f for f in changed if f.endswith(".py") and not _match(f, self.test_globs)]
        issues = libcheck.check(ws, src)
        self.log.append("library", status="done", issues=[i.__dict__ for i in issues])
        if issues:
            self._builder_retry("Library Checker found problems", "\n".join(f"{i.file}:{i.line}: {i.message}" for i in issues))
            return
        self.state.phase = "saboteur"
        self._save("library check passed")

    def _step_saboteur(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        mcfg = self.cfg.get("mutation") or {}
        rep = mutate.run(ws, st.base, self.test_cmd, float(mcfg.get("time_budget_s", 300)))
        minimum = float(mcfg.get("min", 0.8))
        self.log.append("saboteur", status="done", score=rep.score, total=rep.total, killed=rep.killed,
                        survivors=[f"{m.file}:{m.line} {m.description}" for m in rep.survivors][:50], message=rep.message)
        if not rep.baseline_ok:
            self._builder_retry("Tests do not pass", rep.message)
            return
        if rep.score < minimum:
            st.rounds["saboteur"] += 1
            if st.rounds["saboteur"] > MAX_ROUNDS:
                self._block(f"Mutation score {rep.score:.2f} still below {minimum:.2f} after {MAX_ROUNDS} rounds")
                return
            st.frozen = True
            st.feedback = (f"Mutation score {rep.score:.2f} is below {minimum:.2f}. These planted bugs were NOT caught; "
                           "add tests that fail on each:\n" + "\n".join(f"- {m.file}:{m.line} {m.description}" for m in rep.survivors[:30]))
            st.phase = "test-author"
            self._save("saboteur: weak tests")
            return
        st.result["mutation_score"] = round(rep.score, 3)
        st.phase = "lock-tests"
        self._save("saboteur passed")

    def _step_lock_tests(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        tests = [f for f in _git(ws, "diff", "--name-only", st.base, "HEAD").splitlines() if _match(f, self.test_globs)]
        when = approvals_mod.now()
        entries = [Approval(f"test:{f}", checks.file_hash(ws / f), "sparkwright-runner", "runner", None, when)
                   for f in tests if (ws / f).is_file()]
        approvals_mod.append(ws, entries)
        _commit(ws, self.task, "runner", "lock tests", ["specs/approvals.jsonl"])
        st.phase = "code-reviewer"
        self._save("tests locked")

    def _write_code_review(self, findings: list[Finding]) -> None:
        ws = Path(self.state.workspace)
        n = sum(self.state.rounds.values())
        rel = f"specs/reviews/{date.today().isoformat()}-{self.task.lower()}-code-{n}.md"
        rows = "\n".join(f"| F{i} | {f.severity} | {', '.join(f.ids) or '—'} | {f.finding} | {f.fix} | open |"
                         for i, f in enumerate(findings, 1)) or "| — | — | — | No findings | — | — |"
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text(
            f"---\nid: R{''.join(ch for ch in self.task if ch.isdigit())}{n:02d}\ntitle: Code review of {self.task}\ntype: review\nstatus: in-review\n---\n\n"
            "| ID | Severity | Requirements | Finding | Suggested fix | Decision |\n| --- | --- | --- | --- | --- | --- |\n"
            f"{rows}\n", encoding="utf-8")
        _commit(ws, self.task, "runner", "code review", [rel])

    def _step_finish(self) -> None:
        self.state.phase = "ready"
        self._save("ready for human merge")


BROKEN_RUNNER = [
    r"Start directory is not importable", r"\bRan 0 tests\b", r"\bno tests ran\b",
    r"ERROR: file or directory not found", r"error: unrecognized arguments", r"No module named (pytest|unittest)\b",
    r"collected 0 items",
]


def _runner_broken(output: str) -> bool:
    """Heuristic: the test command failed for infrastructure reasons, not because a test failed."""
    return any(re.search(p, output, re.I) for p in BROKEN_RUNNER)


def _parse_reply(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return {"status": "ok"}
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else {"status": "ok"}
    except json.JSONDecodeError:
        m = re.search(r'"spec_defect"', text)
        return {"spec_defect": {"cited_id": "", "reason": text[:500]}} if m else {"status": "ok"}
