"""End-user interview guide (SYSTEM S7.2, S7.7).

A Guide Writer drafts the guide from the Vision, its assumptions and existing evidence themes;
a separate Question Auditor and a deterministic lint check it for leading questions. When the
target users include minors, a parental-consent section is inserted by the engine (not left to
the model) and the guide directs interviews to parents.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from .personas import load_all
from .review import Finding, parse_findings
from .runlog import RunLog

GUIDE_DIR = "specs/guides"
WRITER, AUDITOR = "guide-writer", "question-auditor"
MINOR_WORDS = re.compile(r"\b(minors?|child(ren)?|kids?|students?|pupils?|teen(ager)?s?|under[- ]?18|"
                         r"school|grade \d|years? old)\b", re.I)
LINT = [
    (re.compile(r"\b(would|will|could) you\b", re.I), "medium", "hypothetical or future-facing question"),
    (re.compile(r"\bif (we|you|there) (built|had|offered|made)\b", re.I), "high", "pitches a hypothetical solution"),
    (re.compile(r"\b(don't|doesn't|isn't|wouldn't|aren't) (you|it|that)\b", re.I), "high", "leading question"),
    (re.compile(r"\b(how much|what) would you pay\b|\bwilling to pay\b", re.I), "high", "asks about willingness to pay"),
    (re.compile(r"\bdo you (like|love|agree|think it would)\b", re.I), "high", "asks for an opinion of the idea"),
    (re.compile(r"\b(our|the) (app|product|tool|feature|solution)\b", re.I), "medium", "mentions the solution"),
]
MINORS_SECTION = """## Participants under 18 (required)

Some target users are minors. Do not interview a minor directly unless a
parent or legal guardian has given recorded consent and is present or
reachable during the session. Prefer interviewing the parent about the
child's experience. Record how parental consent was obtained; `sparkwright
interview ingest` requires it in `--consent`. Never record a child's full
name, school, age or date of birth in notes.
"""


class GuideError(RuntimeError):
    pass


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "users"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig") if p.is_file() else ""


def involves_minors(about: str, root: Path) -> bool:
    return bool(MINOR_WORDS.search(about) or MINOR_WORDS.search(_read(root / "specs" / "vision.md")))


def _context(root: Path, about: str, minors: bool) -> str:
    parts = [f"=== TARGET USERS AND TOPIC ===\n{about}"]
    vision = _read(root / "specs" / "vision.md")
    if vision:
        parts.append("=== VISION (the beliefs to test; do not reveal them to participants) ===\n" + vision)
    ev = sorted((root / "specs" / "evidence").glob("*.md")) if (root / "specs" / "evidence").is_dir() else []
    themes = []
    for p in ev:
        m = re.search(r"^## Themes\s*$(.*?)(?=^## |\Z)", _read(p), re.M | re.S)
        if m:
            themes.append(f"--- {p.name} ---\n{m.group(1).strip()}")
    if themes:
        parts.append("=== THEMES ALREADY HEARD ===\n" + "\n".join(themes))
    if minors:
        parts.append("=== MINORS ===\nTarget users include people under 18. Write questions for parents about their "
                     "child's experience; any question for a child must be simple, non-personal and asked with a parent present.")
    return "\n\n".join(parts)


def lint(text: str) -> list[Finding]:
    """Deterministic leading-question checks on question lines (numbered items and italic probes)."""
    out = []
    section = re.search(r"^## (Warm-up|Core questions).*?(?=^## (Wrap-up|Participants)|\Z)", text, re.M | re.S)
    body = text[section.start():] if section else text
    for line in body.splitlines():
        q = line.strip()
        if not re.match(r"^(\d+[.)]|[-*])\s+", q) and not q.startswith("_"):
            continue
        hits = [(sev, why) for rx, sev, why in LINT if rx.search(q)]
        if hits:
            sev = "high" if any(h[0] == "high" for h in hits) else "medium"
            why = "; ".join(dict.fromkeys(h[1] for h in hits))
            out.append(Finding(sev, [], f"{why}: \"{q[:160]}\"", "Ask about a specific past event instead.", ["lint"]))
    return out


def _guide_path(root: Path, about: str) -> Path:
    gdir = root / GUIDE_DIR
    gdir.mkdir(parents=True, exist_ok=True)
    base = f"{date.today().isoformat()}-{_slug(about)}"
    p, n = gdir / f"{base}.md", 2
    while p.exists():
        p, n = gdir / f"{base}-{n}.md", n + 1
    return p


def prepare(root: Path | str, about: str, minors: bool | None = None) -> dict:
    root = Path(root).resolve()
    if not about or not about.strip():
        raise GuideError("--about is required: who the users are and what to learn")
    minors = involves_minors(about, root) if minors is None else minors
    log = RunLog(root, "guide")
    run_dir = log.path.with_suffix("")
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt = run_dir / f"{WRITER}.md"
    prompt.write_text(load_all(root)[WRITER].system_prompt() + "\n" + _context(root, about, minors), encoding="utf-8", newline="\n")
    log.append("start", status="started", about=about[:500], minors=minors)
    return {"run_id": log.run_id, "step": WRITER, "prompt": str(prompt.relative_to(root)),
            "result_file": str((run_dir / f"{WRITER}.result.md").relative_to(root)),
            "minors": minors, "then": f"sparkwright interview guide {log.run_id}"}


def _write_guide(root: Path, log: RunLog, start: dict, draft: str) -> Path:
    draft = re.sub(r"^```(?:markdown|md)?\n|\n```\s*$", "", draft.strip())
    draft = re.sub(r"^---\n.*?\n---\n", "", draft, flags=re.S)  # the engine owns front matter
    if not re.search(r"^## Core questions", draft, re.M):
        raise GuideError("the guide has no '## Core questions' section")
    draft_involves_parents = bool(re.search(r"\b(parent|guardian)s?\b", draft, re.I))
    if start.get("minors"):
        draft = MINORS_SECTION + "\n" + draft.lstrip()
    path = _guide_path(root, start["about"])
    meta = {"id": f"guide-{path.stem}", "title": f"Interview guide: {start['about'][:80]}", "type": "guide",
            "status": "draft", "minors": bool(start.get("minors"))}
    path.write_text("---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + draft.strip() + "\n",
                    encoding="utf-8", newline="\n")
    log.append("write", status="done", guide=str(path.relative_to(root).as_posix()), parents=draft_involves_parents)
    return path


def _auditor_prompt(root: Path, run_dir: Path, guide: Path) -> Path:
    prompt = run_dir / f"{AUDITOR}.md"
    prompt.write_text(load_all(root)[AUDITOR].system_prompt() + "\n=== INTERVIEW GUIDE ===\n" + _read(guide), encoding="utf-8", newline="\n")
    return prompt


def _finish(root: Path, log: RunLog, guide: Path, audit: list[Finding], minors: bool, parents: bool) -> dict:
    findings = lint(_read(guide)) + audit
    if minors and not parents:  # judged on the writer's draft, before the engine's consent section was added
        findings.insert(0, Finding("high", [], "Target users include minors but the guide does not involve parents.",
                                   "Direct interviews to parents or require recorded parental consent (S7.7).", ["engine"]))
    high = [f for f in findings if f.severity == "high"]
    rows = "\n".join(f"| F{i} | {f.severity} | {f.finding.replace('|', '/')} | {f.fix.replace('|', '/')} | "
                     f"{', '.join(f.personas)} | open |" for i, f in enumerate(findings, 1)) or "| — | — | No findings | — | — | — |"
    text = _read(guide).rstrip("\n")
    text = re.sub(r"\n## Review\n.*\Z", "", text, flags=re.S)
    gate = "FAIL — rewrite the flagged questions, then run the review again" if high else "PASS — ready to use"
    text += ("\n\n## Review\n\n" + f"Gate: {gate}\n\n| ID | Severity | Finding | Suggested fix | Raised by | Decision |\n"
             "| --- | --- | --- | --- | --- | --- |\n" + rows + "\n")
    guide.write_text(text, encoding="utf-8", newline="\n")
    log.append("review", status="done", findings=len(findings), high=len(high))
    return {"guide": str(guide.relative_to(root).as_posix()), "findings": len(findings), "high": len(high), "gate": gate}


def advance(root: Path | str, run_id: str, writer_reply: str | None = None, auditor_reply: str | None = None) -> dict:
    """Host mode: write the guide from the writer's reply, then merge the auditor's reply. Call repeatedly."""
    root = Path(root).resolve()
    try:
        log = RunLog(root, "guide", run_id)
    except ValueError as exc:
        raise GuideError(str(exc)) from exc
    recs = log.records()
    start = next((r for r in recs if r.get("step") == "start"), None)
    if start is None:
        raise GuideError(f"no prepared guide run {run_id}")
    run_dir = log.path.with_suffix("")
    written = next((r for r in recs if r.get("step") == "write"), None)
    if written is None:
        res = run_dir / f"{WRITER}.result.md"
        if writer_reply is None:
            if not res.is_file():
                raise GuideError(f"save the Guide Writer's reply to {res.relative_to(root).as_posix()} first")
            writer_reply = res.read_text(encoding="utf-8-sig")
        guide = _write_guide(root, log, start, writer_reply)
        prompt = _auditor_prompt(root, run_dir, guide)
        if auditor_reply is None:
            return {"run_id": run_id, "step": AUDITOR, "guide": str(guide.relative_to(root).as_posix()),
                    "prompt": str(prompt.relative_to(root)),
                    "result_file": str((run_dir / f"{AUDITOR}.json").relative_to(root)),
                    "then": f"sparkwright interview guide {run_id}"}
    else:
        guide = root / written["guide"]
        if (root / GUIDE_DIR).resolve() not in guide.resolve().parents:
            raise GuideError("run log points outside specs/guides")
    if auditor_reply is None:
        res = run_dir / f"{AUDITOR}.json"
        if not res.is_file():
            raise GuideError(f"save the Question Auditor's reply to {res.relative_to(root).as_posix()} first")
        auditor_reply = res.read_text(encoding="utf-8-sig")
    audit = parse_findings(auditor_reply)
    if audit is None:
        audit = [Finding("high", [], "The Question Auditor's reply was not a JSON findings array.", "Run it again.", ["engine"])]
    for f in audit:
        f.personas = [AUDITOR]
    written = next((r for r in log.records() if r.get("step") == "write"), {})
    out = _finish(root, log, guide, audit, bool(start.get("minors")) or "Participants under 18" in _read(guide),
                  bool(written.get("parents")))
    out.update({"run_id": run_id, "step": "done"})
    return out


def run(root: Path | str, about: str, router, minors: bool | None = None) -> dict:
    root = Path(root).resolve()
    prep = prepare(root, about, minors)
    personas = load_all(root)
    body = lambda p: (root / p).read_text(encoding="utf-8").split("\n\n", 1)[1]  # noqa: E731
    w = router.call(personas[WRITER], body(prep["prompt"]), max_tokens=6000)
    mid = advance(root, prep["run_id"], writer_reply=w.text, auditor_reply=None)
    a = router.call(personas[AUDITOR], body(mid["prompt"]), max_tokens=4000)
    return advance(root, prep["run_id"], auditor_reply=a.text)
