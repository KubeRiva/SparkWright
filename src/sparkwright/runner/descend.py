"""Descend workflow (SYSTEM S3.1): draft the next spec level under one approved parent.

System requirement  -> a new component file (specs/components/C<n>-<slug>.md).
Component requirement -> tasks: appended to the component's `## Tasks` section when it
is `lite: true`, otherwise one file per task under specs/tasks/.

The Architect's draft is never trusted: it is parsed, its IDs and refs are checked against
the parent, and it is written with `status: draft` only when it parses cleanly. Inspector
review and human approval follow as for any other draft.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from ..core import checks, frontmatter, ids, store
from ..core.grammar import parse_body
from .personas import load_all
from .runlog import RunLog

OK_PARENT_STATUS = {"approved", "building", "done"}
RESULT = "architect.result.md"
RISK_ORDER = ["low", "medium", "high"]
ARCHITECT_META = {"title", "risk", "lite"}  # the only front-matter keys the Architect may set


class DescendError(RuntimeError):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "draft"


def _higher_risk(a: str, b: str) -> str:
    a, b = str(a).strip().lower(), str(b).strip().lower()
    ra = RISK_ORDER.index(a) if a in RISK_ORDER else len(RISK_ORDER) - 1  # unknown counts as high
    rb = RISK_ORDER.index(b) if b in RISK_ORDER else len(RISK_ORDER) - 1
    return RISK_ORDER[max(ra, rb)]


def _target(root: Path, rel: str) -> Path:
    """Resolve a write target and refuse anything outside specs/."""
    specs = (root / "specs").resolve()
    p = (root / rel).resolve()
    if specs not in p.parents:
        raise DescendError(f"refusing to write outside specs/: {rel}")
    return p


def _front(meta: dict) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig") if p.is_file() else ""


def _plan(root: Path, repo: store.Repo, parent: str) -> dict:
    parent = ids.canonical(parent)
    if parent not in repo.requirements:
        raise DescendError(f"unknown requirement {parent}")
    kind = ids.kind_of(parent)
    if kind not in ("system", "component"):
        raise DescendError(f"descend works from a system or component requirement, not a {kind} ({parent})")
    status = checks.run(root, write_ledger=False).nodes[parent].status
    if status not in OK_PARENT_STATUS:
        raise DescendError(f"{parent} is '{status}'; only an approved parent can be descended")
    owner = repo.file_of[parent]
    risk = str(owner.meta.get("risk", "low"))
    if kind == "system":
        n = 1 + max([int(m.group(1)) for sf in repo.files
                     if sf.meta.get("type") == "component" and sf.id and (m := re.fullmatch(r"C(\d+)", sf.id))] or [0])
        minor = parent.split(".")[1]
        return {"parent": parent, "child": "component", "component": f"C{n}", "prefix": f"C{n}.{minor}.",
                "risk": risk, "owner": owner.path}
    taken = [int(r.split(".T")[1]) for r in repo.requirements if r.startswith(parent + ".T")]
    return {"parent": parent, "child": "task", "prefix": f"{parent}.T", "first": 1 + max(taken or [0]),
            "lite": bool(owner.meta.get("lite", False)), "risk": risk, "owner": owner.path}


def _instructions(plan: dict) -> str:
    p = plan["parent"]
    if plan["child"] == "component":
        c = plan["component"]
        return (f"Write a NEW component spec file for parent {p}. Use this exact front matter:\n\n"
                f"---\nid: {c}\ntitle: <short component name>\ntype: component\nstatus: draft\nrisk: <low|medium|high>\n"
                f"lite: false\n---\n\nThen the sections `## Responsibility`, `## Interfaces` and `## Requirements`. "
                f"Requirement IDs are {plan['prefix']}1, {plan['prefix']}2, ... and every requirement's refs are [{p}]. "
                "Use risk high when the component handles authentication, authorisation, secrets, payments, personal "
                "data or safety. Do not write tasks.")
    first = plan["first"]
    return (f"Write the TASKS that implement parent {p}. Each task is small enough for one Builder in one sitting "
            "and has its own testable behaviour. For each task write exactly:\n\n"
            f"- **{p}.T<k>** [{p}] <what the task delivers, testable>\n\n```yaml\nfiles: [\"<path or glob the task may change>\"]\n"
            "invariants: []\n```\n\n"
            f"Number tasks from {p}.T{first} upward. List under `invariants` only properties that must hold for all inputs. "
            "Write nothing else except optional `> Open question:` lines.")


def _context(root: Path, repo: store.Repo, plan: dict) -> str:
    parent = plan["parent"]
    req = repo.requirements[parent]
    parts = [f"=== PARENT REQUIREMENT ===\n- **{parent}** [{', '.join(req.refs)}] {req.text}"]
    seen, frontier = set(), [parent]
    while frontier:
        rid = frontier.pop()
        owner = repo.file_of.get(rid)
        if owner and owner.path not in seen:
            seen.add(owner.path)
            parts.append(f"=== SPEC FILE ({owner.path}) ===\n" + _read(root / owner.path))
        if rid in repo.requirements:
            frontier.extend(repo.requirements[rid].refs)
    siblings = [r for r in repo.requirements.values() if parent in r.refs]
    if siblings:
        parts.append("=== CHILDREN THAT ALREADY EXIST (do not repeat) ===\n"
                     + "\n".join(f"- **{r.id}** [{', '.join(r.refs)}] {r.text}" for r in siblings))
    const = root / "specs" / "constitution.md"
    if const.is_file():
        parts.append("=== CONSTITUTION ===\n" + _read(const))
    return "\n\n".join(parts)


def prepare(root: Path | str, parent: str) -> dict:
    """Write the Architect prompt for a fresh host agent (host mode)."""
    root = Path(root).resolve()
    repo = store.load(root)
    plan = _plan(root, repo, parent)
    log = RunLog(root, "descend")
    run_dir = log.path.with_suffix("")
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt = run_dir / "architect.md"
    prompt.write_text(load_all(root)["architect"].system_prompt() + "\n=== INSTRUCTIONS ===\n" + _instructions(plan)
                      + "\n\n" + _context(root, repo, plan), encoding="utf-8")
    log.append("start", status="started", **plan)
    return {"run_id": log.run_id, "parent": plan["parent"], "child": plan["child"],
            "prompt": str(prompt.relative_to(root)), "result_file": str((run_dir / RESULT).relative_to(root)),
            "then": f"sparkwright descend --collect {log.run_id}"}


def _strip_fence(text: str) -> str:
    t = text.strip()
    m = re.fullmatch(r"```(?:markdown|md)?\n(.*)\n```", t, re.S)
    return m.group(1) if m else t


def _check_children(reqs, plan: dict, repo: store.Repo) -> list[str]:
    problems = []
    if not reqs:
        problems.append("the draft defines no requirements")
    pat = re.escape(plan["prefix"]) + r"\d+"
    for r in reqs:
        if not re.fullmatch(pat, r.id):
            problems.append(f"{r.id}: IDs must look like {plan['prefix']}<n>")
        if r.id in repo.requirements:
            problems.append(f"{r.id} already exists")
        if plan["parent"] not in r.refs:
            problems.append(f"{r.id} must reference {plan['parent']}")
        for ref in r.refs:
            if ref != plan["parent"] and ref not in repo.requirements:
                problems.append(f"{r.id} references unknown {ref}")
    return problems


def _write_component(root: Path, repo: store.Repo, plan: dict, text: str) -> list[str]:
    try:
        meta, body, first = frontmatter.split(text)
    except frontmatter.FrontMatterError as exc:
        raise DescendError(f"draft front matter is invalid: {exc}") from exc
    meta = {k: v for k, v in (meta or {}).items() if k in ARCHITECT_META}
    title = re.sub(r"\s+", " ", str(meta.get("title") or plan["component"])).strip()[:100]
    meta = {"id": plan["component"], "title": title, "type": "component", "status": "draft",
            "risk": _higher_risk(meta.get("risk", "low"), plan["risk"]), "lite": bool(meta.get("lite", False))}
    reqs, issues = parse_body(body, "draft", first)
    problems = [f"line {i.line}: {i.message}" for i in issues] + _check_children(reqs, plan, repo)
    if any(r.kind != "component" for r in reqs):
        problems.append("a component draft may contain only component requirements (no tasks or other levels)")
    if problems:
        raise DescendError("draft rejected: " + "; ".join(problems))
    path = _target(root, f"specs/components/{plan['component']}-{_slug(title)}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        fh.write(_front(meta) + body.lstrip("\n"))
    return [str(path.relative_to(root).as_posix())]


def _task_blocks(text: str) -> list[tuple[str, str]]:
    """Split a reply into (task id, block text) at task lines; drop anything before the first task."""
    out, cur_id, cur = [], None, []
    for line in text.split("\n"):
        m = re.match(r"^- \*\*(" + ids.ID_PATTERN + r")\*\*", line)
        if m and ids.kind_of(ids.canonical(m.group(1))) == "task":
            if cur_id:
                out.append((cur_id, "\n".join(cur).strip() + "\n"))
            cur_id, cur = ids.canonical(m.group(1)), [line]
        elif cur_id and not line.startswith("> Open question"):
            cur.append(line)
    if cur_id:
        out.append((cur_id, "\n".join(cur).strip() + "\n"))
    return out


def _write_tasks(root: Path, repo: store.Repo, plan: dict, text: str) -> list[str]:
    reqs, issues = parse_body(text, "draft")
    tasks = [r for r in reqs if r.kind == "task"]
    problems = [f"line {i.line}: {i.message}" for i in issues] + _check_children(tasks, plan, repo)
    if len(tasks) != len(reqs):
        problems.append("a task draft may contain only task lines")
    for t in tasks:
        if not t.extras.get("files"):
            problems.append(f"{t.id} declares no files")
    if problems:
        raise DescendError("draft rejected: " + "; ".join(problems))
    blocks = _task_blocks(text)
    block_ids = [b[0] for b in blocks]
    if len(set(block_ids)) != len(block_ids) or sorted(block_ids) != sorted(t.id for t in tasks):
        raise DescendError("draft rejected: task lines must be unique and outside code fences and comments")
    if plan["lite"]:
        path = _target(root, plan["owner"])
        before = {r.id: r.hash for r in store.load(root).file_of[plan["parent"]].requirements}
        content = _read(path).rstrip("\n")
        addition = "\n\n".join(b.rstrip("\n") for _, b in blocks) + "\n"
        m = re.search(r"^## Tasks[ \t]*$", content, re.M)
        if not m:
            content += "\n\n## Tasks\n\n" + addition
        else:
            nxt = re.search(r"^## ", content[m.end():], re.M)
            cut = m.end() + nxt.start() if nxt else len(content)
            content = content[:cut].rstrip("\n") + "\n\n" + addition + ("\n" + content[cut:] if nxt else "")
        original = _read(path)
        # The file now holds unapproved drafts: an approved file goes back to in-review until a human approves it.
        content = re.sub(r"^(---\n(?:.*\n)*?)status:\s*approved\s*$", r"\1status: in-review", content, count=1, flags=re.M)
        path.write_text(content.rstrip("\n") + "\n", encoding="utf-8")
        after_sf = next((sf for sf in store.load(root).files if sf.path == plan["owner"]), None)
        after = {r.id: r.hash for r in after_sf.requirements} if after_sf else {}
        if after_sf is None or after_sf.issues or any(after.get(k) != v for k, v in before.items()) \
                or set(after) - set(before) != set(block_ids):
            path.write_text(original, encoding="utf-8")
            raise DescendError("draft rejected: appending the tasks would change or break the component file")
        return [plan["owner"]]
    written = []
    for tid, block in blocks:
        first_line = block.split("\n", 1)[0]
        title = re.sub(r"^- \*\*[^*]+\*\* \[[^\]]*\]\s*", "", first_line)[:70]
        path = _target(root, f"specs/tasks/{tid}.md")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as fh:
            fh.write(_front({"id": tid, "title": title, "type": "task", "status": "draft", "risk": plan["risk"]})
                     + f"## Task\n\n{block}")
        written.append(path.relative_to(root).as_posix())
    return written


def collect(root: Path | str, run_id: str, reply: str | None = None) -> dict:
    """Validate the Architect's reply and write it as a draft."""
    root = Path(root).resolve()
    try:
        log = RunLog(root, "descend", run_id)
    except ValueError as exc:
        raise DescendError(str(exc)) from exc
    start = next((r for r in log.records() if r.get("step") == "start"), None)
    if start is None:
        raise DescendError(f"no prepared descend run {run_id}")
    if any(r.get("step") == "write" for r in log.records()):
        raise DescendError(f"run {run_id} was already collected")
    if reply is None:
        result = log.path.with_suffix("") / RESULT
        if not result.is_file():
            raise DescendError(f"save the Architect's reply to {result.relative_to(root).as_posix()} first")
        reply = result.read_text(encoding="utf-8-sig")
    repo = store.load(root)
    parent = str(start.get("parent", ""))
    if ids.kind_of(parent) not in ("system", "component"):
        raise DescendError(f"run {run_id} names no valid parent")
    plan = _plan(root, repo, parent)  # never trust the run log: re-derive parent status, IDs, paths and risk
    text = _strip_fence(reply)
    questions = [ln[len("> Open question:"):].strip() for ln in text.split("\n") if ln.startswith("> Open question:")]
    files = (_write_component if plan["child"] == "component" else _write_tasks)(root, repo, plan, text)
    new_ids = sorted({r for r in store.load(root).requirements} - set(repo.requirements), key=ids.sort_key)
    log.append("write", status="done", files=files, ids=new_ids)
    if plan["child"] == "component":
        target = plan["component"]
    elif plan.get("lite"):
        target = str(repo.file_of[plan["parent"]].id)
    else:
        target = new_ids[0] if new_ids else plan["parent"]
    return {"parent": plan["parent"], "files": files, "ids": new_ids, "open_questions": questions,
            "next": f"sparkwright review {target}"}


def run(root: Path | str, parent: str, router) -> dict:
    """Runner mode: prepare, call the Architect through the router, collect."""
    root = Path(root).resolve()
    prep = prepare(root, parent)
    prompt = (root / prep["prompt"]).read_text(encoding="utf-8").split("\n\n", 1)[1]
    res = router.call(load_all(root)["architect"], prompt, max_tokens=12000)
    RunLog(root, "descend", prep["run_id"]).append("call:architect", status="done", tier=res.tier, model=res.model,
                                                    cost_usd=round(res.cost_usd, 6))
    out = collect(root, prep["run_id"], res.text)
    out["run_id"] = prep["run_id"]
    return out
