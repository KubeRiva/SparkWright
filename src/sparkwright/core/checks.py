"""Offline checks behind `sparkwright check` (SYSTEM S1.4, S2.3, S2.4, S2.6, S6.5, S6.8)."""
from __future__ import annotations

import re

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
    from .globs import match
    return match(path, globs)


def file_hash(path: Path) -> str:
    """SHA-256 of file content with CRLF normalised to LF, so hashes match across platforms."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def evidence_hash(path: Path) -> str:
    """Hash of an evidence file's body (front matter excluded, so status changes don't break the lock)."""
    from .frontmatter import split
    from .grammar import text_hash
    _, body, _ = split(path.read_text(encoding="utf-8-sig"))
    return text_hash(body)


SIGNIFICANT_META = ("simulated", "consent", "source", "target", "renames", "risk")


def evidence_hash2(path: Path) -> str:
    """D008: body plus the front-matter fields that change meaning (`simulated`, `consent`, `source`, `target`,
    `renames`, `risk`); `status` stays out so workflow moves don't break the lock."""
    import json
    from .frontmatter import split
    from .grammar import text_hash
    meta, body, _ = split(path.read_text(encoding="utf-8-sig"))
    sig = {k: (meta or {}).get(k) for k in SIGNIFICANT_META if (meta or {}).get(k) is not None}
    return text_hash(body + "\nmeta:" + json.dumps(sig, sort_keys=True, default=str))


def file_approval_holds(root: Path, rel: str, appr) -> bool:
    if appr is None or appr.hash != evidence_hash(root / rel):
        return False
    return appr.hash2 is None or appr.hash2 == evidence_hash2(root / rel)


def approved_change_requests(repo, latest: dict | None = None, root: Path | None = None) -> set[str]:
    """Change requests with status approved/applied AND (when `latest` is given) a human approval that still
    matches the file (D008: a status line alone never makes a change request count)."""
    out = set()
    for sf in repo.files:
        if sf.id and ids.kind_of(sf.id) == "change" and sf.status in ("approved", "applied"):
            if latest is None or file_approval_holds(Path(root), sf.path, latest.get(sf.id)):
                out.add(sf.id)
    return out


def run(root: Path | str, write_ledger: bool = True) -> Result:
    root = Path(root).resolve()
    findings: list[Finding] = []
    add = lambda sev, code, msg, **kw: findings.append(Finding(sev, code, msg, **kw))  # noqa: E731

    cfg, cfg_errors = config_mod.load(root)
    for e in cfg_errors:
        add("error", "config.invalid", e, file=config_mod.CONFIG_PATH)

    for msg in weakened_config(cfg):
        add("warning", "config.weakened", msg, file=config_mod.CONFIG_PATH)
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

    valid_crs = approved_change_requests(repo, latest, root)
    for sf in repo.files:
        if sf.id and ids.kind_of(sf.id) == "change" and sf.status in ("approved", "applied") and sf.id not in valid_crs:
            add("error", "approval.unconfirmed", f"change request {sf.id} is marked {sf.status} but has no matching "
                f"human approval; it is ignored until a human approves it", id=sf.id, file=sf.path)
    for sf in repo.files:  # D008: a decision record counts as approved only with a matching human approval
        if sf.id and sf.meta.get("type") == "decision" and sf.status == "approved" \
                and not file_approval_holds(root, sf.path, latest.get(sf.id)):
            add("warning", "approval.unconfirmed-decision", f"decision {sf.id} is marked approved but has no matching human "
                f"approval (`sparkwright approve {sf.id} --as <name>`)", id=sf.id, file=sf.path)
    renames = rename_map(repo, valid_crs)
    rn = lambda i: renames.get(i, i)  # noqa: E731
    latest = {rn(k): v for k, v in latest.items()}
    evs, ev_errors = events_mod.read(root)
    for e in ev_errors:
        add("error", "events.invalid", e, file=events_mod.EVENTS_PATH)
    for e in evs:
        e.id = rn(e.id)
    derived = status_mod.derive(repo, latest, evs)
    for rid, appr in latest.items():
        if rid in repo.requirements and approvals_mod.matches(appr, repo.requirements[rid]) \
                and not approvals_mod.risk_matches(appr, repo, rid):
            add("warning", "approval.risk-changed",
                f"{rid} was approved at risk '{appr.risk}' but its file now says "
                f"'{approvals_mod.risk_of(repo, rid)}'; a human must re-approve it", id=rid)
    tests = {}
    for k, v in annotations.scan(root, cfg["test_globs"]).items():
        tests.setdefault(rn(k), []).extend(v)
    commits: list[gitlog.Commit] = []
    gitlog.clear_cache()
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
    legacy: list[str] = []
    for rid, r in repo.requirements.items():
        status = repo.status_of(rid)
        appr = latest.get(rid)
        if appr is None:
            if status in APPROVED_LIKE:
                add("error", "approval.unconfirmed", f"{rid} is marked {status} but has no approval record", id=rid, file=r.file, line=r.line)
        elif not approvals_mod.matches(appr, r):
            if derived.get(rid) in ("in-review", "changed"):  # S3.10: an applied change request is being worked through
                add("warning", "approval.change-in-progress", f"{rid} is being changed under an applied change request; "
                    f"review it and re-approve with --cr", id=rid, file=r.file, line=r.line)
            else:
                what = "its text" if appr.hash != r.hash else "its parent links or acceptance criteria"
                add("error", "approval.hash-mismatch", f"{rid}: {what} changed after approval by {appr.approver}; needs a change request", id=rid, file=r.file, line=r.line)
        elif appr.hash2 is None:
            legacy.append(rid)
    if legacy:
        add("info", "approval.legacy-lock", f"{len(legacy)} approval(s) predate locking of parent links and acceptance criteria "
            f"(D007): {', '.join(legacy[:6])}{', ...' if len(legacy) > 6 else ''}. `sparkwright approve <ids>` refreshes "
            f"them without a change request")
    for eid, ev in repo.evidence.items():
        if ev.status in APPROVED_LIKE | {"confirmed"} and eid not in latest:
            add("error", "approval.unconfirmed", f"evidence {eid} is marked {ev.status} but has no approval record", id=eid, file=ev.file)
        elif eid in latest:
            if not file_approval_holds(root, ev.file, latest[eid]):
                add("error", "approval.hash-mismatch", f"evidence {eid} changed after approval by {latest[eid].approver}", id=eid, file=ev.file)
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
        elif aid not in repo.requirements and ids.kind_of(aid) is not None and aid not in repo.evidence \
                and aid not in {sf.id for sf in repo.files if sf.id}:
            add("warning", "approval.orphan", f"approval exists for {aid}, which is no longer defined", id=aid)

    # --- commits: trailers, drift, roles (S2.3, S2.6, S6.5) ---
    mode = cfg.get("trailers", "required")
    drift_exclude = cfg.get("drift_exclude", DRIFT_EXCLUDE_DEFAULT)
    task_ids = {rid for rid, r in repo.requirements.items() if r.kind == "task"}
    tracked_globs = [g for rid in task_ids if derived[rid] in APPROVED_LIKE for g in nodes[rid].files]
    lock_idx = _lock_positions(root, cfg, commits, entries)
    approver_emails = {str(a["email"]).lower() for a in cfg.get("approvers") or [] if isinstance(a, dict) and a.get("email")}
    sign_mode = signing_mode(cfg)
    signed_after = gitlog.shas_after(root, cfg["signing_from"]) if commits and cfg.get("signing_from") else None
    if commits and cfg.get("signing_from") and signed_after is None:
        add("error", "config.signing-from", f"signing_from {cfg['signing_from']} is not a commit in this repository "
            f"(typo or shallow clone?); signing cannot be checked")
        signed_after = set(c.sha for c in commits)  # fail safe: treat every commit as one that must be signed
    commit_pos = {c.sha: i for i, c in enumerate(commits)}
    no_approver_hits: list[str] = []
    for c in commits:
        short = c.sha[:12]
        if c.role == "conflict":
            add("error", "commit.conflicting-roles", f"commit {short} '{c.subject}' has SparkWright-Role trailers that disagree")
        if not approver_emails and c.role in (None, "", "human") and any(
                _glob_match(f.lower(), [g.lower() for g in cfg.get("always_protected", [])]) for f in c.files):
            no_approver_hits.append(short)
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
                cites_approved = any(derived.get(t) in APPROVED_LIKE | {"changed", "in-review"} for t in c.tasks)
                if cites_approved and _glob_match(path, cfg["test_globs"]):
                    continue  # tests written for an approved task under its trailer are tracked by that task
                if not _glob_match(path, tracked_globs):
                    add("error" if mode == "required" else "warning", "drift.untracked-file",
                        f"commit {short} changes {path}, which no approved task declares", file=path)
        if approver_emails and c.role in (None, "", "human"):  # D007: humans other than approvers may not touch protected files
            prot = [f for f in c.files if _glob_match(f.lower(), [g.lower() for g in cfg.get("always_protected", [])])
                    or (f in lock_idx and lock_idx[f] < commit_pos[c.sha])]
            if prot and c.author_email not in approver_emails:
                add("error", "protected.non-approver", f"commit {short} by {c.author_email} changes protected "
                    f"{', '.join(prot)}; only an approver may change these", file=prot[0])
            elif prot and sign_mode != "off" and signed_after is not None and c.sha in signed_after \
                    and not _signed_by_approver(root, cfg, c.sha, c.author_email):
                add("error" if sign_mode == "all" else "warning", "protected.unsigned",
                    f"commit {short} changes protected {', '.join(prot)} without a signature", file=prot[0])
        if c.role == "runner":  # D007: the runner adds new review files; it never edits or deletes one
            for path, kind in c.status.items():
                if _glob_match(path, ["specs/reviews/*"]) and kind != "A":
                    add("error", "role.review-edit", f"commit {short} by role 'runner' "
                        f"{'deletes' if kind == 'D' else 'edits'} existing review {path}; the runner may only add reviews", file=path)
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
            cr_rebuild = c.role == "test-author" and c.tasks and all(
                getattr(latest.get(t), "change_request", None) in valid_crs for t in c.tasks)  # D009: rebuild after a CR
            for path in c.files:
                relocking = cr_rebuild and path in lock_idx and not _glob_match(path, forbidden)
                if _glob_match(path, forbidden) or (path in lock_idx and lock_idx[path] < commit_pos[c.sha] and not relocking):
                    add("error", "role.path-violation", f"commit {short} by role '{c.role}' changes protected path {path}", file=path)

    if no_approver_hits:
        add("error", "protected.no-approvers", f"{len(no_approver_hits)} commit(s) changed protected files, but no "
            f"`approvers` are configured, so nobody's authorship can be checked; add yourself under `approvers` (S6.5)")
    if gitlog.is_repo(root) and not any(f.code == "git.log-failed" for f in findings):
        _verify_approvals(root, cfg, add, {c.sha: c.role for c in commits}, signed_after,
                          lambda i: _current_risk(repo, rn(ids.canonical(i)) if not i.startswith("test:") else i))
        _append_only(root, cfg.get("baseline"), [approvals_mod.APPROVALS_PATH, events_mod.EVENTS_PATH], add,
                     cfg.get("log_waivers"))
        _review_decisions(root, cfg, add, {c.sha: c.role for c in commits}, approver_emails)

    findings.sort(key=lambda f: ({"error": 0, "warning": 1, "info": 2}[f.severity], f.file or "", f.line or 0, f.code))
    if write_ledger:
        ledger.write(root, nodes)
    return Result(findings, nodes, cfg, commits)


def cr_targets(meta: dict) -> list[str]:
    """Targets of a change request: `target: S1.2` or `target: [S1.2, S2.3]` (D008)."""
    raw = meta.get("target")
    vals = raw if isinstance(raw, list) else [raw] if raw else []
    return [ids.canonical(str(v)) for v in vals if str(v).strip()]


def rename_map(repo, valid: set | None = None) -> dict[str, str]:
    """OLD -> NEW from approved or applied change requests (S2.9, D004); only verified ones when `valid` is given."""
    out: dict[str, str] = {}
    for sf in repo.files:
        if sf.id and ids.kind_of(sf.id) == "change" and sf.status in ("approved", "applied") \
                and (valid is None or sf.id in valid):
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


def weakened_config(cfg: dict) -> list[str]:
    """D009 (S6.8): settings that switch off a protection without touching a named gate."""
    out = []
    for key in ("drift_exclude", "test_globs"):
        if any(str(g).strip() in ("**", "*", "**/*") for g in cfg.get(key) or []):
            out.append(f"`{key}` contains a catch-all glob, which switches off "
                       f"{'drift detection' if key == 'drift_exclude' else 'the line between tests and code'}")
    if cfg.get("trailers") == "off":
        out.append("`trailers: off` stops checking that every commit names its task (V1)")
    if signing_mode(cfg) == "off":
        out.append("`require_signed: false`: approvals rest on git author emails alone, which anyone can set")
    if (cfg.get("mutation") or {}).get("allow_not_run"):
        out.append("`mutation.allow_not_run: true`: tasks may be locked without mutation testing")
    return out


def signing_mode(cfg: dict) -> str:
    """D007: "off", "high-risk" (default) or "all"."""
    v = cfg.get("require_signed")
    if v in (None, False, "off", "false", "no"):
        return "off"
    if v in (True, "all", "true", "yes", "always"):
        return "all"
    return "high-risk"


def _current_risk(repo, aid: str) -> str | None:
    sf = repo.file_of.get(aid) or next((f for f in repo.files if f.id == aid), None)
    r = sf.meta.get("risk") if sf is not None else None
    return str(r).strip().lower() if r else None


def _verify_approvals(root: Path, cfg: dict, add, roles: dict | None = None, signed_after: set | None = None,
                      risk_now=None) -> None:
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
    unsigned_unenforced: list[str] = []
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
        else:
            mode = signing_mode(cfg)
            try:
                current = risk_now(str(d.get("id", ""))) if risk_now else None
            except Exception:  # noqa: BLE001 - an unknown id is reported elsewhere
                current = None
            high = "high" in (str(d.get("risk") or "").lower(), current or "")
            needs = mode == "all" or (mode == "high-risk" and high)
            if needs and cfg.get("signing_from") and signed_after is not None and line.sha not in signed_after:
                needs = False  # committed before signing was switched on
            if needs and not _signed_by_approver(root, cfg, line.sha, line.author_email):
                if cfg.get("signing_from"):
                    add("error", "approval.unsigned", f"approval of {d.get('id')} is in unsigned commit {line.sha[:12]}", id=d.get("id"))
                else:
                    unsigned_unenforced.append(str(d.get("id")))
    if unsigned_unenforced:
        add("warning", "approval.unsigned-unenforced",
            f"{len(unsigned_unenforced)} high-risk approval(s) are in unsigned commits ({', '.join(sorted(set(unsigned_unenforced))[:5])}"
            f"{', ...' if len(set(unsigned_unenforced)) > 5 else ''}). Set up commit signing (git config commit.gpgsign true), "
            f"then set `signing_from` in .sparkwright/config.yaml to the last commit before signing started (D007)")
    head = gitlog.show(root, "HEAD", approvals_mod.APPROVALS_PATH) or ""
    path = root / approvals_mod.APPROVALS_PATH
    if path.is_file():
        head_lines = set(head.splitlines())
        for text in path.read_text(encoding="utf-8").splitlines():
            if text.strip() and text not in head_lines:
                add("warning", "approval.pending", f"uncommitted approval line will be verified once committed: {text[:80]}")


def _append_only(root: Path, baseline: str | None, rels: list[str], add, waivers: list | None = None) -> None:
    """S6.9 / D007: no commit after the baseline (merges included) may drop or change a line of the logs, and the
    working copy must keep every committed line. Lines are compared as a multiset, so union merges and a
    missing final newline are fine. `log_waivers` (protected config) lists commits an approver excused."""
    from collections import Counter
    waived = {str(w).lower() for w in waivers or []}

    def lines(text: str | None) -> Counter:
        return Counter(x for x in (text or "").splitlines() if x.strip())

    try:
        touching = gitlog.commits_touching(root, baseline, rels)
    except gitlog.GitError:
        touching = []
    specs = {f"{rev}:{rel}" for sha, parents, *_ in touching for rev in [sha, *parents] for rel in rels}
    specs |= {f"HEAD:{rel}" for rel in rels}
    blobs = gitlog.read_blobs(root, sorted(specs))
    for rel in rels:
        bad = None
        for sha, parents, _, _, files in touching:
            if rel not in files or any(sha.lower().startswith(w) for w in waived if len(w) >= 7):
                continue
            now = lines(blobs.get(f"{sha}:{rel}"))
            if any(lines(blobs.get(f"{par}:{rel}")) - now for par in parents):
                bad = sha
                break
        if bad:
            add("error", "log.not-append-only", f"commit {bad[:12]} removed or edited a line of {rel}; it is "
                f"append-only (append a correcting entry instead; an approver can list the commit under "
                f"`log_waivers`)", file=rel)
            continue
        path = root / rel
        current = lines(path.read_text(encoding="utf-8") if path.is_file() else "")
        if lines(blobs.get(f"HEAD:{rel}")) - current:
            add("error", "log.not-append-only", f"{rel} was edited or truncated since HEAD; it is append-only", file=rel)


def _review_table(text: str | None) -> dict[str, tuple[str, str]]:
    """{finding id: (severity, decision)} from a review file's findings table."""
    out: dict[str, tuple[str, str]] = {}
    for line in (text or "").splitlines():
        cells = [c.strip().strip("*`").strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 7 and re.fullmatch(r"F\d+", cells[0]):
            out[cells[0]] = (cells[1].lower(), cells[-1].lower())
    return out


def _review_decisions(root: Path, cfg: dict, add, roles: dict, approver_emails: set) -> None:
    """D007 (S6.11): only an approver, in a human commit, may take a high finding off `open`.

    For each commit touching specs/reviews, compares the findings in the files it changed before and after, so
    renamed IDs, rows that no longer parse, deleted or renamed files and rows removed now and re-added later all
    count as closing. For a merge, a finding counts as closed there only if it was open in every parent (an edit
    made while resolving the merge). A new high finding added already closed counts as closing too.
    """
    try:
        touching = gitlog.commits_touching(root, cfg.get("baseline"), "specs/reviews")
    except gitlog.GitError:
        return
    wanted = []
    for sha, parents, _, _, files in touching:
        for f in files:
            wanted += [f"{rev}:{f}" for rev in [sha, *parents]]
    blobs = gitlog.read_blobs(root, sorted(set(wanted)))

    def state(rev: str, files: list[str]) -> dict:
        out = {}
        for f in files:
            for fid, row in _review_table(blobs.get(f"{rev}:{f}")).items():
                out[(f, fid)] = row
        return out

    for sha, parents, email, body, files in touching:
        after = state(sha, files)
        befores = [state(p, files) for p in parents] or [{}]
        closed = []
        for key in set().union(*befores) | set(after):
            now = after.get(key)
            if all(b.get(key) == ("high", "open") for b in befores) and now != ("high", "open"):
                closed.append(key)
            elif not any(key in b for b in befores) and now and now[0] == "high" and now[1] != "open":
                closed.append(key)
        if not closed:
            continue
        role = gitlog.role_of(body)
        ok = role in (None, "", "human") and (not approver_emails or email in approver_emails)
        if ok and approver_emails and cfg.get("signing_from") and signing_mode(cfg) != "off":
            ok = _signed_by_approver(root, cfg, sha, email)
        if not ok:
            path = sorted(closed)[0][0]
            add("error", "review.decision-not-allowed", f"commit {sha[:12]} closed or removed high finding "
                f"{', '.join(f for _, f in sorted(closed))} in {path}; only an approver may decide a high finding", file=path)


def _signed_by_approver(root: Path, cfg: dict, sha: str, email: str) -> bool:
    """A good signature; when the approver lists `signing_key`, by that key (D007)."""
    status, key = gitlog.signer(root, sha)
    if status not in ("G", "U"):
        return False
    want = [str(a.get("signing_key", "")).replace(" ", "").upper() for a in cfg.get("approvers") or []
            if isinstance(a, dict) and str(a.get("email", "")).lower() == email and a.get("signing_key")]
    return not want or any(key.endswith(w) or w.endswith(key) for w in want if key)
