"""The `build` workflow (SYSTEM S3.3–S3.6, S5.1–S5.5, "Build failure handling").

One engine, two modes:
  host mode   — `advance()` returns an agent step for the host (e.g. Claude Code) to perform;
                the host calls back with `submit()`.
  runner mode — `run()` performs agent steps itself through the Router.

Trust model: nothing an agent reports, writes to the run log, or commits is
trusted. After every agent step the engine unwinds agent-made commits, then
reverts every change the role may not make. Before a build is declared ready a
final gate re-derives the evidence from git: the red tests failed, the checks
pass, the mutation score holds, tests are locked and the code was reviewed.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import py_compile
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from ..core import approvals as approvals_mod, checks, config as config_mod, events as events_mod, ids, store
from ..core.approvals import Approval
from . import libcheck, mutate
from .personas import load_all
from .review import Finding, parse_findings
from .runlog import RunLog
from .verify import command_env, run_checks

MAX_ROUNDS = 2
AGENT_STEPS = {"test-author", "builder", "code-reviewer"}
TERMINAL = {"ready", "blocked", "changed"}
ENGINE_DIRTY_OK = ("specs/events.jsonl", "specs/changes/")  # the engine itself writes these in the main tree


class BuildError(RuntimeError):
    pass


@dataclass
class State:
    phase: str = "prepare"
    base: str | None = None
    workspace: str | None = None
    branch: str | None = None
    rounds: dict = field(default_factory=lambda: {"red": 0, "builder": 0, "saboteur": 0})
    frozen: bool = False
    feedback: str = ""
    step_head: str | None = None   # workspace HEAD when the current agent step started
    red_commit: str | None = None
    result: dict = field(default_factory=dict)


# ------------------------------------------------------------------ helpers
def _git(cwd: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(cwd), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise BuildError(f"git {' '.join(args[:3])} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def _git_bytes(cwd: Path, *args: str) -> bytes | None:
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def _match(path: str, globs: list[str]) -> bool:
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return True
        if g.endswith("/**") and path.startswith(g[:-2]):
            return True
    return False


def _status(ws: Path) -> list[tuple[str, str]]:
    """(code, path) for staged and unstaged changes including untracked files."""
    out = _git(ws, "status", "--porcelain", "-uall", "--no-renames")
    res = []
    for line in out.splitlines():
        if len(line) > 3:
            res.append((line[:2], line[3:].strip().strip('"')))
    return res


def _changed(ws: Path) -> list[str]:
    return sorted({p for _, p in _status(ws)})


def _blob_hash(ws: Path, rev: str, path: str) -> str | None:
    data = _git_bytes(ws, "show", f"{rev}:{path}")
    return None if data is None else hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _commit(ws: Path, task: str, role: str, subject: str, files: list[str], extra: str = "", allow_empty: bool = False) -> str | None:
    if not files and not allow_empty:
        return None
    if files:
        _git(ws, "add", "-A", "--", *files)
    body = "\n".join(f"- {f}" for f in files) or "- (none)"
    msg = f"{task}: {subject}\n\nFiles:\n{body}\n{extra}\nSparkWright-Task: {task}\nSparkWright-Role: {role}\n"
    _git(ws, "commit", "-q", *(["--allow-empty"] if allow_empty else []), "-m", msg)
    return _git(ws, "rev-parse", "HEAD").strip()


def _read(p: Path, limit: int = 60_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def safe_relpath(rel) -> str | None:
    """A normalised relative POSIX path, or None if it is absolute, escapes, or touches .git/.sparkwright."""
    if not isinstance(rel, str) or not rel or "\\" in rel or "\x00" in rel:
        return None
    pp = PurePosixPath(rel)
    if pp.is_absolute() or re.match(r"^[A-Za-z]:", rel):
        return None
    parts = pp.parts
    if any(p in ("..", ".git") for p in parts) or parts[0] in (".sparkwright",):
        return None
    return pp.as_posix()


# ------------------------------------------------------------------ the engine
class Build:
    def __init__(self, root: Path | str, task_id: str, restart: bool = False):
        self.root = Path(root).resolve()
        self.task = ids.canonical(task_id)
        self.restart = restart
        if ids.kind_of(self.task) != "task":
            raise BuildError(f"{task_id} is not a task ID (expected C<n>.<m>.<k>.T<n>)")
        self.cfg, errors = config_mod.load(self.root)
        if errors:
            raise BuildError("; ".join(errors))
        self.repo = store.load(self.root)
        if self.task not in self.repo.requirements:
            raise BuildError(f"task {self.task} is not defined in specs/")
        self.req = self.repo.requirements[self.task]
        if not self.req.refs:
            raise BuildError(f"task {self.task} cites no parent")
        self.files = list(self.req.extras.get("files") or [])
        if not self.files:
            raise BuildError(f"task {self.task} declares no `files`; add a yaml block with files: [...] (S1.8)")
        self.test_globs = list(self.cfg["test_globs"])
        self.test_cmd = (self.cfg.get("checks") or {}).get("test")
        if not self.test_cmd:
            raise BuildError("set checks.test in .sparkwright/config.yaml so builds can run tests")
        self.env = command_env(self.cfg.get("env"), self.root)
        self.run_no = self._latest_run_no()
        self._open_run()

    # ---- runs and persistence
    def _run_id(self, n: int) -> str:
        return f"build-{self.task}" if n == 1 else f"build-{self.task}-{n}"

    def _latest_run_no(self) -> int:
        runs = self.root / ".sparkwright" / "runs"
        n = 1
        if runs.is_dir():
            for p in runs.glob(f"build-{self.task}*.jsonl"):
                m = re.fullmatch(rf"build-{re.escape(self.task)}(?:-(\d+))?", p.stem)
                if m:
                    n = max(n, int(m.group(1) or 1))
        return n

    def _open_run(self) -> None:
        self.log = RunLog(self.root, "build", self._run_id(self.run_no))
        st = State()
        for rec in self.log.records():
            if rec.get("step") == "state" and isinstance(rec.get("state"), dict):
                try:
                    st = State(**rec["state"])
                except TypeError:
                    pass
        self.state = st

    def _save(self, note: str = "") -> None:
        self.log.append("state", status="done", state=asdict(self.state), note=note)

    def _enter(self, phase: str) -> None:
        self.state.phase = phase
        if phase in AGENT_STEPS and self.state.workspace:
            self.state.step_head = _git(Path(self.state.workspace), "rev-parse", "HEAD").strip()

    def _new_run(self) -> None:
        old = self.state
        if old.workspace and Path(old.workspace).exists():
            _git(self.root, "worktree", "remove", "--force", old.workspace, check=False)
        if old.branch:
            _git(self.root, "branch", "-D", old.branch, check=False)
        _git(self.root, "worktree", "prune", check=False)
        self.run_no += 1
        self._open_run()

    # ---- locked tests
    def _locked_at(self, rev: str) -> dict[str, str]:
        data = _git_bytes(Path(self.state.workspace), "show", f"{rev}:{approvals_mod.APPROVALS_PATH}") or b""
        locked = {}
        for line in data.decode("utf-8", "replace").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(d.get("id", "")).startswith("test:"):
                locked[d["id"][5:]] = d.get("hash", "")
        return locked

    # ---- context for agents
    def _test_files(self, ws: Path) -> list[str]:
        if not self.state.base:
            return []
        out = _git(ws, "diff", "--name-only", self.state.base, "HEAD")
        cur = [f for f in out.splitlines() + _changed(ws) if _match(f, self.test_globs) and (ws / f).is_file()]
        return sorted(set(cur))

    def _existing_task_files(self, ws: Path) -> list[str]:
        out = []
        for g in self.files:
            for p in sorted(ws.glob(g)):
                rel = p.relative_to(ws).as_posix()
                if p.is_file() and not _match(rel, self.test_globs):
                    out.append(rel)
        return out

    def _context(self, role: str) -> str:
        ws = Path(self.state.workspace)
        sf = self.repo.file_of[self.task]
        parts = [f"=== TASK {self.task} ===\n- **{self.task}** [{', '.join(self.req.refs)}] {self.req.text}\n"
                 f"Declared files: {json.dumps(self.files)}\nInvariants: {json.dumps(self.req.extras.get('invariants', []))}\n"
                 f"Test paths you may write: {json.dumps(self.test_globs)}\n"
                 f"Workspace (all paths are relative to it): {ws}"]
        parts.append(f"=== SPEC FILE ({sf.path}) ===\n" + _read(self.root / sf.path))
        seen, frontier = {sf.path}, list(self.req.refs)
        while frontier:
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

    # ---- events and terminal states
    def _event(self, kind: str, reason: str) -> None:
        events_mod.append(self.root, [events_mod.make(self.task, kind, run=self.log.run_id, reason=reason)])

    def _block(self, reason: str) -> dict:
        self.state.phase = "blocked"
        self.state.result = {"reason": reason}
        self._event("blocked", reason[:300])
        self._save(reason)
        return self.instruction()

    def _spec_defect(self, defect: dict, role: str) -> dict:
        cited = ids.canonical(str(defect.get("cited_id", "")))
        ancestors, frontier = set(), list(self.req.refs)
        while frontier:
            rid = frontier.pop()
            ancestors.add(rid)
            if rid in self.repo.requirements:
                frontier.extend(self.repo.requirements[rid].refs)
        target = cited if (cited in ancestors or cited == self.task) else self.req.refs[0]
        n = 1 + max([int(sf.id[2:]) for sf in self.repo.files if sf.id and ids.kind_of(sf.id) == "change"] or [0])
        cr = f"CR{n}"
        path = self.root / "specs" / "changes" / f"{cr}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        reason = str(defect.get("reason", "")).strip()[:2000]
        path.write_text(
            f"---\nid: {cr}\ntitle: Spec defect found while building {self.task}\ntype: change\nstatus: open\n"
            f"target: {target}\nraised_by: {role}\nrounds: 0\n---\n\n## Reason\n\n{reason}\n\n"
            "## ADDED\n\n## MODIFIED\n\n## REMOVED\n", encoding="utf-8")
        self._event("changed", f"{cr}: {reason[:200]}")
        self.state.phase = "changed"
        self.state.result = {"change_request": f"specs/changes/{cr}.md", "target": target}
        self._save(f"spec defect -> {cr}")
        return self.instruction()

    # ---- enforcement
    def _allowed(self, role: str, path: str, deleted: bool, locked: set[str]) -> bool:
        if safe_relpath(path) is None or path.startswith("specs/"):
            return False
        if role == "test-author":
            return _match(path, self.test_globs) and path not in locked and not deleted
        if role == "builder":
            return _match(path, self.files) and not _match(path, self.test_globs)
        return False  # code-reviewer and anything else: read-only

    def _unwind_and_enforce(self, role: str) -> list[str]:
        """Undo agent commits, then revert every change the role may not make. Returns reverted paths."""
        st, ws = self.state, Path(self.state.workspace)
        head_ref = _git(ws, "symbolic-ref", "-q", "HEAD", check=False).strip()
        if head_ref != f"refs/heads/{st.branch}":
            _git(ws, "checkout", "-q", "-f", st.branch)
        if _git(ws, "rev-parse", "HEAD").strip() != st.step_head:
            self.log.append(f"unwind:{role}", status="done", note="agent-made commits turned back into changes")
            _git(ws, "reset", "-q", "--soft", st.step_head)
        locked = set(self._locked_at(st.base))
        tracked = set(_git(ws, "ls-tree", "-r", "--name-only", st.step_head).splitlines())
        bad = []
        for code, path in _status(ws):
            deleted = "D" in code
            if not self._allowed(role, path, deleted, locked):
                bad.append(path)
                _git(ws, "reset", "-q", st.step_head, "--", path, check=False)
                if path in tracked:
                    _git(ws, "checkout", "-q", st.step_head, "--", path)
                else:
                    target = ws / path
                    if target.is_symlink() or target.is_file():
                        target.unlink()
                    elif target.is_dir():
                        shutil.rmtree(target)
        return sorted(set(bad))

    def _apply_files(self, role: str, files) -> list[str]:
        """Runner mode: write proposed files after validation (S6.5: refuse, don't write-then-revert)."""
        ws = Path(self.state.workspace).resolve()
        locked = set(self._locked_at(self.state.base))
        refused = []
        if not isinstance(files, dict):
            return ["<files is not an object>"]
        for rel, content in files.items():
            norm = safe_relpath(rel)
            if norm is None or not isinstance(content, str) or not self._allowed(role, norm, False, locked):
                refused.append(str(rel)[:200])
                continue
            target = ws / norm
            cur = ws
            ok = True
            for part in PurePosixPath(norm).parts[:-1]:
                cur = cur / part
                if cur.is_symlink():
                    ok = False
                    break
            if not ok or target.is_symlink():
                refused.append(norm)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return refused

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
                    "prompt": prompt.relative_to(self.root).as_posix(), "workspace": st.workspace,
                    "result_file": result_file.relative_to(self.root).as_posix(),
                    "then": f"sparkwright build {self.task} --done {st.phase} --result {result_file.relative_to(self.root).as_posix()}"}
        if st.phase == "ready":
            if not self._ready_marker_ok():
                return self._block("ready state is not backed by a ready commit on the branch (run log tampered?)")
            return {"task": self.task, "step": "ready", "kind": "human", "branch": st.branch, "workspace": st.workspace,
                    "message": f"Branch {st.branch} is ready. Review the diff, merge it into your main branch, then run `sparkwright check`.",
                    **st.result}
        if st.phase in ("blocked", "changed"):
            return {"task": self.task, "step": st.phase, "kind": "human", **st.result}
        return {"task": self.task, "step": st.phase, "kind": "auto"}

    def advance(self) -> dict:
        if self.state.phase in ("blocked", "changed"):
            status = checks.run(self.root, write_ledger=False).nodes[self.task].status
            if self.restart or (self.state.phase == "changed" and status == "approved"):
                self._new_run()
        for _ in range(60):
            st = self.state
            if st.phase in AGENT_STEPS or st.phase in TERMINAL:
                return self.instruction()
            getattr(self, "_step_" + st.phase.replace("-", "_"))()
        raise BuildError("build did not settle after 60 automatic steps")

    def submit(self, step: str, output: str) -> dict:
        st = self.state
        if step != st.phase or step not in AGENT_STEPS:
            raise BuildError(f"expected result for step '{st.phase}', got '{step}'")
        self.log.append(f"agent:{step}", status="done", role=step, output=output[:4000])
        if step == "code-reviewer":
            ws = Path(st.workspace)
            _git(ws, "checkout", "-q", "-f", st.branch, check=False)
            _git(ws, "reset", "-q", "--hard", st.step_head)
            _git(ws, "clean", "-q", "-fd")
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
                self._enter("builder")
            else:
                st.feedback = ""
                self._enter("finish")
            self._save("code review recorded")
            return self.advance()
        reply = _parse_reply(output)
        refused = []
        if "files" in reply:
            refused = self._apply_files(step, reply["files"])
        reverted = self._unwind_and_enforce(step)
        if "spec_defect" in reply and isinstance(reply["spec_defect"], dict):
            return self._spec_defect(reply["spec_defect"], step)
        bad = sorted(set(refused + reverted))
        if bad:
            self.log.append(f"enforce:{step}", status="done", reverted=bad)
        st.feedback = f"These changes were refused or reverted because the {step} may not make them: {bad}\n" if bad else ""
        if step == "test-author":
            self._enter("tests-pass" if st.frozen else "red-check")
        else:
            self._enter("commit-build")
        self._save(f"{step} submitted")
        return self.advance()

    def run(self, router) -> dict:
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
        dirty = [p for _, p in _status(self.root)
                 if p.startswith(("specs/", "personas/", ".sparkwright/config.yaml")) and not p.startswith(ENGINE_DIRTY_OK)]
        if dirty:
            raise BuildError(f"commit or stash spec and config changes before building: {dirty[:5]}")
        status = checks.run(self.root, write_ledger=False).nodes[self.task].status
        if status not in ("approved", "building") and not (self.restart and status == "blocked"):
            raise BuildError(f"task {self.task} is '{status}'; it must be approved before it is built "
                             f"(`sparkwright approve {self.task} --as <name>`)")
        self._count_change_request_round()
        if self.state.phase == "blocked":
            return
        base = _git(self.root, "rev-parse", "HEAD").strip()
        branch = f"sparkwright/{self.task}" + ("" if self.run_no == 1 else f"-{self.run_no}")
        ws = self.root / ".sparkwright" / "worktrees" / (self.task if self.run_no == 1 else f"{self.task}-{self.run_no}")
        if ws.exists():
            _git(self.root, "worktree", "remove", "--force", str(ws), check=False)
        _git(self.root, "branch", "-D", branch, check=False)
        _git(self.root, "worktree", "add", "-q", "-b", branch, str(ws), base)
        self.state.base, self.state.workspace, self.state.branch = base, str(ws), branch
        base_run = run_checks(ws, {"test": self.test_cmd}, env=self.env)[0]
        if not base_run.ok and not _runner_broken(base_run.output):
            self._block("The test suite already fails before this task starts; fix it first, because the red check "
                        "cannot tell new failures from old ones.\n" + base_run.output[-1500:])
            return
        self._event("building", f"build started on {branch}")
        self._enter("test-author")
        self._save("workspace ready")

    def _count_change_request_round(self) -> None:
        """S3.6: a rebuild after an applied change request counts as a round; more than 2 blocks the CR."""
        evs, _ = events_mod.read(self.root)
        last = next((e for e in reversed(evs) if e.id == self.task and e.event == "changed"), None)
        m = re.match(r"^(CR\d+)", (last.reason or "")) if last else None
        if not m:
            return
        cr = ids.canonical(m.group(1))
        sf = next((f for f in self.repo.files if f.id == cr), None)
        if sf is None or sf.status != "applied":
            return
        path = self.root / sf.path
        text = path.read_text(encoding="utf-8")
        rounds = int(sf.meta.get("rounds", 0) or 0) + 1
        text = re.sub(r"^rounds:\s*\d+\s*$", f"rounds: {rounds}", text, count=1, flags=re.M)
        if rounds > MAX_ROUNDS:
            text = re.sub(r"^status:\s*\S+\s*$", "status: blocked", text, count=1, flags=re.M)
            path.write_text(text, encoding="utf-8")
            self._block(f"{cr} has been rebuilt {MAX_ROUNDS} times; a human must apply or reject it")
            return
        path.write_text(text, encoding="utf-8")

    def _step_red_check(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        new_tests = [f for f in _changed(ws) if _match(f, self.test_globs) and (ws / f).is_file()]
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
            res = run_checks(ws, {"test": self.test_cmd}, env=self.env)[0]
            if res.ok:
                problem = "The new tests pass before any implementation exists, so they do not test the task."
            elif _runner_broken(res.output):
                problem = ("The test command failed before running any test (collection or discovery error), so the "
                           "red check cannot tell whether the tests are meaningful. Output:\n" + res.output[-1500:])
        if problem:
            st.rounds["red"] += 1
            self.log.append("red-check", status="failed", reason=problem[:500])
            if st.rounds["red"] > MAX_ROUNDS:
                self._block(f"Red check failed after {MAX_ROUNDS} rounds: {problem}")
                return
            st.feedback = problem
            self._enter("test-author")
            self._save("red check failed")
            return
        st.red_commit = _commit(ws, self.task, "test-author", "tests (red)", new_tests)
        self.log.append("red-check", status="done", tests=new_tests)
        st.feedback = ""
        self._enter("builder")
        self._save("tests red and committed")

    def _step_tests_pass(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        res = run_checks(ws, {"test": self.test_cmd}, env=self.env)[0]
        if not res.ok:
            st.rounds["saboteur"] += 1
            if st.rounds["saboteur"] > MAX_ROUNDS:
                self._block("Strengthened tests fail against the frozen implementation after 2 rounds")
                return
            st.feedback = "Your new tests fail against the implementation, which is frozen:\n" + res.output[-2000:]
            self._enter("test-author")
            self._save("strengthened tests fail")
            return
        _commit(ws, self.task, "test-author", "strengthen tests", [f for f in _changed(ws) if _match(f, self.test_globs)])
        st.frozen, st.feedback = False, ""
        self._enter("saboteur")
        self._save("tests strengthened")

    def _step_commit_build(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        changed = _changed(ws)
        if not changed:
            st.rounds["builder"] += 1
            if st.rounds["builder"] > MAX_ROUNDS:
                self._block("Builder made no changes")
                return
            st.feedback = "You made no changes. Implement the task."
            self._enter("builder")
            self._save("no builder changes")
            return
        _commit(ws, self.task, "builder", "implement", changed)
        self._enter("verify")
        self._save("build committed")

    def _builder_retry(self, why: str, output: str) -> None:
        st = self.state
        st.rounds["builder"] += 1
        if st.rounds["builder"] > MAX_ROUNDS:
            self._block(f"{why} after {MAX_ROUNDS} builder rounds")
            return
        st.feedback = f"{why}:\n{output[-3000:]}"
        self._enter("builder")
        self._save(why)

    def _step_verify(self) -> None:
        ws = Path(self.state.workspace)
        results = run_checks(ws, self.cfg.get("checks") or {}, env=self.env)
        self.log.append("verify", status="done", results=[{"name": r.name, "ok": r.ok} for r in results])
        failed = [r for r in results if not r.ok]
        if failed:
            self._builder_retry("Project checks failed", "\n\n".join(f"[{r.name}] {r.output}" for r in failed))
            return
        self._enter("library")
        self._save("verify green")

    def _step_library(self) -> None:
        ws = Path(self.state.workspace)
        changed = _git(ws, "diff", "--name-only", self.state.base, "HEAD").splitlines()
        src = [f for f in changed if f.endswith(".py") and not _match(f, self.test_globs) and (ws / f).is_file()]
        issues = libcheck.check(ws, src, python=self.cfg.get("python") or __import__("sys").executable, env=self.env)
        self.log.append("library", status="done", issues=[i.__dict__ for i in issues])
        if issues:
            self._builder_retry("Library Checker found problems", "\n".join(f"{i.file}:{i.line}: {i.message}" for i in issues))
            return
        self._enter("saboteur")
        self._save("library check passed")

    def _mutation(self) -> tuple[mutate.MutationReport, float]:
        mcfg = self.cfg.get("mutation") or {}
        rep = mutate.run(Path(self.state.workspace), self.state.base, self.test_cmd,
                         float(mcfg.get("time_budget_s", 300)), test_globs=self.test_globs, env=self.env)
        return rep, float(mcfg.get("min", 0.8))

    def _step_saboteur(self) -> None:
        st = self.state
        rep, minimum = self._mutation()
        self.log.append("saboteur", status="done", score=rep.score, total=rep.total, killed=rep.killed, partial=rep.partial,
                        survivors=[f"{m.file}:{m.line} {m.description}" for m in rep.survivors][:50], message=rep.message)
        if not rep.baseline_ok:
            self._builder_retry("Tests do not pass", rep.message)
            return
        if rep.total == 0 and rep.changed_source:
            st.result["mutation_note"] = "no mutants could be generated; mutation evidence is absent"
        elif rep.score < minimum:
            st.rounds["saboteur"] += 1
            if st.rounds["saboteur"] > MAX_ROUNDS:
                self._block(f"Mutation score {rep.score:.2f} still below {minimum:.2f} after {MAX_ROUNDS} rounds")
                return
            st.frozen = True
            st.feedback = (f"Mutation score {rep.score:.2f} is below {minimum:.2f}. These planted bugs were NOT caught; "
                           "add tests that fail on each:\n" + "\n".join(f"- {m.file}:{m.line} {m.description}" for m in rep.survivors[:30]))
            self._enter("test-author")
            self._save("saboteur: weak tests")
            return
        st.result["mutation_score"] = round(rep.score, 3)
        st.result["mutation_partial"] = rep.partial
        self._enter("lock-tests")
        self._save("saboteur passed")

    def _step_lock_tests(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        locked_before = self._locked_at(st.base)
        tests = [f for f in _git(ws, "diff", "--name-only", st.base, "HEAD").splitlines()
                 if _match(f, self.test_globs) and f not in locked_before]
        when = approvals_mod.now()
        entries = []
        for f in tests:
            h = _blob_hash(ws, "HEAD", f)
            if h:
                entries.append(Approval(f"test:{f}", h, "sparkwright-runner", "runner", None, when))
        approvals_mod.append(ws, entries)
        _commit(ws, self.task, "runner", "lock tests", ["specs/approvals.jsonl"])
        self._enter("code-reviewer")
        self._save("tests locked")

    def _write_code_review(self, findings: list[Finding]) -> None:
        ws = Path(self.state.workspace)
        n = sum(self.state.rounds.values())
        rel = f"specs/reviews/{date.today().isoformat()}-{self.task.lower()}-code-{self.run_no}-{n}.md"
        digits = "".join(ch for ch in self.task if ch.isdigit())
        rows = "\n".join(f"| F{i} | {f.severity} | {', '.join(f.ids) or '—'} | {_cell(f.finding)} | {_cell(f.fix)} | open |"
                         for i, f in enumerate(findings, 1)) or "| — | — | — | No findings | — | — |"
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        (ws / rel).write_text(
            f"---\nid: R{digits}{self.run_no}{n:02d}\ntitle: Code review of {self.task}\ntype: review\nstatus: in-review\n---\n\n"
            "| ID | Severity | Requirements | Finding | Suggested fix | Decision |\n| --- | --- | --- | --- | --- | --- |\n"
            f"{rows}\n", encoding="utf-8")
        _commit(ws, self.task, "runner", "code review", [rel])

    # ---- final gate
    def _role_commits(self) -> list[tuple[str, str, str]]:
        """(sha, subject, role) of commits on the branch since base, oldest first."""
        out = _git(Path(self.state.workspace), "log", "--reverse", "--format=%H%x1f%s%x1f%B%x1e", f"{self.state.base}..HEAD")
        res = []
        for rec in out.split("\x1e"):
            if not rec.strip():
                continue
            sha, subject, body = (rec.strip("\n").split("\x1f") + ["", ""])[:3]
            m = re.search(r"^SparkWright-Role:\s*(\S+)", body, re.M)
            res.append((sha, subject, m.group(1) if m else ""))
        return res

    def _step_finish(self) -> None:
        st, ws = self.state, Path(self.state.workspace)
        problems = []
        if _changed(ws):
            problems.append("workspace has uncommitted changes")
        commits = self._role_commits()
        roles = [(subj.split(": ", 1)[-1], role) for _, subj, role in commits]
        for need in [("tests (red)", "test-author"), ("implement", "builder"), ("lock tests", "runner"), ("code review", "runner")]:
            if need not in roles:
                problems.append(f"missing '{need[0]}' commit by {need[1]}")
        red = next((sha for sha, subj, role in commits if subj.endswith(": tests (red)") and role == "test-author"), None)
        if red:
            tmp = Path(tempfile.mkdtemp(prefix="sparkwright-red-"))
            try:
                _git(self.root, "worktree", "add", "-q", "--detach", str(tmp / "w"), red)
                if run_checks(tmp / "w", {"test": self.test_cmd}, env=self.env)[0].ok:
                    problems.append("the red tests do not fail at their own commit")
            finally:
                _git(self.root, "worktree", "remove", "--force", str(tmp / "w"), check=False)
                shutil.rmtree(tmp, ignore_errors=True)
        failed = [r.name for r in run_checks(ws, self.cfg.get("checks") or {}, env=self.env) if not r.ok]
        if failed:
            problems.append(f"checks fail at the branch tip: {failed}")
        rep, minimum = self._mutation()
        if rep.total and rep.score < minimum:
            problems.append(f"mutation score {rep.score:.2f} below {minimum:.2f} at the branch tip")
        locked = self._locked_at("HEAD")
        for f in [f for f in _git(ws, "diff", "--name-only", st.base, "HEAD").splitlines() if _match(f, self.test_globs)]:
            if (ws / f).is_file() and locked.get(f) != _blob_hash(ws, "HEAD", f):
                problems.append(f"test {f} is not locked at its final content")
        if problems:
            self._block("Final gate failed: " + "; ".join(problems))
            return
        st.result["mutation_score"] = round(rep.score, 3) if rep.total else None
        gate = f"Gate: red=confirmed checks=green mutation={st.result['mutation_score']}\n"
        _commit(ws, self.task, "runner", "ready", [], extra=gate, allow_empty=True)
        self._enter("ready")
        self._save("ready for human merge")

    def _ready_marker_ok(self) -> bool:
        if not self.state.branch:
            return False
        body = _git(self.root, "log", "-1", "--format=%s%x1f%B", self.state.branch, check=False)
        subject, _, rest = body.partition("\x1f")
        return subject.strip() == f"{self.task}: ready" and "SparkWright-Role: runner" in rest


BROKEN_RUNNER = [
    r"Start directory is not importable", r"\bRan 0 tests\b", r"\bno tests ran\b",
    r"ERROR: file or directory not found", r"error: unrecognized arguments", r"No module named (pytest|unittest)\b",
    r"collected 0 items",
]


def _runner_broken(output: str) -> bool:
    return any(re.search(p, output, re.I) for p in BROKEN_RUNNER)


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _parse_reply(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return {"status": "ok"}
    try:
        data = json.loads(text[start:end + 1])
        return data if isinstance(data, dict) else {"status": "ok"}
    except json.JSONDecodeError:
        return {"status": "ok"}
