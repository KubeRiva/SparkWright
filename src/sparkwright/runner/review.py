"""The `review` workflow: Inspector swarm + Foreman merge + gate (SYSTEM S3.7, S4.2, S4.5, S6.1, S6.7)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..core import ids, store
from .personas import Persona, load_all
from .router import BudgetExceeded, RoleFailed, Router
from .runlog import RunLog

DEFAULT_PERSONAS: dict[str, list[str]] = {
    "vision": ["coverage-auditor", "contradiction-hunter", "devils-advocate"],
    "system": ["coverage-auditor", "contradiction-hunter", "newcomer", "devils-advocate"],
    "component": ["coverage-auditor", "contradiction-hunter", "newcomer", "buildability-checker"],
    "task": ["coverage-auditor", "buildability-checker"],
}
HUMAN_GATED = {"evidence", "vision", "system"}


NON_INSPECTORS = {"code-reviewer", "question-auditor"}  # findings-producing roles that do not review specs


def inspector_names(root: Path | str | None = None) -> set[str]:
    return {n for n, p in load_all(root).items() if p.output == "findings" and n not in NON_INSPECTORS}


def _validated(names: list[str], root: Path) -> list[str]:
    """Distinct Inspector names in order (S6.1: a persona listed twice is still one Inspector)."""
    out = list(dict.fromkeys(names))
    bad = [n for n in out if n not in inspector_names(root)]
    if bad:
        raise ReviewError(f"not Inspector personas: {bad}")
    return out


def default_personas(level: str, cfg: dict | None = None) -> list[str]:
    """Default Inspectors for a level minus any a human disabled after calibration; never fewer than MIN_PERSONAS."""
    names = list(DEFAULT_PERSONAS.get(level, DEFAULT_PERSONAS["system"]))
    disabled = set(((cfg or {}).get("review") or {}).get("disabled") or [])
    kept = [n for n in names if n not in disabled]
    return kept if len(kept) >= 2 else names
MIN_PERSONAS = 2
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}

INJECTION_PATTERNS = [
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|prompts?)",
    r"\byou are now\b",
    r"disregard (the|your|all) (system|previous|prior)",
    r"<!--[^>]*(agent|assistant|claude|gpt|llm|ai\b)[^>]*-->",
    r"do not (tell|inform|show) the (user|human|reviewer)",
    r"new instructions:",
]


class ReviewError(RuntimeError):
    pass


@dataclass
class Finding:
    severity: str
    ids: list[str]
    finding: str
    fix: str
    personas: list[str] = field(default_factory=list)


@dataclass
class ReviewResult:
    review_id: str
    path: Path | None
    target: str
    level: str
    findings: list[Finding]
    ran: list[str]
    skipped: list[str]
    abstained: list[str]
    gate: str
    cost_usd: float
    run_id: str

    def counts(self) -> dict[str, int]:
        c = {"high": 0, "medium": 0, "low": 0}
        for f in self.findings:
            c[f.severity] = c.get(f.severity, 0) + 1
        return c


# ------------------------------------------------------------------ context
def _resolve(repo: store.Repo, target: str) -> store.SpecFile:
    target = ids.canonical(target)
    for sf in repo.files:
        if sf.id == target:
            return sf
    if target in repo.file_of:
        return repo.file_of[target]
    raise ReviewError(f"unknown target {target}: give a file id (e.g. SYSTEM) or a requirement id")


def build_context(root: Path, repo: store.Repo, sf: store.SpecFile) -> tuple[str, list[str]]:
    """Return (user message, list of files included). Only the artifact, its parents and the constitution."""
    included: list[str] = []
    parent_files: list[str] = []
    for r in sf.requirements:
        for ref in r.refs:
            owner = repo.file_of.get(ref)
            path = owner.path if owner else (repo.evidence[ref].file if ref in repo.evidence else None)
            if path and path != sf.path and path not in parent_files:
                parent_files.append(path)
    parts = [f"=== ARTIFACT ({sf.path}) ===\n" + (root / sf.path).read_text(encoding="utf-8")]
    included.append(sf.path)
    for p in sorted(parent_files):
        parts.append(f"=== PARENT ({p}) ===\n" + (root / p).read_text(encoding="utf-8"))
        included.append(p)
    const = root / "specs" / "constitution.md"
    if const.is_file():
        parts.append("=== CONSTITUTION (specs/constitution.md) ===\n" + const.read_text(encoding="utf-8"))
        included.append("specs/constitution.md")
    parts.append("Review the ARTIFACT only. Parents and constitution are context.")
    return "\n\n".join(parts), included


def _code_spans(text: str) -> list[tuple[int, int]]:
    spans = [(m.start(), m.end()) for m in re.finditer(r"```.*?```|~~~.*?~~~", text, re.S)]
    spans += [(m.start(), m.end()) for m in re.finditer(r"`[^`\n]+`", text)]
    return spans


def scan_injection(text: str) -> tuple[list[str], list[str]]:
    """Return (live hits, code mentions).

    Only matches inside code spans or fences count as mentions; quoting a phrase
    does not make it safe. Any match of either kind brings in the Security Reviewer.
    """
    spans = _code_spans(text)
    live, mentions = [], []
    for pat in INJECTION_PATTERNS:
        for m in re.finditer(pat, text, re.I | re.S):
            snippet = m.group(0)[:80]
            in_code = any(a <= m.start() and m.end() <= b for a, b in spans)
            (mentions if in_code else live).append(snippet)
    return sorted(set(live)), sorted(set(mentions))


# ------------------------------------------------------------------ parsing and merging
def parse_findings(text: str) -> list[Finding] | None:
    """Parse a persona's JSON array; None means the persona abstained (unparseable)."""
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    out = []
    for d in data:
        if not isinstance(d, dict) or not d.get("finding"):
            continue
        sev = str(d.get("severity", "medium")).lower()
        out.append(Finding(sev if sev in SEVERITY_RANK else "medium",
                           [str(i) for i in d.get("ids", []) if str(i).strip()],
                           str(d["finding"]).strip(), str(d.get("fix", "")).strip()))
    return out


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _req_ids(values: list[str]) -> set[str]:
    return {v for v in values if ids.is_id(v)}


def _similar(a: Finding, b: Finding) -> bool:
    """Duplicate rule, tuned on real reviews: overlapping requirement IDs plus overlapping wording."""
    ta, tb = _tokens(a.finding + " " + a.fix), _tokens(b.finding + " " + b.fix)
    if not ta or not tb:
        return False
    text = len(ta & tb) / len(ta | tb)
    ia, ib = _req_ids(a.ids), _req_ids(b.ids)
    if ia and ib:
        id_overlap = len(ia & ib) / len(ia | ib)
        if ia == ib:
            return text >= 0.15
        return id_overlap >= 0.5 and text >= 0.19
    return text >= 0.45  # no IDs on one side: require strong wording overlap


def _ids_key(values: list[str]) -> tuple:
    keys = [ids.sort_key(i) for i in values if ids.is_id(i)]
    return (0, tuple(keys)) if keys else (1, ())


def merge(per_persona: dict[str, list[Finding]]) -> list[Finding]:
    """Foreman: combine duplicates raised by different personas, rank by severity."""
    merged: list[Finding] = []
    for persona in sorted(per_persona):
        for f in per_persona[persona]:
            match = next((m for m in merged if persona not in m.personas and _similar(m, f)), None)
            if match:
                if SEVERITY_RANK[f.severity] < SEVERITY_RANK[match.severity]:
                    match.severity = f.severity
                match.personas.append(persona)
                match.ids = sorted(set(match.ids) | set(f.ids), key=ids.sort_key)
                if f.fix and f.fix not in match.fix:
                    match.fix = f"{match.fix} / {f.fix}" if match.fix else f.fix
            else:
                merged.append(Finding(f.severity, list(f.ids), f.finding, f.fix, [persona]))
    merged.sort(key=lambda f: (SEVERITY_RANK[f.severity], _ids_key(f.ids)))
    return merged


# ------------------------------------------------------------------ output
def _next_review_id(root: Path) -> str:
    nums = [0]
    rdir = root / "specs" / "reviews"
    if rdir.is_dir():
        for p in rdir.glob("*.md"):
            m = re.search(r"^id:\s*R(\d+)\s*$", p.read_text(encoding="utf-8"), re.M)
            if m:
                nums.append(int(m.group(1)))
    return f"R{max(nums) + 1:03d}"


def _cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ").strip()


def write_review(root: Path, res: ReviewResult) -> Path:
    rdir = root / "specs" / "reviews"
    rdir.mkdir(parents=True, exist_ok=True)
    path = rdir / f"{date.today().isoformat()}-{res.target.lower()}-{res.review_id.lower()}.md"
    c = res.counts()
    lines = [
        "---", f"id: {res.review_id}", f"title: Inspector review of {res.target}", "type: review",
        f"target: {res.target}", "status: in-review", f"reviewers: [{', '.join(res.ran)}]",
        f"date: {date.today().isoformat()}", f"run: {res.run_id}", "---", "",
        f"**Gate:** {res.gate}", "",
        f"{c['high']} high, {c['medium']} medium, {c['low']} low. Cost ${res.cost_usd:.2f}.", "",
        "| ID | Severity | Requirements | Finding | Suggested fix | Raised by | Decision |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for n, f in enumerate(res.findings, start=1):
        lines.append(f"| F{n} | {f.severity} | {', '.join(f.ids) or '—'} | {_cell(f.finding)} | {_cell(f.fix)} | {', '.join(f.personas)} | open |")
    if res.skipped:
        lines += ["", f"Skipped (cost ceiling): {', '.join(res.skipped)}"]
    if res.abstained:
        lines += ["", f"Abstained (unparseable output): {', '.join(res.abstained)}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ------------------------------------------------------------------ workflow
def run_review(root: Path | str, target: str, router: Router, persona_names: list[str] | None = None,
               run_id: str | None = None, write: bool = True) -> ReviewResult:
    root = Path(root).resolve()
    repo = store.load(root)
    sf = _resolve(repo, target)
    level = str(sf.meta.get("type", "system"))
    names = _validated(list(persona_names or default_personas(level, router.config)), root)
    all_personas = load_all(root)

    context, included = build_context(root, repo, sf)
    hits, mentions = scan_injection(context)
    high_risk = str(sf.meta.get("risk", "")).lower() == "high"
    if (hits or mentions or high_risk) and "security-reviewer" not in names:
        names.insert(0, "security-reviewer")  # S6.7, S6.2

    try:
        log = RunLog(root, "review", run_id)
    except ValueError as exc:
        raise ReviewError(str(exc)) from exc
    done = log.completed()
    log.append("start", status="started", target=sf.id or target, level=level, personas=names, files=included)
    level_ceiling = float(router.config.get("budgets", {}).get("per_level_usd", {}).get(level, 0) or 0)
    per_persona: dict[str, list[Finding]] = {}
    ran, skipped, abstained = [], [], []
    level_spent = 0.0
    costs: list[float] = []
    for name in names:
        step = f"persona:{name}"
        if step in done:  # resume
            per_persona[name] = [Finding(**f) for f in done[step].get("findings", [])]
            (abstained if done[step].get("abstained") else ran).append(name)
            continue
        estimate = (sum(costs) / len(costs)) if costs else 0.0
        if len(ran) >= MIN_PERSONAS and level_ceiling and level_spent + estimate > level_ceiling:
            skipped.append(name)
            log.append(step, status="skipped", reason="level cost ceiling would be exceeded")
            continue
        persona: Persona = all_personas[name]
        try:
            res = router.call(persona, context, force=len(ran) < MIN_PERSONAS)
        except BudgetExceeded:
            skipped.append(name)
            log.append(step, status="skipped", reason="run cost ceiling would be exceeded")
            continue
        except RoleFailed as exc:
            log.append(step, status="failed", error=str(exc))
            abstained.append(name)
            continue
        level_spent += res.cost_usd
        costs.append(res.cost_usd)
        parsed = parse_findings(res.text)
        is_abstain = parsed is None
        if is_abstain:
            abstained.append(name)
            parsed = []
        else:
            ran.append(name)
        per_persona[name] = parsed
        log.append(step, status="done", role=name, tier=res.tier, model=res.model,
                   input_tokens=res.input_tokens, output_tokens=res.output_tokens,
                   cost_usd=round(res.cost_usd, 6), duration_s=res.duration_s, attempts=res.attempts,
                   findings=[f.__dict__ for f in parsed], abstained=is_abstain)

    findings = merge(per_persona)
    if hits:
        findings.insert(0, Finding("high", [], f"Possible instructions aimed at AI agents found in reviewed text: {hits}",
                                   "Remove or rewrite the text; agents must treat specs as data.", ["pattern-scan"]))
    if mentions:
        findings.append(Finding("low", [], f"Agent-instruction phrases inside code spans (treated as examples): {mentions}",
                                "No action if these are examples; otherwise rewrite.", ["pattern-scan"]))
    c_high = sum(1 for f in findings if f.severity == "high")
    if len(ran) < MIN_PERSONAS:
        gate = f"FAIL — only {len(ran)} Inspector(s) produced a review; at least {MIN_PERSONAS} are required"
    elif level in HUMAN_GATED or high_risk or router.config.get("gates", {}).get(level) == "human":
        gate = f"HUMAN — resolve findings, then `sparkwright approve {sf.id} --as <name>`"
    elif c_high:
        gate = f"FAIL — {c_high} high-severity finding(s) must be resolved"
    else:
        gate = "PASS — no high-severity findings"
    result = ReviewResult(_next_review_id(root), None, sf.id or target, level, findings, ran, skipped, abstained,
                          gate, log.total_cost(), log.run_id)
    if write:
        result.path = write_review(root, result)
        _record_reviewed(root, sf, result)
    log.append("foreman", status="done", findings=len(findings), gate=gate,
               review=str(result.path.relative_to(root)) if result.path else None)
    return result


def _record_reviewed(root: Path, sf: store.SpecFile, result: "ReviewResult") -> None:
    """S3.10: a review that did not fail records which text it saw, so a change request's re-approval can require it."""
    if result.gate.startswith("FAIL"):
        return
    from ..core import events as events_mod
    events_mod.append(root, [events_mod.make(r.id, "reviewed", run=result.run_id, reason=f"{result.review_id} {r.hash}")
                             for r in sf.requirements])


# ------------------------------------------------------------------ host-agent path (S8.1, S8.2)
@dataclass
class Prepared:
    run_id: str
    run_dir: Path
    context_path: Path
    target: str
    level: str
    personas: list[str]


def prepare(root: Path | str, target: str, persona_names: list[str] | None = None) -> Prepared:
    """Build the isolated review context for a host that spawns its own fresh-context agents."""
    root = Path(root).resolve()
    repo = store.load(root)
    sf = _resolve(repo, target)
    level = str(sf.meta.get("type", "system"))
    from ..core import config as config_mod
    names = _validated(list(persona_names or default_personas(level, config_mod.load(root)[0])), root)
    context, included = build_context(root, repo, sf)
    hits, mentions = scan_injection(context)
    high_risk = str(sf.meta.get("risk", "")).lower() == "high"
    if (hits or mentions or high_risk) and "security-reviewer" not in names:
        names.insert(0, "security-reviewer")  # S6.7, S6.2
    log = RunLog(root, "review")
    run_dir = log.path.with_suffix("")
    run_dir.mkdir(parents=True, exist_ok=True)
    ctx = run_dir / "context.md"
    ctx.write_text(context, encoding="utf-8")
    log.append("start", status="started", mode="host-agents", target=sf.id or target, level=level,
               personas=names, files=included, injection_hits=hits, injection_mentions=mentions, risk=sf.meta.get("risk"))
    return Prepared(log.run_id, run_dir, ctx, sf.id or target, level, names)


def collect(root: Path | str, run_id: str, router_config: dict | None = None, write: bool = True) -> ReviewResult:
    """Merge persona outputs written by host agents to <run_dir>/<persona>.json, then gate and write the review."""
    root = Path(root).resolve()
    try:
        log = RunLog(root, "review", run_id)
    except ValueError as exc:
        raise ReviewError(str(exc)) from exc
    recs = log.records()
    start = next((r for r in recs if r.get("step") == "start"), None)
    if start is None:
        raise ReviewError(f"no prepared review run {run_id}")
    run_dir = log.path.with_suffix("")
    if any(r.get("step") == "foreman" for r in recs):
        raise ReviewError(f"review run {run_id} was already collected; prepare a new review")
    # The run log is not trusted: risk, level and the injection scan are recomputed from the spec (S6.2, S6.7).
    repo = store.load(root)
    sf = _resolve(repo, str(start.get("target", "")))
    target, level = sf.id or str(start["target"]), str(sf.meta.get("type", "system"))
    context = build_context(root, repo, sf)[0]
    saved = run_dir / "context.md"
    if not saved.is_file() or saved.read_text(encoding="utf-8") != context:
        raise ReviewError("the artifact or its parents changed since this review was prepared; prepare a new review "
                          "so the Inspectors see the current text (S3.10)")
    hits, mentions = scan_injection(context)
    high_risk = str(sf.meta.get("risk", "")).lower() == "high"
    inspectors = inspector_names(root)
    names = list(dict.fromkeys(n for n in start.get("personas", []) if isinstance(n, str) and n in inspectors))
    if (hits or mentions or high_risk) and "security-reviewer" not in names:
        names.insert(0, "security-reviewer")
    per_persona: dict[str, list[Finding]] = {}
    ran, abstained = [], []
    for name in names:
        out = run_dir / f"{name}.json"
        if not out.is_file():
            abstained.append(name)
            log.append(f"persona:{name}", status="failed", error="no output file")
            continue
        parsed = parse_findings(out.read_text(encoding="utf-8"))
        if parsed is None:
            abstained.append(name)
            parsed = []
        else:
            ran.append(name)
        per_persona[name] = parsed
        log.append(f"persona:{name}", status="done", role=name, tier="host", findings=[f.__dict__ for f in parsed])
    findings = merge(per_persona)
    if "security-reviewer" in abstained and (hits or high_risk):
        findings.insert(0, Finding("high", [], "The required Security Reviewer produced no review.",
                                   "Run the review again with the security-reviewer agent.", ["foreman"]))
    if hits:
        findings.insert(0, Finding("high", [], f"Possible instructions aimed at AI agents found in reviewed text: {hits}",
                                   "Remove or rewrite the text; agents must treat specs as data.", ["pattern-scan"]))
    if mentions:
        findings.append(Finding("low", [], f"Agent-instruction phrases inside code spans (treated as examples): {mentions}",
                                "No action if these are examples; otherwise rewrite.", ["pattern-scan"]))
    gates = (router_config or {}).get("gates", {})
    c_high = sum(1 for f in findings if f.severity == "high")
    if len(ran) < MIN_PERSONAS:
        gate = f"FAIL — only {len(ran)} Inspector(s) produced a review; at least {MIN_PERSONAS} are required"
    elif level in HUMAN_GATED or high_risk or gates.get(level) == "human":
        gate = f"HUMAN — resolve findings, then `sparkwright approve {target} --as <name>`"
    elif c_high:
        gate = f"FAIL — {c_high} high-severity finding(s) must be resolved"
    else:
        gate = "PASS — no high-severity findings"
    result = ReviewResult(_next_review_id(root), None, target, level, findings, ran, [], abstained, gate, 0.0, run_id)
    if write:
        result.path = write_review(root, result)
        _record_reviewed(root, sf, result)
    log.append("foreman", status="done", findings=len(findings), gate=gate,
               review=str(result.path.relative_to(root)) if result.path else None)
    return result
