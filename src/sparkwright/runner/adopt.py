"""Adopt an existing codebase (SYSTEM S2.7).

The Surveyor drafts System, Component and Task specs bottom-up from a deterministic inventory of
the code. The engine assigns every ID, writes everything as `status: draft`, records the current
commit as the baseline, and creates a draft Vision with an explicit assumption when none exists,
so the drafts trace upward while making clear nothing is backed by user evidence yet.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import re
import subprocess
from pathlib import Path

import yaml

from ..core import config as config_mod
from .personas import load_all
from .runlog import RunLog

SKIP = ("specs/", ".sparkwright/", ".git/", ".claude/", "node_modules/", "dist/", "build/", ".venv")
SOURCE = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".kt", ".cs", ".rb", ".rs", ".php", ".swift", ".scala"}
SIG_RE = re.compile(r"^\s*(export\s+)?(default\s+)?(async\s+)?(public\s+|private\s+|protected\s+)?(static\s+)?"
                    r"(function|class|interface|func|fn|def|type|struct|enum|const\s+\w+\s*=\s*\()\b.*")
MAX_CONTEXT = 120_000


class AdoptError(RuntimeError):
    pass


def _is_template(path: Path) -> bool:
    """True when the file is missing or still the untouched template written by `sparkwright init`."""
    if not path.exists():
        return True
    from importlib import resources
    tpl = resources.files("sparkwright") / "data" / "templates" / path.name
    try:
        return path.read_text(encoding="utf-8-sig").strip() == tpl.read_text(encoding="utf-8").strip()
    except OSError:
        return False


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise AdoptError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def _py_summary(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    out = []
    doc = ast.get_docstring(tree)
    if doc:
        out.append(f"  module: {doc.strip().splitlines()[0][:160]}")
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            d = ast.get_docstring(node)
            if isinstance(node, ast.ClassDef):
                sig = f"class {node.name}"
                methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and not n.name.startswith("_")]
                if methods:
                    sig += f" (methods: {', '.join(methods[:12])})"
            else:
                sig = f"def {node.name}({', '.join(a.arg for a in node.args.args)})"
            out.append(f"  {sig}" + (f" — {d.strip().splitlines()[0][:140]}" if d else ""))
    return out[:30]


def inventory(root: Path, paths: list[str] | None = None, test_globs: list[str] | None = None) -> tuple[str, list[str]]:
    files = [f for f in _git(root, "ls-files").splitlines() if f and not f.startswith(SKIP)]
    if paths:
        files = [f for f in files if any(f == p or f.startswith(p.rstrip("/") + "/") for p in paths)]
    tests = [f for f in files if any(fnmatch.fnmatch(f, g) for g in (test_globs or []))]
    lines, size = [], 0
    for f in files:
        entry = [f]
        if f not in tests and Path(f).suffix in SOURCE:
            try:
                text = (root / f).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if f.endswith(".py"):
                entry += _py_summary(text)
            else:
                entry += [f"  {m.group(0).strip()[:160]}" for m in map(SIG_RE.match, text.splitlines()) if m][:20]
        block = "\n".join(entry)
        if size + len(block) > MAX_CONTEXT:
            lines.append(f"{f}  (details omitted: inventory size limit)")
            continue
        size += len(block)
        lines.append(block)
    return "\n".join(lines), files


def prepare(root: Path | str, paths: list[str] | None = None) -> dict:
    root = Path(root).resolve()
    if not _is_template(root / "specs" / "system.md"):
        raise AdoptError("specs/system.md already has content; adopt drafts specs for a codebase that has none")
    cfg, errors = config_mod.load(root)
    if errors:
        raise AdoptError("; ".join(errors))
    inv, files = inventory(root, paths, cfg.get("test_globs"))
    if not files:
        raise AdoptError("no tracked source files found" + (f" under {paths}" if paths else ""))
    log = RunLog(root, "adopt")
    run_dir = log.path.with_suffix("")
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt = run_dir / "surveyor.md"
    prompt.write_text(load_all(root)["surveyor"].system_prompt() + "\n=== CODE INVENTORY ===\n" + inv, encoding="utf-8")
    head = _git(root, "rev-parse", "HEAD").strip()
    log.append("start", status="started", head=head, paths=paths or [])
    return {"run_id": log.run_id, "prompt": str(prompt.relative_to(root)),
            "result_file": str((run_dir / "surveyor.json").relative_to(root)),
            "then": f"sparkwright adopt --collect {log.run_id}"}


def _parse(text: str) -> dict:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    try:
        data = json.loads(t)
    except json.JSONDecodeError as exc:
        raise AdoptError(f"Surveyor reply is not JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("system"), list) or not isinstance(data.get("components"), list):
        raise AdoptError("Surveyor reply needs 'system' and 'components' lists")
    return data


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "component"


def _front(meta: dict) -> str:
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n"


def _set_baseline(root: Path, head: str) -> bool:
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(head)):
        raise AdoptError("invalid baseline commit in the run log")
    cfg = root / ".sparkwright" / "config.yaml"
    text = cfg.read_text(encoding="utf-8") if cfg.is_file() else ""
    if re.search(r"^baseline:\s*(null|~)?\s*(#.*)?$", text, re.M):
        cfg.write_text(re.sub(r"^baseline:\s*(null|~)?\s*(#.*)?$", lambda _m: f"baseline: {head}  # recorded by adopt",
                              text, count=1, flags=re.M), encoding="utf-8")
        return True
    if not re.search(r"^baseline:", text, re.M):
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(text + ("" if text.endswith("\n") or not text else "\n") + f"baseline: {head}  # recorded by adopt\n",
                       encoding="utf-8")
        return True
    return False


def collect(root: Path | str, run_id: str, reply: str | None = None) -> dict:
    root = Path(root).resolve()
    try:
        log = RunLog(root, "adopt", run_id)
    except ValueError as exc:
        raise AdoptError(str(exc)) from exc
    recs = log.records()
    start = next((r for r in recs if r.get("step") == "start"), None)
    if start is None:
        raise AdoptError(f"no prepared adopt run {run_id}")
    if any(r.get("step") == "write" for r in recs):
        raise AdoptError(f"run {run_id} was already collected")
    if not _is_template(root / "specs" / "system.md"):
        raise AdoptError("specs/system.md already has content")
    if reply is None:
        res = log.path.with_suffix("") / "surveyor.json"
        if not res.is_file():
            raise AdoptError(f"save the Surveyor's reply to {res.relative_to(root).as_posix()} first")
        reply = res.read_text(encoding="utf-8-sig")
    data = _parse(reply)
    tracked = [f for f in _git(root, "ls-files").splitlines() if f]
    warnings: list[str] = []
    written: list[str] = []
    specs = root / "specs"

    # System: groups -> S<g>.<k>
    sys_ids: dict[tuple[int, int], str] = {}
    sys_lines = []
    for g, group in enumerate(data["system"], 1):
        if not isinstance(group, dict):
            continue
        sys_lines.append(f"\n### S{g} — {_clean(group.get('title')) or f'Group {g}'}\n")
        for k, text in enumerate(group.get("requirements") or [], 1):
            if _clean(text):
                sys_ids[(g, k)] = f"S{g}.{k}"
                sys_lines.append(f"- **S{g}.{k}** [V1] {_clean(text)}")
    if not sys_ids:
        raise AdoptError("the Surveyor proposed no system requirements")

    # Components and tasks
    comps = []
    for n, comp in enumerate([c for c in data["components"] if isinstance(c, dict)], 1):
        reqs, tasks, minor_count = [], [], {}
        for item in comp.get("requirements") or []:
            if not isinstance(item, dict) or not _clean(item.get("text")):
                continue
            ref = item.get("system") or []
            key = (int(ref[0]), int(ref[1])) if isinstance(ref, list) and len(ref) == 2 and all(
                isinstance(x, int) for x in ref) else None
            if key not in sys_ids:
                warnings.append(f"component {n}: requirement without a valid system reference was dropped")
                continue
            sid = sys_ids[key]
            minor = sid.split(".")[1]
            minor_count[minor] = minor_count.get(minor, 0) + 1
            cid = f"C{n}.{minor}.{minor_count[minor]}"
            reqs.append(f"- **{cid}** [{sid}] {_clean(item['text'])}")
            globs = [str(g) for g in (item.get("files") or []) if isinstance(g, str)]
            good = [g for g in globs if any(fnmatch.fnmatch(t, g) or t == g for t in tracked)
                    and not g.startswith(("specs/", ".sparkwright/", "/")) and ".." not in g]
            if len(good) != len(globs):
                warnings.append(f"{cid}: dropped file globs that match nothing: {sorted(set(globs) - set(good))}")
            if good:
                tasks.append(f"- **{cid}.T1** [{cid}] Existing implementation of {cid} (adopted; verify and add tests).\n\n"
                             f"```yaml\nfiles: {json.dumps(good)}\n```")
            else:
                warnings.append(f"{cid}: no task drafted because no files were named")
        if not reqs:
            warnings.append(f"component {n} ({_clean(comp.get('title'))}) had no valid requirements and was skipped")
            continue
        comps.append((n, comp, reqs, tasks))

    # Write: vision (if missing), system, components
    if _is_template(specs / "vision.md"):
        purpose = _clean(data.get("purpose")) or "Purpose not yet stated."
        (specs).mkdir(parents=True, exist_ok=True)
        (specs / "vision.md").write_text(
            _front({"id": "VISION", "title": "Vision (drafted by adopt from existing code)", "type": "vision",
                    "status": "draft", "risk": "high"})
            + "## Requirements\n\n"
            f"- **V1** [A1] {purpose}\n\n## Assumptions (not yet backed by user evidence)\n\n"
            "- **A1** [] The purpose above was inferred from the code by `sparkwright adopt`. "
            "*Validate with an owner interview (`sparkwright interview owner`).*\n", encoding="utf-8")
        written.append("specs/vision.md")
    (specs / "system.md").write_text(
        _front({"id": "SYSTEM", "title": "System (drafted by adopt from existing code)", "type": "system",
                "status": "draft", "risk": "high"})
        + "## Overview\n\nDrafted bottom-up from the existing code. Correct it before approving.\n\n## Requirements\n"
        + "\n".join(sys_lines) + "\n", encoding="utf-8")
    written.append("specs/system.md")
    (specs / "components").mkdir(parents=True, exist_ok=True)
    for n, comp, reqs, tasks in comps:
        title = _clean(comp.get("title"))[:80] or f"Component {n}"
        path = specs / "components" / f"C{n}-{_slug(title)}.md"
        body = (f"## Responsibility\n\n{_clean(comp.get('responsibility')) or 'TBD'}\n\n## Requirements\n\n"
                + "\n".join(reqs) + "\n\n## Tasks\n\n" + "\n\n".join(tasks) + "\n")
        with path.open("x", encoding="utf-8") as fh:
            fh.write(_front({"id": f"C{n}", "title": title, "type": "component", "status": "draft",
                             "risk": "medium", "lite": True, "adopted": True}) + body)
        written.append(path.relative_to(root).as_posix())
    baseline_set = _set_baseline(root, start["head"])
    log.append("write", status="done", files=written, warnings=warnings)
    return {"files": written, "warnings": warnings, "baseline": start["head"] if baseline_set else None,
            "next": "sparkwright review SYSTEM"}


def run(root: Path | str, router, paths: list[str] | None = None) -> dict:
    root = Path(root).resolve()
    prep = prepare(root, paths)
    body = (root / prep["prompt"]).read_text(encoding="utf-8").split("\n\n", 1)[1]
    res = router.call(load_all(root)["surveyor"], body, max_tokens=16000)
    out = collect(root, prep["run_id"], res.text)
    out["run_id"] = prep["run_id"]
    return out
