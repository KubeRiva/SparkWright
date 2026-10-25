"""`sparkwright` command-line interface (SYSTEM 'Interfaces')."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from importlib import resources
from pathlib import Path

from . import __version__
from .core import approvals, checks, gitlog, ids, ledger, store
from .core.approvals import Approval
from .core.grammar import text_hash
from .runner.providers import ProviderError
from .runner.router import RoleFailed

EXIT_OK, EXIT_FAIL, EXIT_USAGE = 0, 1, 2


class CommandError(RuntimeError):
    """A user-facing error reported through _emit (text or JSON)."""


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse usage errors honour --json (S11.6)
        if "--json" in sys.argv[1:] or "--json" in (getattr(self, "_argv", None) or []):
            print(json.dumps({"ok": False, "command": self.prog, "data": {"error": message}}, sort_keys=True))
            raise SystemExit(EXIT_USAGE)
        super().error(message)


def _emit(args, command: str, ok: bool, data: dict, text: str) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"ok": ok, "command": command, "data": data}, sort_keys=True, indent=2))
    else:
        print(text)
    return EXIT_OK if ok else EXIT_FAIL


# ---------------------------------------------------------------- check
def cmd_check(args) -> int:
    res = checks.run(args.root)
    lines = []
    for f in res.findings:
        if f.severity == "info" and not args.verbose:
            continue
        loc = f"{f.location()}: " if f.location() else ""
        lines.append(f"{f.severity.upper():7} {loc}{f.message} [{f.code}]")
    c = res.counts()
    summary = f"{'PASS' if res.ok else 'FAIL'}: {c['error']} errors, {c['warning']} warnings, {c['info']} info " \
              f"({len(res.nodes)} nodes, {len(res.commits)} commits checked)"
    lines.append(summary)
    return _emit(args, "check", res.ok, res.to_dict(), "\n".join(lines))


# ---------------------------------------------------------------- trace
def _tree_lines(t: dict, depth: int = 0) -> list[str]:
    pad = "  " * depth
    extra = []
    if t.get("tests"):
        extra.append(f"tests: {', '.join(t['tests'])}")
    if t.get("commits"):
        extra.append(f"commits: {', '.join(t['commits'])}")
    suffix = f"  ({'; '.join(extra)})" if extra else ""
    out = [f"{pad}{t['id']} [{t['kind']}, {t['status']}]{suffix}"]
    for c in t["children"]:
        out.extend(_tree_lines(c, depth + 1))
    return out


def cmd_trace(args) -> int:
    res = checks.run(args.root, write_ledger=False)
    rid = ids.canonical(args.id)
    if rid not in res.nodes:
        return _emit(args, "trace", False, {"error": f"unknown id {rid}"}, f"Unknown ID: {rid}")
    up = ledger.ancestors(res.nodes, rid)
    down = ledger.descendants(res.nodes, rid)
    lines = ["Up (why it exists):"]
    for path in up:
        lines.append("  " + " -> ".join(path))
    lines.append("Down (what implements and verifies it):")
    lines.extend("  " + l for l in _tree_lines(down))
    return _emit(args, "trace", True, {"up": up, "down": down}, "\n".join(lines))


# ---------------------------------------------------------------- status
def cmd_status(args) -> int:
    root = Path(args.root)
    res = checks.run(root)
    levels: dict[str, dict[str, int]] = {}
    for n in res.nodes.values():
        if n.kind in ids.PYRAMID or n.kind == "evidence":
            levels.setdefault(n.kind, {}).setdefault(n.status, 0)
            levels[n.kind][n.status] += 1
    gaps = [f for f in res.findings if f.severity != "info" and f.code.startswith(("coverage.", "vision.", "task.no-test", "ref."))]
    drift = [f for f in res.findings if f.code.startswith("drift.")]
    locks = [f for f in res.findings if f.code.startswith("approval.")]
    reviews = sorted(p.name for p in (root / "specs" / "reviews").glob("*.md")) if (root / "specs" / "reviews").is_dir() else []
    open_findings = 0
    for name in reviews:
        for line in (root / "specs" / "reviews" / name).read_text(encoding="utf-8-sig").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("| F") and cells and cells[-1].lower() == "open":
                open_findings += 1
    cost = 0.0
    runs_dir = root / ".sparkwright" / "runs"
    if runs_dir.is_dir():
        for p in runs_dir.glob("*.jsonl"):
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    cost += float(json.loads(line).get("cost_usd", 0) or 0)
                except (json.JSONDecodeError, ValueError, AttributeError):
                    pass
    order = ["evidence"] + ids.PYRAMID
    lines = ["Levels:"]
    for k in order:
        if k in levels:
            parts = ", ".join(f"{v} {s}" for s, v in sorted(levels[k].items()))
            lines.append(f"  {k:10} {parts}")
    lines += [
        f"Coverage gaps:      {len(gaps)}",
        f"Drift:              {len(drift)}",
        f"Approval problems:  {len(locks)}",
        f"Reviews on file:    {len(reviews)} ({open_findings} open findings)",
        f"Agent cost so far:  ${cost:.2f}",
        f"Check:              {'PASS' if res.ok else 'FAIL'} ({res.counts()['error']} errors)",
    ]
    data = {"levels": levels, "gaps": len(gaps), "drift": len(drift), "approval_problems": len(locks),
            "reviews": reviews, "open_findings": open_findings, "cost_usd": round(cost, 4), "check_ok": res.ok}
    print_ok = True  # status reports; it does not fail the build
    return _emit(args, "status", print_ok, data, "\n".join(lines))


# ---------------------------------------------------------------- approve
_STATUS_RE = re.compile(r"^status:\s*\S+\s*$", re.M)


def _set_status(path: Path, status: str) -> None:
    raw = path.read_bytes().decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in raw else "\n"
    text = raw.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return
    end = text.find("\n---", 3)
    head, rest = text[:end], text[end:]
    if _STATUS_RE.search(head):
        head = _STATUS_RE.sub(f"status: {status}", head, count=1)
    else:
        head = head + f"\nstatus: {status}"
    path.write_bytes((head + rest).replace("\n", nl).encode("utf-8"))


def cmd_approve(args) -> int:
    root = Path(args.root).resolve()
    repo = store.load(root)
    latest = approvals.latest(approvals.read(root)[0])
    when = approvals.now()
    entries: list[Approval] = []
    target = args.id if args.test else ids.canonical(args.id)

    if args.test:
        path = root / target
        if not path.is_file():
            return _emit(args, "approve", False, {"error": "no such file"}, f"No such test file: {target}")
        entries.append(Approval(f"test:{Path(target).as_posix()}", checks.file_hash(path), args.approver, args.role, args.cr, when))
        approvals.append(root, entries)
        return _emit(args, "approve", True, {"approved": [entries[0].id]}, f"Locked test {target}.")

    file_match = [sf for sf in repo.files if sf.id == target]
    if file_match:
        sf = file_match[0]
        if any(i.code.startswith(("grammar.", "frontmatter.")) for i in sf.issues):
            return _emit(args, "approve", False, {"error": "file has parse errors"},
                         f"Refusing: {sf.path} has parse errors; run `sparkwright check`.")
        reqs = sf.requirements
        if sf.meta.get("type") in ("evidence", "change", "decision"):
            body_hash = checks.evidence_hash(root / sf.path)
            entries.append(Approval(sf.id, body_hash, args.approver, args.role, args.cr, when,
                                    hash2=checks.evidence_hash2(root / sf.path)))
    elif target in repo.requirements:
        sf, reqs = None, [repo.requirements[target]]
    else:
        return _emit(args, "approve", False, {"error": f"unknown id {target}"}, f"Unknown ID: {target}")

    if args.cr:
        args.cr = ids.canonical(args.cr)
    if args.cr and args.cr not in checks.approved_change_requests(repo, approvals.latest(approvals.read(root)[0]), root):
        return _emit(args, "approve", False, {"error": f"{args.cr} is not an approved change request"},
                     f"Refusing: {args.cr} is not an approved change request in specs/changes/.")
    derived = {k: n.status for k, n in checks.run(root, write_ledger=False).nodes.items()}
    from .core import events as events_mod
    evs, _ = events_mod.read(root)
    cr_targets: list[str] = []
    if args.cr:
        cr_sf = next((f for f in repo.files if f.id == args.cr), None)
        cr_targets = checks.cr_targets(cr_sf.meta if cr_sf else {})

    def ancestors(rid: str) -> set[str]:
        seen, stack = set(), list(repo.requirements[rid].refs) if rid in repo.requirements else []
        while stack:
            a = stack.pop()
            if a not in seen:
                seen.add(a)
                stack.extend(repo.requirements[a].refs if a in repo.requirements else [])
        return seen

    def last_applied(rid: str) -> str | None:
        return max((e.time for e in evs if e.id == rid and e.event == "cr-applied"), default=None)

    blocked, unreviewed, refused, not_covered = [], [], [], []
    for r in reqs:
        prev = latest.get(r.id)
        risk = approvals.risk_of(repo, r.id)
        changed_like = derived.get(r.id) in ("changed", "in-review")
        same = prev is not None and approvals.matches(prev, r)
        if same and prev.hash2 is not None and not changed_like and approvals.risk_matches(prev, repo, r.id):
            continue  # already approved as-is
        if same and prev.hash2 is None and not changed_like and approvals.risk_matches(prev, repo, r.id):
            entries.append(Approval(r.id, r.hash, args.approver, args.role, prev.change_request, when, risk, r.hash2))
            continue  # D007: refresh a legacy lock; the text the human approved is unchanged
        if prev and (not same or changed_like) and not args.cr:
            blocked.append(r.id)
            continue
        if args.cr and prev:  # S3.10: a change request re-approves its target only after a review, then its descendants
            above = [t for t in cr_targets if t in ancestors(r.id)]
            if r.id not in cr_targets and not above:
                msg = f"{r.id} is not {', '.join(cr_targets)} or below it, so {args.cr} does not cover it"
                (not_covered if sf is not None else refused).append(msg)  # a whole file may mix change requests
                continue
            if r.id in cr_targets and not any(e.id == r.id and e.event == "cr-applied" and e.reason == args.cr for e in evs):
                refused.append(f"apply {args.cr} first (`sparkwright change apply {args.cr}`)")
                continue
            applied = last_applied(r.id)
            if applied and not events_mod.reviewed_since(evs, r.id, r.hash, applied):
                unreviewed.append(r.id)
                continue
            if r.id not in cr_targets:
                waiting = []
                for t in above:
                    t_appr, t_applied = latest.get(t), last_applied(t)
                    now_ok = any(e.id == t for e in entries)  # re-approved earlier in this same command
                    if not now_ok and (derived.get(t) != "approved" or (t_applied and (not t_appr or t_appr.time < t_applied))):
                        waiting.append(t)
                if waiting:
                    refused.append(f"{r.id}: re-approve the change request's target {', '.join(waiting)} first (S3.10)")
                    continue
        entries.append(Approval(r.id, r.hash, args.approver, args.role, args.cr, when, risk, r.hash2))
    if refused:
        return _emit(args, "approve", False, {"refused": refused}, "Refusing: " + "; ".join(refused))
    if unreviewed:
        return _emit(args, "approve", False, {"needs_review": unreviewed},
                     "Refusing: review the changed text first (S3.10): "
                     + ", ".join(f"`sparkwright review {repo.file_of[i].id or i}`" for i in unreviewed))
    if blocked:
        return _emit(args, "approve", False, {"needs_change_request": blocked},
                     "Refusing: these approved requirements changed and need a change request (--cr CR<n>): "
                     + ", ".join(blocked))
    if not_covered and not entries:
        return _emit(args, "approve", False, {"refused": not_covered}, "Refusing: " + "; ".join(not_covered))
    approvals.append(root, entries)
    if sf is not None and not not_covered:
        _set_status(root / sf.path, "approved")
    ids_done = [e.id for e in entries]
    msg = f"Recorded {len(entries)} approval(s) by {args.approver}" + (f" for {sf.path}" if sf else "") + "."
    if not_covered:
        msg += (f" Left for another change request: {len(not_covered)} requirement(s) outside {args.cr}; "
                f"the file stays in review until they are approved too.")
    return _emit(args, "approve", True, {"approved": ids_done, "not_covered": not_covered}, msg)


# ---------------------------------------------------------------- init
TEMPLATE_TARGETS = {
    "constitution.md": "specs/constitution.md",
    "vision.md": "specs/vision.md",
    "system.md": "specs/system.md",
    "config.yaml": ".sparkwright/config.yaml",
}


def cmd_init(args) -> int:
    root = Path(args.root).resolve()
    created = []
    tdir = resources.files("sparkwright") / "data" / "templates"
    for d in ["specs/evidence", "specs/components", "specs/tasks", "specs/reviews", "specs/changes", "specs/decisions", ".sparkwright/templates"]:
        (root / d).mkdir(parents=True, exist_ok=True)
    for name in sorted(p.name for p in tdir.iterdir()):
        dest_rel = TEMPLATE_TARGETS.get(name, f".sparkwright/templates/{name}")
        dest = root / dest_rel
        if dest.exists():
            continue
        with resources.as_file(tdir / name) as src:
            shutil.copyfile(src, dest)
        created.append(dest_rel)
    if gitlog.is_repo(root):
        import subprocess
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True)
        cfg = root / ".sparkwright" / "config.yaml"
        if head.returncode == 0 and "baseline: null" in cfg.read_text(encoding="utf-8"):
            cfg.write_text(cfg.read_text(encoding="utf-8").replace("baseline: null", f"baseline: {head.stdout.strip()}"), encoding="utf-8")
        name, email = gitlog.user_identity(root)
        text = cfg.read_text(encoding="utf-8")
        if email and "approvers: []" in text:
            cfg.write_text(text.replace("approvers: []", f"approvers:\n  - {{name: \"{name or email}\", email: \"{email}\"}}"), encoding="utf-8")
    gi = root / ".gitignore"
    wanted = [".sparkwright/ledger.json", ".sparkwright/runs/", ".sparkwright/worktrees/"]
    existing = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    missing = [w for w in wanted if w not in existing]
    if missing:
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if existing and existing[-1] else "") + "\n".join(missing) + "\n")
    ensure_union_merge(root)
    return _emit(args, "init", True, {"created": created},
                 "Initialised SparkWright.\n" + "\n".join(f"  created {c}" for c in created))



UNION_LOGS = ["specs/approvals.jsonl merge=union", "specs/events.jsonl merge=union"]


def ensure_union_merge(root: Path) -> bool:
    """S3.8: parallel build branches each append to the logs; a union merge keeps every line without conflicts."""
    ga = root / ".gitattributes"
    existing = ga.read_text(encoding="utf-8").splitlines() if ga.exists() else []
    missing = [w for w in UNION_LOGS if w not in existing]
    if missing:
        with ga.open("a", encoding="utf-8") as fh:
            fh.write(("\n" if existing and existing[-1] else "") + "\n".join(missing) + "\n")
    return bool(missing)


# ---------------------------------------------------------------- runner commands
def _router(args, root: Path):
    from .core import config as config_mod
    from .runner.providers import FakeProvider
    from .runner.router import Router
    cfg, errors = config_mod.load(root)
    if errors:
        raise CommandError("config errors: " + "; ".join(errors))
    overrides = {}
    if getattr(args, "dry_run", False):
        fake = FakeProvider(default="[]")
        overrides = {"fast": fake, "mid": fake, "top": fake}
    return Router(cfg, overrides)


def cmd_review(args) -> int:
    from .core import config as config_mod
    from .runner.review import ReviewError, collect, prepare, run_review
    root = Path(args.root).resolve()
    personas = args.personas.split(",") if args.personas else None
    if args.prepare:
        try:
            prep = prepare(root, args.id, personas)
        except ReviewError as exc:
            return _emit(args, "review", False, {"error": str(exc)}, f"Error: {exc}")
        data = {"run_id": prep.run_id, "context": str(prep.context_path.relative_to(root)),
                "outputs_dir": str(prep.run_dir.relative_to(root)), "personas": prep.personas,
                "target": prep.target, "level": prep.level}
        text = (f"Prepared review run {prep.run_id} for {prep.target}.\nContext: {data['context']}\n"
                f"Write each persona's JSON findings to {data['outputs_dir']}/<persona>.json for: {', '.join(prep.personas)}\n"
                f"Then run: sparkwright review {prep.target} --collect {prep.run_id}")
        return _emit(args, "review", True, data, text)
    try:
        if args.collect:
            cfg, _ = config_mod.load(root)
            res = collect(root, args.collect, cfg)
        else:
            router = _router(args, root)
            res = run_review(root, args.id, router, personas, run_id=args.resume, write=not args.dry_run)
    except (ReviewError, ProviderError) as exc:
        return _emit(args, "review", False, {"error": str(exc)}, f"Error: {exc}")
    c = res.counts()
    lines = [f"Review {res.review_id} of {res.target} ({res.level}) by: {', '.join(res.ran) or 'nobody'}"]
    if args.dry_run:
        lines.append("(dry run: no model calls were billed and no review file was written)")
    for f in res.findings[:20]:
        lines.append(f"  [{f.severity}] {', '.join(f.ids) or '-'}: {f.finding}")
    if len(res.findings) > 20:
        lines.append(f"  ... {len(res.findings) - 20} more in the review file")
    if res.skipped:
        lines.append(f"Skipped (cost ceiling): {', '.join(res.skipped)}")
    if res.abstained:
        lines.append(f"Abstained: {', '.join(res.abstained)}")
    lines.append(f"{c['high']} high, {c['medium']} medium, {c['low']} low; cost ${res.cost_usd:.2f}")
    if res.path:
        lines.append(f"Written to {res.path.relative_to(root)}")
    lines.append(f"Gate: {res.gate}")
    ok = not res.gate.startswith("FAIL")
    data = {"review_id": res.review_id, "target": res.target, "gate": res.gate, "counts": c,
            "path": str(res.path.relative_to(root)) if res.path else None, "run_id": res.run_id,
            "ran": res.ran, "skipped": res.skipped, "abstained": res.abstained}
    return _emit(args, "review", ok, data, "\n".join(lines))


def _guide(args, root: Path) -> int:
    from .runner import guide as gd
    minors = True if args.minors else None
    try:
        if args.file:
            data = gd.advance(root, args.file)
        elif args.prepare:
            data = gd.prepare(root, args.about or "", minors)
        else:
            data = gd.run(root, args.about or "", _router(args, root), minors)
    except (gd.GuideError, ProviderError, RoleFailed, OSError) as exc:
        return _emit(args, "interview", False, {"error": str(exc)}, f"Stopped: {exc}")
    if data["step"] != "done":
        who = "Guide Writer" if data["step"] == gd.WRITER else "Question Auditor"
        return _emit(args, "interview", True, data, f"Run a fresh {who} agent on {data['prompt']}, save its reply to "
                                                   f"{data['result_file']}, then run: {data['then']}")
    return _emit(args, "interview", data["high"] == 0, data,
                 f"Guide: {data['guide']}\n{data['gate']} ({data['findings']} findings, {data['high']} high).")


def cmd_interview(args) -> int:
    from .runner import interview as iv
    root = Path(args.root).resolve()
    if args.mode == "guide":
        return _guide(args, root)
    names = [n for n in (args.redact or "").split(",") if n.strip()]
    try:
        if args.mode == "owner" and args.host:
            data = iv.host_owner(root, args.consent or "")
            return _emit(args, "interview", True, data,
                         f"Interview the owner in chat following {data['prompt']}; save the transcript to "
                         f"{data['transcript']}, then run: {data['then']}")
        if args.mode == "ingest" and args.prepare:
            if not args.file:
                raise iv.InterviewError("give the transcript file")
            data = iv.prepare_ingest(root, args.file, args.consent or "", names, args.simulated)
            return _emit(args, "interview", True, data,
                         f"Run a fresh Theme Synthesizer agent on {data['prompt']}, save its reply to "
                         f"{data['result_file']}, then run: {data['then']}")
        if args.mode == "collect":
            if not args.file:
                raise iv.InterviewError("give the run id from --prepare")
            res = iv.collect(root, args.file)
        else:
            router = _router(args, root)
            if args.mode == "owner":
                res = iv.owner_interview(root, router, names=names)
            else:
                if not args.file:
                    raise iv.InterviewError("give the transcript file")
                res = iv.ingest(root, router, args.file, args.consent or "", names=names, simulated=args.simulated)
    except (iv.InterviewError, ProviderError, RoleFailed, OSError) as exc:
        return _emit(args, "interview", False, {"error": str(exc)}, f"Stopped: {exc}")
    msg = f"Evidence written to {res.path.relative_to(root)}."
    if res.saturated:
        msg += " Saturation reached: the last 3 interviews added no new themes."
    return _emit(args, "interview", True, {"path": str(res.path.relative_to(root)), "saturated": res.saturated}, msg)


def cmd_adopt(args) -> int:
    from .runner import adopt as ad
    root = Path(args.root).resolve()
    try:
        if not (root / ".sparkwright" / "config.yaml").exists():
            raise ad.AdoptError("run `sparkwright init` first")
        if args.collect:
            data = ad.collect(root, args.collect)
        elif args.prepare:
            data = ad.prepare(root, args.path or None)
            return _emit(args, "adopt", True, data,
                         f"Run a fresh Surveyor agent on {data['prompt']}, save its reply to {data['result_file']}, "
                         f"then run: {data['then']}")
        else:
            data = ad.run(root, _router(args, root), args.path or None)
    except (ad.AdoptError, ProviderError, RoleFailed, OSError) as exc:
        return _emit(args, "adopt", False, {"error": str(exc)}, f"Stopped: {exc}")
    msg = "Drafted (all status: draft): " + ", ".join(data["files"])
    if data["baseline"]:
        msg += f"\nBaseline recorded: {data['baseline'][:12]} (checks apply to commits after it)."
    if data["warnings"]:
        msg += "\nWarnings:\n" + "\n".join(f"- {w}" for w in data["warnings"])
    msg += f"\nNext: correct the drafts, interview the owner, then {data['next']}."
    return _emit(args, "adopt", True, data, msg)


def cmd_calibrate(args) -> int:
    from .runner import calibrate as cb
    root = Path(args.root).resolve()
    personas = [n.strip() for n in (args.personas or "").split(",") if n.strip()] or None
    try:
        if args.collect:
            data = cb.collect(root, args.collect)
        elif args.prepare:
            data = cb.prepare(root, personas, batch=args.batch)
            return _emit(args, "calibrate", True, data,
                         f"{len(data['jobs'])} reviews to run, each by a fresh agent of the named persona on its context "
                         f"file; save each reply to its result_file, then run: {data['then']}")
        else:
            data = cb.run(root, _router(args, root), personas, args.tier or None)
    except (cb.CalibrationError, ProviderError, RoleFailed, OSError) as exc:
        return _emit(args, "calibrate", False, {"error": str(exc)}, f"Stopped: {exc}")
    msg = f"Wrote {data['report']}."
    if data.get("missing"):
        msg += f" Missing replies (scored as no findings): {len(data['missing'])}."
    if data["propose_disable"]:
        msg += f" Proposed for a human to disable: {', '.join(data['propose_disable'])} (see the report)."
    return _emit(args, "calibrate", True, data, msg)


def cmd_descend(args) -> int:
    from .runner import descend as ds
    root = Path(args.root).resolve()
    try:
        if args.collect:
            data = ds.collect(root, args.collect)
        elif not args.id:
            raise ds.DescendError("give the parent requirement ID")
        elif args.prepare:
            data = ds.prepare(root, args.id)
            return _emit(args, "descend", True, data,
                         f"Run a fresh Architect agent on {data['prompt']}, save its reply to "
                         f"{data['result_file']}, then run: {data['then']}")
        else:
            data = ds.run(root, args.id, _router(args, root))
    except (ds.DescendError, ProviderError, RoleFailed, OSError) as exc:
        return _emit(args, "descend", False, {"error": str(exc)}, f"Stopped: {exc}")
    msg = f"Draft written: {', '.join(data['files'])} ({', '.join(data['ids'])})."
    if data["open_questions"]:
        msg += "\nOpen questions from the Architect:\n" + "\n".join(f"- {q}" for q in data["open_questions"])
    msg += f"\nNext: {data['next']}, then a human approves."
    return _emit(args, "descend", True, data, msg)


def cmd_mutate(args) -> int:
    from .core import config as config_mod
    from .runner import mutate
    root = Path(args.root).resolve()
    cfg, _ = config_mod.load(root)
    test_cmd = args.test_cmd or cfg.get("checks", {}).get("test")
    if not test_cmd:
        return _emit(args, "mutate", False, {"error": "no test command"}, "Set checks.test in .sparkwright/config.yaml or pass --test-cmd.")
    budget = float(args.budget or cfg.get("mutation", {}).get("time_budget_s", 300))
    minimum = float(cfg.get("mutation", {}).get("min", 0.8))
    from .runner.verify import command_env
    rep = mutate.run(root, args.base, test_cmd, budget, test_globs=cfg.get("test_globs"), env=command_env(cfg.get("env"), root))
    ok = rep.baseline_ok and rep.score >= minimum
    lines = [rep.message]
    for m in rep.survivors[:30]:
        lines.append(f"  survived: {m.file}:{m.line} {m.description}")
    if rep.timed_out_budget:
        lines.append("Time budget reached; remaining mutants were not run.")
    lines.append(f"{'PASS' if ok else 'FAIL'} (minimum {minimum:.2f})")
    data = {"score": round(rep.score, 4), "total": rep.total, "killed": rep.killed, "baseline_ok": rep.baseline_ok,
            "survivors": [{"file": m.file, "line": m.line, "mutation": m.description} for m in rep.survivors]}
    return _emit(args, "mutate", ok, data, "\n".join(lines))


def cmd_guard(args) -> int:
    from .adapters import guard
    return guard.main(args.host)


def cmd_adapt(args) -> int:
    root = Path(args.root).resolve()
    if args.host == "claude-code":
        from .adapters import claude_code
        out = Path(args.out) if args.out else root / "adapters" / "claude-code"
        if not out.is_absolute():
            out = root / out
        written = claude_code.generate(out, root)
        extra = []
        if args.marketplace:
            mp = claude_code.write_marketplace(root, out.relative_to(root).as_posix())
            extra.append(str(mp.relative_to(root)))
        rel = out.relative_to(root) if out.is_relative_to(root) else out
        return _emit(args, "adapt", True, {"out": str(rel), "files": written + extra},
                     f"Generated Claude Code plugin in {rel} ({len(written)} files)." + (f" Marketplace: {extra[0]}" if extra else ""))
    if args.host in ("codex", "gemini"):
        from .adapters import codex, gemini
        mod = codex if args.host == "codex" else gemini
        default = root if args.host == "codex" else root / "adapters" / "gemini"
        out = Path(args.out) if args.out else default
        if not out.is_absolute():
            out = root / out
        written = mod.generate(out, root)
        rel = out.relative_to(root) if out.is_relative_to(root) else out
        how = ("Codex reads .agents/skills, .codex/agents and .codex/hooks.json in this project; trust the hook once "
               "with /hooks." if args.host == "codex" else f"Install with: gemini extensions install {out}")
        return _emit(args, "adapt", True, {"out": str(rel), "files": written},
                     f"Generated {args.host} adapter in {rel} ({len(written)} files). {how}")
    from .adapters import agents_md
    path = agents_md.write(root)
    return _emit(args, "adapt", True, {"path": str(path.relative_to(root))},
                 f"Updated {path.relative_to(root)} (human-gated: review and commit it yourself).")


def _build_many(args, root: Path) -> int:
    """S3.8: plan non-overlapping batches; in Runner mode build each batch's tasks concurrently."""
    from concurrent.futures import ThreadPoolExecutor
    from .runner import parallel
    from .runner.build import Build, BuildError
    try:
        batches = parallel.plan_batches(root, args.id)
    except ValueError as exc:
        return _emit(args, "build", False, {"error": str(exc)}, f"Error: {exc}")
    if args.plan or args.next or args.done:
        text = "\n".join(f"Batch {i}: {', '.join(b)}" for i, b in enumerate(batches, 1))
        text += "\nTasks in one batch may build at the same time; start a batch after the previous one is merged."
        return _emit(args, "build", True, {"batches": batches}, text)
    router = _router(args, root)

    def one(task: str) -> dict:
        try:
            return Build(root, task, restart=args.restart).run(router)
        except (BuildError, ProviderError, RoleFailed) as exc:
            return {"task": task, "step": "error", "reason": str(exc)}

    first = batches[0]  # later batches overlap these files: they start after a human merges this batch
    with ThreadPoolExecutor(max_workers=max(1, min(args.parallel or 1, len(first)))) as pool:
        results = list(pool.map(one, first))
    ok = all(r["step"] == "ready" for r in results)
    text = "\n".join(f"{r['task']}: {r['step']} {r.get('reason', '')}".rstrip() for r in results)
    if len(batches) > 1:
        text += "\nNot started (their files may overlap this batch; merge first): " + \
                "; ".join(", ".join(b) for b in batches[1:])
    return _emit(args, "build", ok, {"batches": batches, "results": results}, text)


def cmd_build(args) -> int:
    from .runner.build import Build, BuildError
    root = Path(args.root).resolve()
    if len(args.id) > 1 or args.plan:
        return _build_many(args, root)
    args.id = args.id[0]
    try:
        b = Build(root, args.id, restart=args.restart)
        if args.abandon:
            ins = b.abandon()
        elif args.done:
            src = args.result
            if not src:
                raise BuildError("--done needs --result <file> (the agent's reply), or '-' for stdin")
            if src == "-":
                text = sys.stdin.read()
            else:
                path = (root / src).resolve()
                runs = (root / ".sparkwright" / "runs").resolve()
                if runs not in path.parents:
                    raise BuildError("--result must be a file inside .sparkwright/runs/")
                if not path.is_file():
                    raise BuildError(f"result file {src} does not exist; save the agent's final reply there first")
                text = path.read_text(encoding="utf-8")
            ins = b.submit(args.done, text)
        elif args.next:
            ins = b.advance()
        else:
            ins = b.run(_router(args, root))
    except (BuildError, ProviderError, RoleFailed) as exc:
        return _emit(args, "build", False, {"error": str(exc)}, f"Error: {exc}")
    if ins["kind"] == "agent":
        text = (f"Next step for {ins['task']}: run the '{ins['persona']}' agent with a fresh context on\n"
                f"  {ins['prompt']}\nin workspace {ins['workspace']}. Save its final reply to {ins['result_file']}, then:\n  {ins['then']}")
    elif ins["step"] == "ready":
        text = ins["message"] + (f" Mutation score: {ins['mutation_score']}." if "mutation_score" in ins else "")
    elif ins["step"] == "changed":
        text = f"Build stopped: the spec needs to change. Review {ins['change_request']} (target {ins['target']})."
    else:
        text = f"Build {ins['step']}: {ins.get('reason', '')}"
    ok = ins["step"] not in ("blocked",)
    return _emit(args, "build", ok, ins, text)


def cmd_verify(args) -> int:
    from .core import config as config_mod
    from .runner.verify import run_checks
    root = Path(args.root).resolve()
    cfg, _ = config_mod.load(root)
    if not cfg.get("checks"):
        return _emit(args, "verify", False, {"error": "no checks configured"}, "Add commands under `checks:` in .sparkwright/config.yaml.")
    from .runner.verify import command_env
    results = run_checks(root, cfg["checks"], env=command_env(cfg.get("env"), root, (cfg.get("sandbox") or {}).get("keep_env")))
    ok = all(r.ok for r in results)
    lines = [f"{'PASS' if r.ok else 'FAIL'}  {r.name}: {r.command}" + ("" if r.ok else "\n" + r.output[-1500:]) for r in results]
    return _emit(args, "verify", ok, {"results": [{"name": r.name, "ok": r.ok} for r in results]}, "\n".join(lines))


def cmd_change(args) -> int:
    from .core import events as events_mod
    root = Path(args.root).resolve()
    repo = store.load(root)
    if args.action == "new":
        targets = [ids.canonical(t) for t in (args.target or [])]
        unknown = [t for t in targets if t not in repo.requirements]
        if not targets or unknown:
            return _emit(args, "change", False, {"error": f"unknown requirement {', '.join(unknown)}"},
                         f"Unknown requirement: {', '.join(unknown) or '(none given)'}")
        nums = [int(sf.id[2:]) for sf in repo.files if sf.id and ids.kind_of(sf.id) == "change"]
        cr = f"CR{max(nums or [0]) + 1}"
        path = root / "specs" / "changes" / f"{cr}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = "\n".join(f"- **{t}** [{', '.join(repo.requirements[t].refs)}] {repo.requirements[t].text}\n" for t in targets)
        tgt = targets[0] if len(targets) == 1 else "[" + ", ".join(targets) + "]"
        title = f"Change {targets[0]}" if len(targets) == 1 else f"Change {len(targets)} requirements"
        path.write_text(f"---\nid: {cr}\ntitle: {title}\ntype: change\nstatus: open\ntarget: {tgt}\n"
                        f"raised_by: human\nrounds: 0\n---\n\n## Reason\n\n{args.reason or ''}\n\n## ADDED\n\n"
                        f"## MODIFIED\n\n{lines}\n## REMOVED\n", encoding="utf-8")
        return _emit(args, "change", True, {"change_request": str(path.relative_to(root))},
                     f"Opened {path.relative_to(root)}. Edit the MODIFIED lines, then a human approves it with `sparkwright approve {cr} --as <name>`.")
    # apply
    cr = ids.canonical((args.target or [""])[0])
    sf = next((f for f in repo.files if f.id == cr), None)
    if sf is None:
        return _emit(args, "change", False, {"error": f"unknown change request {cr}"}, f"Unknown change request: {cr}")
    if sf.status != "approved":
        return _emit(args, "change", False, {"error": "not approved"}, f"{cr} is '{sf.status}'; it must be approved first.")
    res = checks.run(root, write_ledger=False)
    targets = checks.cr_targets(sf.meta)
    bad = [t for t in targets if t not in res.nodes]
    if not targets or bad:
        return _emit(args, "change", False, {"error": f"unknown target {', '.join(bad)}"}, f"{cr} targets unknown {', '.join(bad) or '(none)'}.")
    affected = []
    for target in targets:
        stack = [ledger.descendants(res.nodes, target)]
        while stack:
            t = stack.pop()
            if t["id"] not in affected:
                affected.append(t["id"])
            stack.extend(t["children"])
    changed = [a for a in affected if res.nodes[a].status in ("approved", "building", "done")]
    events_mod.append(root, [events_mod.make(a, "changed", reason=f"{cr} applied") for a in changed])
    events_mod.append(root, [events_mod.make(t, "cr-applied", reason=cr) for t in targets])
    target = ", ".join(targets)
    _set_status(root / sf.path, "applied")
    return _emit(args, "change", True, {"affected": sorted(affected, key=ids.sort_key), "marked_changed": changed},
                 f"Applied {cr}. {target} is now in review; marked changed: {', '.join(changed) or 'none'}.\n"
                 f"Next: edit {target}, run `sparkwright review "
                 f"{' '.join(sorted({repo.file_of[t].id or t for t in targets}))}`, then `sparkwright approve "
                 f"<file or ids> --as <name> --cr {cr}`, then rebuild affected tasks.")

# ---------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="sparkwright", description="Evidence-backed, multi-level, verified spec-driven development.")
    p.add_argument("--version", action="version", version=f"sparkwright {__version__}")
    p.add_argument("-C", "--root", default=".", help="repository root (default: current directory)")
    p.add_argument("--json", action="store_true", dest="json_global", help="machine-readable output")
    sub = p.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def common(sp):
        sp.add_argument("--json", action="store_true", help="machine-readable output")
        return sp

    sp = common(sub.add_parser("check", help="offline grammar, coverage, approval, drift and role checks"))
    sp.add_argument("-v", "--verbose", action="store_true", help="also show info findings")
    sp.set_defaults(func=cmd_check)
    sp = common(sub.add_parser("trace", help="show why an ID exists and what implements it"))
    sp.add_argument("id")
    sp.set_defaults(func=cmd_trace)
    common(sub.add_parser("status", help="summary of levels, gaps, drift and cost")).set_defaults(func=cmd_status)
    sp = common(sub.add_parser("approve", help="record a human approval for a spec file, requirement or test"))
    sp.add_argument("id", help="file id (e.g. SYSTEM), requirement id, or test path with --test")
    sp.add_argument("--as", dest="approver", required=True, help="name of the person approving")
    sp.add_argument("--role", default="human", choices=["human", "runner"], help=argparse.SUPPRESS)
    sp.add_argument("--cr", default=None, help="change request authorising a changed requirement")
    sp.add_argument("--test", action="store_true", help="lock a test file")
    sp.set_defaults(func=cmd_approve)
    common(sub.add_parser("init", help="create specs/, templates and config")).set_defaults(func=cmd_init)
    sp = common(sub.add_parser("review", help="run the Inspector swarm on a spec and write a review"))
    sp.add_argument("id", help="file id (e.g. SYSTEM) or requirement id")
    sp.add_argument("--personas", help="comma-separated persona names (default: by level)")
    sp.add_argument("--resume", metavar="RUN_ID", help="resume an interrupted run")
    sp.add_argument("--dry-run", action="store_true", help="no model calls; show what would run")
    sp.add_argument("--prepare", action="store_true", help="host-agent mode: write the isolated context and persona list")
    sp.add_argument("--collect", metavar="RUN_ID", help="host-agent mode: merge persona outputs and gate")
    sp.set_defaults(func=cmd_review)
    sp = common(sub.add_parser("interview", help="gather evidence: owner interview or transcript ingest"))
    sp.add_argument("mode", choices=["owner", "ingest", "collect", "guide"])
    sp.add_argument("file", nargs="?", help="transcript file (ingest) or run id (collect, guide)")
    sp.add_argument("--about", help="guide: who the target users are and what to learn")
    sp.add_argument("--minors", action="store_true", help="guide: target users include people under 18")
    sp.add_argument("--host", action="store_true", help="owner: host agent interviews in chat (no API key)")
    sp.add_argument("--prepare", action="store_true", help="ingest: write the Theme Synthesizer prompt for a host agent")
    sp.add_argument("--consent", help="how consent was obtained (required for ingest)")
    sp.add_argument("--redact", help="comma-separated names to remove")
    sp.add_argument("--simulated", action="store_true", help="mark evidence as simulated (never counts as evidence)")
    sp.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_interview)
    sp = common(sub.add_parser("calibrate", help="score Inspector personas on planted-flaw specs (catch and false-alarm rates)"))
    sp.add_argument("--personas", help="comma-separated personas (default: all Inspectors)")
    sp.add_argument("--tier", action="append", choices=["fast", "mid", "top"], help="Runner mode: tier to test (repeatable)")
    sp.add_argument("--prepare", action="store_true", help="host-agent mode: write one job per persona and case")
    sp.add_argument("--batch", action="store_true", help="host-agent mode: one job per persona covering all its cases (cheaper, less independent)")
    sp.add_argument("--collect", metavar="RUN_ID", help="host-agent mode: score the replies and write the report")
    sp.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_calibrate)
    sp = common(sub.add_parser("adopt", help="Surveyor drafts System, Component and Task specs from an existing codebase"))
    sp.add_argument("--path", action="append", help="only survey this directory (repeatable)")
    sp.add_argument("--prepare", action="store_true", help="host-agent mode: write the Surveyor prompt")
    sp.add_argument("--collect", metavar="RUN_ID", help="host-agent mode: write the drafts from the Surveyor's reply")
    sp.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_adopt)
    sp = common(sub.add_parser("descend", help="Architect drafts the next spec level under an approved requirement"))
    sp.add_argument("id", nargs="?", help="approved system or component requirement ID, e.g. S1.2 or C1.2.1")
    sp.add_argument("--prepare", action="store_true", help="host-agent mode: write the Architect prompt")
    sp.add_argument("--collect", metavar="RUN_ID", help="host-agent mode: validate the Architect's reply and write the draft")
    sp.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_descend)
    sp = common(sub.add_parser("mutate", help="Saboteur: mutation-test lines changed since a git revision"))
    sp.add_argument("--base", required=True, help="git revision to diff against")
    sp.add_argument("--test-cmd", help="test command (default: checks.test in config)")
    sp.add_argument("--budget", help="time budget in seconds")
    sp.set_defaults(func=cmd_mutate)
    sp = sub.add_parser("guard", help="pre-tool hook for host agents (reads hook JSON on stdin)")
    sp.add_argument("--host", choices=["claude-code", "codex", "gemini"], default="claude-code")
    sp.set_defaults(func=cmd_guard)
    sp = common(sub.add_parser("adapt", help="generate host adapters: claude-code plugin or AGENTS.md section"))
    sp.add_argument("host", choices=["claude-code", "codex", "gemini", "agents-md"])
    sp.add_argument("--out", help="output directory for the plugin (default adapters/claude-code)")
    sp.add_argument("--marketplace", action="store_true", help="also write .claude-plugin/marketplace.json at the repo root")
    sp.set_defaults(func=cmd_adapt)
    sp = common(sub.add_parser("build", help="build a task: tests first, code, checks, mutation, review"))
    sp.add_argument("id", nargs="+", help="task ID, e.g. C1.2.1.T1 (several: plan or build in parallel, S3.8)")
    sp.add_argument("--plan", action="store_true", help="group tasks into batches whose files cannot overlap")
    sp.add_argument("--parallel", type=int, default=2, metavar="N", help="Runner mode: build up to N tasks of a batch at once")
    sp.add_argument("--next", action="store_true", help="host mode: run automatic steps and print the next agent step")
    sp.add_argument("--done", metavar="STEP", help="host mode: record the result of an agent step")
    sp.add_argument("--result", metavar="FILE", help="file holding the agent's reply ('-' for stdin)")
    sp.add_argument("--restart", action="store_true", help="start a new run after a blocked build")
    sp.add_argument("--abandon", action="store_true", help="stop an in-progress build (keeps its branch)")
    sp.add_argument("--dry-run", action="store_true", help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_build)
    common(sub.add_parser("verify", help="run the project's checks from config")).set_defaults(func=cmd_verify)
    sp = common(sub.add_parser("change", help="open or apply a change request"))
    sp.add_argument("action", choices=["new", "apply"])
    sp.add_argument("target", nargs="+", help="requirement ID(s) (new) or CR ID (apply)")
    sp.add_argument("--reason", help="why the change is needed (new)")
    sp.set_defaults(func=cmd_change)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)
    parser._argv = argv
    for action in parser._subparsers._group_actions:
        for sp in action.choices.values():
            sp._argv = argv
    args = parser.parse_args(argv)
    args.json = getattr(args, "json", False) or getattr(args, "json_global", False)
    try:
        return args.func(args)
    except CommandError as exc:
        return _emit(args, args.command, False, {"error": str(exc)}, f"Error: {exc}")
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
