"""Offline checks behind `sparkwright check` (SYSTEM S1.4, S2.3, S2.4, S2.6, S6.5, S6.8)."""
from __future__ import annotations

import fnmatch
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import annotations, approvals as approvals_mod, config as config_mod, events as events_mod, gitlog, ids, ledger, status as status_mod, store

APPROVED_LIKE = {"approved", "building", "done"}
RUNNER_PATHS = ["specs/approvals.jsonl", "specs/events.jsonl", "specs/reviews/*"]
DRIFT_EXCLUDE_DEFAULT = ["specs/**", ".sparkwright/**", "*.md", ".gitignore", ".gitattributes", "LICENSE", "NOTICE", "personas/**", "templates/**"]


@dataclass
class Finding:
    severity: str  # error | warning | info
    code: str
    message: str
    id: str | None = None
    file: str | None = None
    line: int | None = None

    def location(self) -> str:
        if self.file and self.line:
            return f"{self.file}:{self.line}"
        return self.file or ""


@dataclass
class Result:
    findings: list[Finding]
    nodes: dict[str, ledger.Node]
    config: dict
    commits: list[gitlog.Commit] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def counts(self) -> dict[str, int]:
        out = {"error": 0, "warning": 0, "info": 0}
        for f in self.findings:
            out[f.severity] += 1
        return out

    def to_dict(self) -> dict:
        return {"counts": self.counts(), "findings": [asdict(f) for f in self.findings]}


def _glob_match(path: str, globs: list[str]) -> bool:
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return True
        if g.endswith("/**") and (path == g[:-3] or path.startswith(g[:-2])):
            return True
    return False


def file_hash(path: Path) -> str:
    """SHA-256 of file content with CRLF normalised to LF, so hashes match across platforms."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def evidence_hash(path: Path) -> str:
    """Hash of an evidence file's body (front matter excluded, so status changes don't break the lock)."""
    from .frontmatter import split
    from .grammar import text_hash
    _, body, _ = split(path.read_text(encoding="utf-8-sig"))
    return text_hash(body)


def approved_change_requests(repo) -> set[str]:
    return {sf.id for sf in repo.files
            if sf.id and ids.kind_of(sf.id) == "change" and sf.status in ("approved", "applied")}


def run(root: Path | str, write_ledger: bool = True) -> Result:
    root = Path(root).resolve()
    findings: list[Finding] = []
    add = lambda sev, code, msg, **kw: findings.append(Finding(sev, code, msg, **kw))  # noqa: E731

    cfg, cfg_errors = config_mod.load(root)
    for e in cfg_errors:
        add("error", "config.invalid", e, file=config_mod.CONFIG_PATH)

    repo = store.load(root)
    if not repo.files:
        add("error", "store.empty", "no spec files found under specs/")

    for sf in repo.files:
        for iss in sf.issues:
            add("error", iss.code, iss.message, id=iss.id, file=sf.path, line=iss.line)
    for rid, f, line in repo.duplicates:
        first = repo.requirements[rid]
        add("error", "grammar.duplicate-id", f"{rid} already defined at {first.file}:{first.line}", id=rid, file=f, line=line)

    entries, appr_errors = approvals_mod.read(root)
    for e in appr_errors:
        add("error", "approval.invalid", e, file=approvals_mod.APPROVALS_PATH)
    latest = approvals_mod.latest(entries)

    renames = rename_map(repo)
    rn = lambda i: renames.get(i, i)  # noqa: E731
    latest = {rn(k): v for k, v in latest.items()}
    evs, ev_errors = events_mod.read(root)
    for e in ev_errors:
        add("error", "events.invalid", e, file=events_mod.EVENTS_PATH)
    for e in evs:
        e.id = rn(e.id)
    derived = status_mod.derive(repo, latest, evs)
    for rid, appr in latest.items():
        if rid in repo.requirements and appr.hash == repo.requirements[rid].hash \
                and not approvals_mod.risk_matches(appr, repo, rid):
            add("warning", "approval.risk-changed",
                f"{rid} was approved at risk '{appr.risk}' but its file now says "
                f"'{approvals_mod.risk_of(repo, rid)}'; a human must re-approve it", id=rid)
    tests = {}
    for k, v in annotations.scan(root, cfg["test_globs"]).items():
        tests.setdefault(rn(k), []).extend(v)
    commits: list[gitlog.Commit] = []
    if not gitlog.git_available():
        add("warning", "git.unavailable", "git is not installed; commit, drift and role checks were skipped")
    elif not gitlog.is_repo(root):
        add("info", "git.not-a-repo", "not a git repository; commit, drift and role checks were skipped")
    else:
        try:
            commits = gitlog.commits(root, cfg.get("baseline"))
        except gitlog.GitError as exc:
            add("error", "git.log-failed", str(exc))
    for c in commits:
        c.tasks = [rn(t) for t in c.tasks]
    nodes = ledger.build(repo, latest, tests, commits)
    built = {t for c in commits if c.role == "runner" and c.subject.strip().endswith(": ready") for t in c.tasks}
    for rid, st in derived.items():
        if st == "building" and rid in built:
            st = derived[rid] = "done"  # its build commit is on this branch (S2.8, merge detection)
        nodes[rid].status = st

    # --- references (S1.2, S1.4) ---
    present_kinds = {r.kind for r in repo.requirements.values()}
    for rid, r in repo.requirements.items():
        loc = dict(id=rid, file=r.file, line=r.line)
        allowed = ids.PARENT_KINDS.get(r.kind)
        if allowed is None:
            add("error", "ref.not-a-requirement-kind", f"{rid} is a {r.kind} ID and cannot be a requirement line", **loc)
            continue
        if not r.refs and r.kind != "assumption":
            add("error", "ref.empty", f"{rid} cites no parent", **loc)
        for ref in r.refs:
            rk = ids.kind_of(ref)
            if rk is None:
                add("error", "ref.invalid", f"{rid} cites '{ref}', which is not a valid ID", **loc)
            elif ref not in nodes:
                add("error", "ref.unknown", f"{rid} cites {ref}, which is not defined", **loc)
            elif rk not in allowed:
                add("error", "ref.wrong-level", f"{rid} ({r.kind}) cites {ref} ({rk}); expected {', '.join(allowed)}", **loc)
            elif r.kind == "task" and not rid.startswith(ref + ".T"):
                add("error", "ref.task-scope", f"task {rid} must cite its own component, not {ref}", **loc)
        if r.kind == "vision":
            backing = [x for x in r.refs if (x in repo.evidence and not repo.evidence[x].simulated) or ids.kind_of(x) == "assumption"]
            if not backing:
                add("error", "vision.no-evidence", f"{rid} cites no real evidence or assumption", **loc)

    # --- coverage (S2.3) ---
    not_started: set[str] = set()
    for rid, r in repo.requirements.items():
        child_kind = ids.CHILD_KIND.get(r.kind)
        if not child_kind:
            continue
        if child_kind not in present_kinds:
            not_started.add(child_kind)
            continue
        kids = [c for c in nodes[rid].children if nodes[c].kind == child_kind]
        if not kids:
            add("error", "coverage.no-children", f"{rid} has no {child_kind} requirements", id=rid, file=r.file, line=r.line)
    for k in sorted(not_started, key=ids.PYRAMID.index):
        add("info", "coverage.level-not-started", f"no {k} requirements yet; coverage below that level is not checked")
    for rid, r in repo.requirements.items():
        if r.kind == "task" and derived[rid] == "done" and not nodes[rid].tests:
            add("error", "task.no-test", f"task {rid} is {derived[rid]} but no test references it", id=rid, file=r.file, line=r.line)

    # --- approvals and locks (S2.4) ---
    for rid, r in repo.requirements.items():
        status = repo.status_of(rid)
        appr = latest.get(rid)
        if appr is None:
            if status in APPROVED_LIKE:
                add("error", "approval.unconfirmed", f"{rid} is marked {status} but has no approval record", id=rid, file=r.file, line=r.line)
        elif appr.hash != r.hash:
            add("error", "approval.hash-mismatch", f"{rid} changed after approval by {appr.approver}; needs a change request", id=rid, file=r.file, line=r.line)
    for eid, ev in repo.evidence.items():
        if ev.status in APPROVED_LIKE | {"confirmed"} and eid not in latest:
            add("error", "approval.unconfirmed", f"evidence {eid} is marked {ev.status} but has no approval record", id=eid, file=ev.file)
        elif eid in latest:
            current = evidence_hash(root / ev.file)
            if current != latest[eid].hash:
                add("error", "approval.hash-mismatch", f"evidence {eid} changed after approval by {latest[eid].approver}", id=eid, file=ev.file)
    valid_crs = approved_change_requests(repo)
    for e in entries:
        if e.change_request and e.change_request not in valid_crs:
            add("error", "approval.unknown-change-request",
                f"approval of {e.id} cites {e.change_request}, which is not an approved change request in specs/changes/", id=e.id)
    for aid, appr in latest.items():
        if aid.startswith("test:"):
            path = root / aid[5:]
            if not path.is_file():
                add("error", "approval.locked-test-missing", f"locked test {aid[5:]} is missing", id=aid)
            elif file_hash(path) != appr.hash:
                add("error", "approval.locked-test-changed", f"locked test {aid[5:]} changed after it was locked", id=aid, file=aid[5:])
        elif aid not in repo.requirements and ids.kind_of(aid) is not None and aid not in repo.evidence:
            add("warning", "approval.orphan", f"approval exists for {aid}, which is no longer defined", id=aid)

    # --- commits: trailers, drift, roles (S2.3, S2.6, S6.5) ---
    mode = cfg.get("trailers", "required")
    drift_exclude = cfg.get("drift_exclude", DRIFT_EXCLUDE_DEFAULT)
    task_ids = {rid for rid, r in repo.requirements.items() if r.kind == "task"}
    tracked_globs = [g for rid in task_ids if derived[rid] in APPROVED_LIKE for g in nodes[rid].files]
    lock_idx = _lock_positions(root, cfg, commits, entries)
    commit_pos = {c.sha: i for i, c in enumerate(commits)}
    for c in commits:
        short = c.sha[:12]
        spec_only = bool(c.files) and all(_glob_match(f, drift_exclude) for f in c.files)
        if mode != "off":
            if not c.tasks and not spec_only:
                add("error" if mode == "required" else "warning", "commit.no-trailer", f"commit {short} '{c.subject}' has no SparkWright-Task trailer")
            for t in c.tasks:
                if t not in task_ids:
                    add("error", "commit.unknown-task", f"commit {short} cites task {t}, which is not defined", id=t)
        if tracked_globs:
            for path in c.files:
                if _glob_match(path, drift_exclude):
                    continue
                if not _glob_match(path, tracked_globs):
                    add("error" if mode == "required" else "warning", "drift.untracked-file",
                        f"commit {short} changes {path}, which no approved task declares", file=path)
        if c.role and c.role != "human":
            for path in c.files:
                if path not in c.body:
                    add("error", "commit.unlisted-file", f"commit {short} by role '{c.role}' changes {path} without listing it in the message", file=path)
            if c.role == "runner":  # the Runner may only append logs and write review files
                for path in c.files:
                    if not _glob_match(path, RUNNER_PATHS):
                        add("error", "role.path-violation", f"commit {short} by role 'runner' changes {path}; the runner may only change {RUNNER_PATHS}", file=path)
                continue
            forbidden = list(cfg.get("protected", {}).get(c.role, [])) + list(cfg.get("always_protected", []))
            for path in c.files:
                if _glob_match(path, forbidden) or (path in lock_idx and lock_idx[path] < commit_pos[c.sha]):
                    add("error", "role.path-violation", f"commit {short} by role '{c.role}' changes protected path {path}", file=path)

    if gitlog.is_repo(root) and not any(f.code == "git.log-failed" for f in findings):
        _verify_approvals(root, cfg, add, {c.sha: c.role for c in commits})
        for rel in (approvals_mod.APPROVALS_PATH, events_mod.EVENTS_PATH):
            _append_only(root, cfg.get("baseline"), rel, add)

    findings.sort(key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f.severity], f.file or "", f.line or 0, f.code))
    if write_ledger:
        ledger.write(root, nodes)
    return Result(findings, nodes, cfg, commits)


def rename_map(repo) -> dict[str, str]:
    """OLD -> NEW from approved or applied change requests (S2.9, D004)."""
    out: dict[str, str] = {}
    for sf in repo.files:
        if sf.id and ids.kind_of(sf.id) == "change" and sf.status in ("approved", "applied"):
            for old, new in (sf.meta.get("renames") or {}).items():
                out[ids.canonical(str(old))] = ids.canonical(str(new))
    return out


def _lock_positions(root: Path, cfg: dict, commits: list, entries: list) -> dict[str, int]:
    """Test path -> position in `commits` of the commit that locked it (-1: locked at or before the baseline).

    Uses git history, not timestamps, so the order is exact. Uncommitted locks are ignored here.
    """
    import json as _json
    pos = {c.sha: i for i, c in enumerate(commits)}
    out: dict[str, int] = {}
    try:
        added = gitlog.added_lines(root, approvals_mod.APPROVALS_PATH, cfg.get("baseline")) if commits else []
    except gitlog.GitError:
        added = []
    after_baseline = set()
    for line in added:
        try:
            d = _json.loads(line.text)
        except _json.JSONDecodeError:
            continue
        aid = str(d.get("id", ""))
        if aid.startswith("test:") and line.sha in pos:
            out.setdefault(aid[5:], pos[line.sha])
            after_baseline.add(aid[5:])
    head = gitlog.show(root, "HEAD", approvals_mod.APPROVALS_PATH) if commits else None
    committed = set()
    for text in (head or "").splitlines():
        try:
            aid = str(_json.loads(text).get("id", ""))
        except _json.JSONDecodeError:
            continue
        if aid.startswith("test:"):
            committed.add(aid[5:])
    for path in committed - after_baseline:
        out[path] = -1
    return out


def _verify_approvals(root: Path, cfg: dict, add, roles: dict | None = None) -> None:
    """S6.3: committed human approval lines must come from allowlisted authors."""
    import json
    approvers = {}
    for a in cfg.get("approvers") or []:
        if isinstance(a, dict) and a.get("email"):
            approvers.setdefault(str(a["email"]).lower(), set()).add(str(a.get("name", "")).lower())
    try:
        added = gitlog.added_lines(root, approvals_mod.APPROVALS_PATH, cfg.get("baseline"))
    except gitlog.GitError as exc:
        add("error", "git.log-failed", str(exc))
        return
    committed = set()
    for line in added:
        committed.add(line.text)
        try:
            d = json.loads(line.text)
        except json.JSONDecodeError:
            continue
        role, who = d.get("role"), str(d.get("approver", "")).lower()
        commit_role = (roles or {}).get(line.sha)
        if commit_role and commit_role != "human" and (role != "runner" or not str(d.get("id", "")).startswith("test:")):
            add("error", "approval.role-not-allowed",
                f"commit {line.sha[:12]} by role '{commit_role}' added a non-test-lock approval for {d.get('id')}", id=d.get("id"))
            continue
        if role == "runner":
            if not str(d.get("id", "")).startswith("test:"):
                add("error", "approval.role-not-allowed", f"runner may only lock tests, not approve {d.get('id')} (commit {line.sha[:12]})", id=d.get("id"))
            continue
        names = approvers.get(line.author_email)
        if names is None:
            add("error", "approval.unverified-approver",
                f"approval of {d.get('id')} was committed by {line.author_email}, who is not in `approvers`", id=d.get("id"))
        elif who not in names:
            add("error", "approval.unverified-approver",
                f"approval of {d.get('id')} names '{d.get('approver')}' but was committed by {line.author_email}", id=d.get("id"))
        elif cfg.get("require_signed") and not gitlog.verify_commit(root, line.sha):
            add("error", "approval.unsigned", f"approval of {d.get('id')} is in unsigned commit {line.sha[:12]}", id=d.get("id"))
    head = gitlog.show(root, "HEAD", approvals_mod.APPROVALS_PATH) or ""
    path = root / approvals_mod.APPROVALS_PATH
    if path.is_file():
        head_lines = set(head.splitlines())
        for text in path.read_text(encoding="utf-8").splitlines():
            if text.strip() and text not in head_lines:
                add("warning", "approval.pending", f"uncommitted approval line will be verified once committed: {text[:80]}")


def _append_only(root: Path, baseline: str | None, rel: str, add) -> None:
    """S6.9: content at the baseline and at HEAD must be a prefix of the current file."""
    path = root / rel
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    for rev in [r for r in (baseline, "HEAD") if r]:
        old = gitlog.show(root, rev, rel)
        if old and not current.startswith(old):
            add("error", "log.not-append-only", f"{rel} was edited or truncated since {rev[:12]}; it is append-only", file=rel)
            return
