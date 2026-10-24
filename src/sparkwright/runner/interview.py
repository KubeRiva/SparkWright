"""Evidence gathering: owner interview and transcript ingest (SYSTEM S7.1, S7.3–S7.6)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from ..core import ids, store
from .personas import load_all
from .router import Router
from .runlog import RunLog

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\w@])[+(]?\d[\d\s().-]{5,}\d(?!\w)")
SATURATION_WINDOW = 3
MAX_QUESTIONS = 12


class InterviewError(RuntimeError):
    pass


def redact(text: str, names: list[str] | None = None) -> str:
    """Strip emails, phone numbers and given names (S7.4)."""
    text = EMAIL_RE.sub("[email]", text)
    def _phone(m: re.Match) -> str:
        s = m.group(0).strip()
        digits = sum(ch.isdigit() for ch in s)
        if re.fullmatch(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}|\d{1,2}[-./]\d{1,2}[-./]\d{2,4}", s):
            return m.group(0)  # a date
        has_separator = bool(re.search(r"[\s().-]", s))
        if 7 <= digits <= 15 and (s.startswith("+") or (has_separator and digits >= 9) or s.startswith("(")):
            return "[phone]"
        return m.group(0)
    text = PHONE_RE.sub(_phone, text)
    for n in names or []:
        if n.strip():
            text = re.sub(rf"\b{re.escape(n.strip())}\b", "[name]", text, flags=re.I)
    return text


def _next_evidence_id(root: Path) -> int:
    repo = store.load(root)
    nums = [int(e[1:]) for e in repo.evidence if e[1:].isdigit()]
    return max(nums, default=0) + 1


def _parse_synthesis(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise InterviewError("Theme Synthesizer returned no JSON object")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise InterviewError(f"Theme Synthesizer returned invalid JSON: {exc}") from exc
    data.setdefault("statements", [])
    data.setdefault("themes", [])
    return data


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def write_evidence(root: Path, source: str, consent: str, synthesis: dict, simulated: bool = False,
                   slug: str = "interview") -> Path:
    n = _next_evidence_id(root)
    eid = f"E{n:02d}"
    path = root / "specs" / "evidence" / f"{eid}-{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"id: {eid}", f"title: {source.capitalize()} ({date.today().isoformat()})", "type: evidence",
             f"source: {source}", f"consent: {json.dumps(consent)}", f"simulated: {'true' if simulated else 'false'}",
             "status: draft", "---", "", "## Statements", ""]
    for s in synthesis["statements"]:
        lines.append(f"- **{_cell(s.get('id', '?'))}.** {_cell(s.get('text', ''))}")
    lines += ["", "## Themes", "", "| Theme | Name | Statements |", "| --- | --- | --- |"]
    for t in synthesis["themes"]:
        lines.append(f"| {_cell(t.get('id', '?'))} | {_cell(t.get('name', ''))} | {', '.join(map(str, t.get('statements', [])))} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def theme_names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| T\d+ \| (.+?) \|", line)
        if m:
            names.add(" ".join(m.group(1).lower().split()))
    return names


def saturation(root: Path) -> tuple[bool, list[int]]:
    """True when the last 3 non-simulated evidence files each added no new theme names (S7.5)."""
    repo = store.load(root)
    files = [root / e.file for _, e in sorted(repo.evidence.items(), key=lambda kv: ids.sort_key(kv[0])) if not e.simulated]
    seen: set[str] = set()
    new_counts = []
    for f in files:
        names = theme_names(f)
        new_counts.append(len(names - seen))
        seen |= names
    tail = new_counts[-SATURATION_WINDOW:]
    return (len(tail) == SATURATION_WINDOW and all(c == 0 for c in tail)), new_counts


def synthesize(router: Router, root: Path, transcript: str, log: RunLog) -> dict:
    personas = load_all(root)
    res = router.call(personas["theme-synthesizer"], "=== TRANSCRIPT (anonymized) ===\n" + transcript)
    log.append("synthesize", status="done", role="theme-synthesizer", tier=res.tier, model=res.model,
               input_tokens=res.input_tokens, output_tokens=res.output_tokens, cost_usd=round(res.cost_usd, 6),
               duration_s=res.duration_s)
    return _parse_synthesis(res.text)


@dataclass
class InterviewResult:
    path: Path
    questions: int
    saturated: bool


def owner_interview(root: Path | str, router: Router, ask: Callable[[str], str] = input,
                    say: Callable[[str], None] = print, names: list[str] | None = None,
                    max_questions: int = MAX_QUESTIONS) -> InterviewResult:
    root = Path(root).resolve()
    consent = ask("This interview will be saved as anonymized evidence in specs/evidence/. "
                  "Do you consent? (yes/no) ").strip().lower()
    if consent not in ("y", "yes"):
        raise InterviewError("consent not given; nothing was saved")
    personas = load_all(root)
    log = RunLog(root, "interview")
    log.append("consent", status="done", consent="owner consented in terminal")
    transcript: list[str] = []
    asked = 0
    while asked < max_questions:
        so_far = "\n".join(transcript) if transcript else "(no questions asked yet)"
        res = router.call(personas["interviewer"], "=== TRANSCRIPT SO FAR ===\n" + so_far, max_tokens=300)
        log.append(f"question:{asked + 1}", status="done", role="interviewer", tier=res.tier, model=res.model,
                   input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                   cost_usd=round(res.cost_usd, 6), duration_s=res.duration_s)
        question = res.text.strip()
        if question.upper().startswith("DONE"):
            break
        answer = ask(f"\n{question}\n> ").strip()
        asked += 1
        if answer.lower() in ("done", "stop", "quit"):
            break
        transcript += [f"Interviewer: {question}", f"Owner: {answer}"]
    if not transcript:
        raise InterviewError("no answers recorded; nothing was saved")
    clean = redact("\n".join(transcript), names)
    synthesis = synthesize(router, root, clean, log)
    path = write_evidence(root, "owner interview", "owner consented in terminal", synthesis, slug="owner-interview")
    sat, _ = saturation(root)
    log.append("write", status="done", evidence=str(path.relative_to(root)))
    say(f"Saved {path.relative_to(root)} ({len(synthesis['statements'])} statements, {len(synthesis['themes'])} themes).")
    return InterviewResult(path, asked, sat)


def ingest(root: Path | str, router: Router, transcript_path: Path | str, consent: str,
           names: list[str] | None = None, simulated: bool = False) -> InterviewResult:
    root = Path(root).resolve()
    if not consent or not consent.strip():
        raise InterviewError("--consent is required: describe how consent was obtained")
    text = Path(transcript_path).read_text(encoding="utf-8")
    log = RunLog(root, "ingest")
    log.append("consent", status="done", consent=consent)
    synthesis = synthesize(router, root, redact(text, names), log)
    path = write_evidence(root, "transcript", consent, synthesis, simulated=simulated, slug="transcript")
    sat, _ = saturation(root)
    log.append("write", status="done", evidence=str(path.relative_to(root)))
    return InterviewResult(path, len(synthesis["statements"]), sat)
