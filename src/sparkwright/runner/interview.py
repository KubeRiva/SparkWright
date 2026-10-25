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


NAME_RE = re.compile(r"(?<![.!?:]\s)(?<!^)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", re.M)


def unredacted_names(text: str) -> list[str]:
    """D009 (S7.4): runs of two or more capitalised words that look like a person's full name and are still in
    the text after redaction. A heuristic: a human confirms with --redact or --keep-names."""
    found = []
    for m in NAME_RE.finditer(text):
        words = m.group(1).split()
        if len(words) <= 4 and m.group(1) not in found:
            found.append(m.group(1))
    return found[:20]


def _guard_names(text: str, keep_names: bool) -> None:
    left = [] if keep_names else unredacted_names(text)
    if left:
        raise InterviewError(f"the transcript still contains what look like personal names: {left}. Remove them with "
                             f"--redact \"Name One,Name Two\", or confirm they may be stored with --keep-names")


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
           names: list[str] | None = None, simulated: bool = False, keep_names: bool = False) -> InterviewResult:
    root = Path(root).resolve()
    if not consent or not consent.strip():
        raise InterviewError("--consent is required: describe how consent was obtained")
    text = Path(transcript_path).read_text(encoding="utf-8")
    log = RunLog(root, "ingest")
    log.append("consent", status="done", consent=consent)
    clean = redact(text, names)
    _guard_names(clean, keep_names)
    synthesis = synthesize(router, root, clean, log)
    path = write_evidence(root, "transcript", consent, synthesis, simulated=simulated, slug="transcript")
    sat, _ = saturation(root)
    log.append("write", status="done", evidence=str(path.relative_to(root)))
    return InterviewResult(path, len(synthesis["statements"]), sat)


# ------------------------------------------------------------------ host mode (no API key: the host's agents do the talking)
def host_owner(root: Path | str, consent: str) -> dict:
    """Prepare an owner interview run by the host agent in chat (S7.1, S8.2)."""
    root = Path(root).resolve()
    if not consent or not consent.strip():
        raise InterviewError("--consent is required: ask the owner for consent first and describe it")
    log = RunLog(root, "interview")
    run_dir = log.path.with_suffix("")
    run_dir.mkdir(parents=True, exist_ok=True)
    persona = load_all(root)["interviewer"]
    prompt = run_dir / "interviewer.md"
    prompt.write_text(
        persona.system_prompt() + "\n\n## Host mode\n\nYou are talking to the owner directly in chat. Ask one question per "
        "message and wait for the answer. When you would reply DONE, stop asking and write the whole conversation to "
        f"the transcript file below as alternating `Interviewer:` and `Owner:` lines.\n\nTranscript file: {run_dir / 'transcript.md'}\n",
        encoding="utf-8")
    log.append("consent", status="done", consent=consent)
    return {"run_id": log.run_id, "prompt": str(prompt.relative_to(root)),
            "transcript": str((run_dir / "transcript.md").relative_to(root)),
            "then": f"sparkwright interview ingest {(run_dir / 'transcript.md').relative_to(root).as_posix()} "
                    f"--consent \"{consent}\" --prepare"}


def prepare_ingest(root: Path | str, transcript_path: Path | str, consent: str, names: list[str] | None = None,
                   simulated: bool = False, keep_names: bool = False) -> dict:
    """Redact a transcript and write the Theme Synthesizer prompt for a fresh host agent."""
    root = Path(root).resolve()
    if not consent or not consent.strip():
        raise InterviewError("--consent is required: describe how consent was obtained")
    text = Path(transcript_path if Path(transcript_path).is_absolute() else root / transcript_path).read_text(encoding="utf-8")
    _guard_names(redact(text, names), keep_names)
    log = RunLog(root, "ingest")
    run_dir = log.path.with_suffix("")
    run_dir.mkdir(parents=True, exist_ok=True)
    persona = load_all(root)["theme-synthesizer"]
    prompt = run_dir / "theme-synthesizer.md"
    prompt.write_text(persona.system_prompt() + "\n\n=== TRANSCRIPT (anonymized) ===\n" + redact(text, names), encoding="utf-8")
    log.append("consent", status="done", consent=consent, simulated=simulated)
    result = run_dir / "theme-synthesizer.result.json"
    return {"run_id": log.run_id, "prompt": str(prompt.relative_to(root)), "result_file": str(result.relative_to(root)),
            "then": f"sparkwright interview collect {log.run_id}"}


def collect(root: Path | str, run_id: str) -> InterviewResult:
    root = Path(root).resolve()
    try:
        log = RunLog(root, "ingest", run_id)
    except ValueError as exc:
        raise InterviewError(str(exc)) from exc
    start = next((r for r in log.records() if r.get("step") == "consent"), None)
    if start is None:
        raise InterviewError(f"no prepared ingest run {run_id}")
    result = log.path.with_suffix("") / "theme-synthesizer.result.json"
    if not result.is_file():
        raise InterviewError(f"save the Theme Synthesizer's reply to {result.relative_to(root)} first")
    synthesis = _parse_synthesis(result.read_text(encoding="utf-8"))
    path = write_evidence(root, "transcript", start["consent"], synthesis, simulated=bool(start.get("simulated")),
                          slug="interview")
    sat, _ = saturation(root)
    log.append("write", status="done", evidence=str(path.relative_to(root)))
    return InterviewResult(path, len(synthesis["statements"]), sat)
