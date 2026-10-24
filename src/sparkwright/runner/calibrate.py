"""Reviewer calibration (SYSTEM S10.1–S10.3).

Runs each Inspector persona on a suite of review contexts with planted flaws (and clean controls),
scores catch rate and false-alarm rate per persona and tier, writes specs/reviews/calibration.md,
and proposes disabling weak personas as a config change a human must make.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from ..core import config as config_mod
from ..core.frontmatter import split
from .personas import load_all
from .review import DEFAULT_PERSONAS, MIN_PERSONAS, Finding, parse_findings
from .runlog import RunLog
from .router import Router

INSPECTORS = ["coverage-auditor", "contradiction-hunter", "newcomer", "devils-advocate",
              "buildability-checker", "security-reviewer"]
REPORT = "specs/reviews/calibration.md"


class CalibrationError(RuntimeError):
    pass


@dataclass
class Case:
    id: str
    expect: list[str]
    ids: list[str]
    keywords: list[str]
    flaw: str | None
    context: str

    @property
    def clean(self) -> bool:
        return not self.expect


def load_cases(root: Path | None = None) -> list[Case]:
    """Built-in suite plus project cases in .sparkwright/calibration/*.md (same format)."""
    sources = [resources.files("sparkwright") / "data" / "calibration" / "cases"]
    if root is not None and (Path(root) / ".sparkwright" / "calibration").is_dir():
        sources.append(Path(root) / ".sparkwright" / "calibration")
    out: dict[str, Case] = {}
    for src in sources:
        for entry in sorted(src.iterdir(), key=lambda e: e.name):
            if not entry.name.endswith(".md"):
                continue
            meta, body, _ = split(entry.read_text(encoding="utf-8"))
            if not re.fullmatch(r"[a-z0-9-]+", str(meta.get("id", ""))):
                raise CalibrationError(f"calibration case {entry.name} needs an id of lowercase letters, digits and dashes")
            out[meta["id"]] = Case(str(meta["id"]), list(meta.get("expect") or []), [str(i) for i in meta.get("ids") or []],
                                   [str(k) for k in meta.get("keywords") or []], meta.get("flaw"), body)
    return list(out.values())


ID_LIKE = re.compile(r"^[A-Z]+\d+(\.\d+)*(\.T\d+)?$")


def caught(case: Case, findings: list[Finding]) -> bool:
    """A catch names the flaw (a keyword that is not just an ID) and, when the case has IDs, points at one of them."""
    words = [k.lower() for k in case.keywords if not ID_LIKE.match(k)]
    for f in findings:
        if f.severity not in ("high", "medium"):
            continue
        text = f"{f.finding} {f.fix}".lower()
        if not any(re.search(r"\b" + re.escape(k), text) for k in words):
            continue
        if not case.ids or set(f.ids) & set(case.ids) or any(i.lower() in text for i in case.ids):
            return True
    return False


def plan(cases: list[Case], personas: list[str]) -> list[tuple[str, str]]:
    """(case id, persona) pairs: each persona on the cases it should catch plus every clean control."""
    return [(c.id, p) for p in personas for c in cases if p in c.expect or c.clean]


def score(cases: list[Case], results: dict[tuple[str, str], list[Finding] | None]) -> dict[str, dict]:
    by_id = {c.id: c for c in cases}
    stats: dict[str, dict] = {}
    for (cid, persona), findings in results.items():
        s = stats.setdefault(persona, {"cases": 0, "caught": 0, "clean": 0, "false_alarms": 0, "noise": 0,
                                       "unparseable": 0, "missed": []})
        case = by_id[cid]
        if findings is None:  # missing or unparseable reply: reported, but not scored either way
            s["unparseable"] += 1
            continue
        if case.clean:
            s["clean"] += 1
            if any(f.severity == "high" for f in findings):
                s["false_alarms"] += 1
            s["noise"] += sum(1 for f in findings if f.severity == "medium")
        elif persona in case.expect:
            s["cases"] += 1
            if caught(case, findings):
                s["caught"] += 1
            else:
                s["missed"].append(cid)
    for s in stats.values():
        s["catch_rate"] = round(s["caught"] / s["cases"], 2) if s["cases"] else None
        s["false_alarm_rate"] = round(s["false_alarms"] / s["clean"], 2) if s["clean"] else None
        s["noise_per_clean"] = round(s["noise"] / s["clean"], 1) if s["clean"] else None
    return stats


def proposal(stats: dict[str, dict], min_catch: float, already_disabled: list[str]) -> list[str]:
    """S10.3: personas to disable, never leaving any review level with fewer than MIN_PERSONAS Inspectors."""
    weak = sorted(p for p, s in stats.items() if s["catch_rate"] is not None and s["catch_rate"] < min_catch)
    disabled = set(already_disabled)
    out = []
    for p in weak:
        trial = disabled | {p}
        if all(len([n for n in names if n not in trial]) >= MIN_PERSONAS for names in DEFAULT_PERSONAS.values()):
            disabled = trial
            out.append(p)
    return out


def write_report(root: Path, tier_stats: dict[str, dict[str, dict]], cfg: dict, n_cases: int) -> tuple[Path, list[str]]:
    min_catch = float((cfg.get("calibration") or {}).get("min_catch_rate", 0.5))
    disabled = list((cfg.get("review") or {}).get("disabled") or [])
    rows, weak_all = [], {}
    merged: dict[str, dict] = {}
    for tier, stats in tier_stats.items():
        for persona in sorted(stats):
            s = stats[persona]
            fmt = lambda v: "—" if v is None else f"{v:.2f}"  # noqa: E731
            noise = "—" if s.get("noise_per_clean") is None else f"{s['noise_per_clean']:.1f}"
            rows.append(f"| {persona} | {tier} | {s['cases']} | {s['caught']} | {fmt(s['catch_rate'])} | {s['clean']} | "
                        f"{s['false_alarms']} | {fmt(s['false_alarm_rate'])} | {noise} | {', '.join(s['missed']) or '—'} |")
        for p, st in stats.items():
            if st["catch_rate"] is not None and st["catch_rate"] < min_catch:
                weak_all.setdefault(p, []).append(tier)
                merged[p] = {"catch_rate": 0.0}
    propose = proposal(merged, min_catch, disabled)  # one check over all tiers: never fewer than 2 Inspectors
    weak_all = {p: t for p, t in weak_all.items() if p in propose}
    text = ("---\nid: calibration\ntitle: Reviewer calibration\ntype: review\nstatus: in-review\n---\n\n"
            f"Suite: {n_cases} cases (built-in planted flaws and clean controls, plus any in `.sparkwright/calibration/`).\n"
            "Catch: a high or medium finding that names the flaw and points at the flawed requirement. False alarm: a "
            "high finding on a clean control. Noise: medium findings per clean control (often fair critique, but cost "
            "reader time). Missing or unparseable replies are not scored.\n\n| Persona | Tier | Flawed cases | Caught | Catch rate | Clean cases | False alarms | "
            "False-alarm rate | Noise | Missed |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n" + "\n".join(rows) + "\n")
    text += f"\n## Proposal\n\nMinimum catch rate: {min_catch:.2f} (`calibration.min_catch_rate`).\n\n"
    if propose:
        text += ("These personas caught too few planted flaws. To stop using them in default reviews, a human adds this "
                 "to `.sparkwright/config.yaml` (every level keeps at least 2 Inspectors):\n\n```yaml\nreview:\n  disabled: "
                 f"{sorted(set(disabled) | set(propose))}\n```\n\nWeak at tier: "
                 + "; ".join(f"{p} ({', '.join(t)})" for p, t in sorted(weak_all.items())) + "\n")
    else:
        text += "No change proposed.\n"
    path = root / REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, propose


# ---- host mode
def prepare(root: Path | str, personas: list[str] | None = None) -> dict:
    root = Path(root).resolve()
    personas = personas or INSPECTORS
    available = load_all(root)
    unknown = [p for p in personas if p not in available]
    if unknown:
        raise CalibrationError(f"unknown personas: {unknown}")
    cases = load_cases(root)
    pairs = plan(cases, personas)
    log = RunLog(root, "calibrate")
    run_dir = log.path.with_suffix("")
    (run_dir / "cases").mkdir(parents=True, exist_ok=True)
    by_id = {c.id: c for c in cases}
    for c in {cid for cid, _ in pairs}:
        (run_dir / "cases" / f"{c}.md").write_text(by_id[c].context, encoding="utf-8")
    jobs = [{"case": cid, "persona": p, "context": str((run_dir / "cases" / f"{cid}.md").relative_to(root)),
             "result_file": str((run_dir / f"{cid}__{p}.json").relative_to(root))} for cid, p in pairs]
    log.append("start", status="started", personas=personas, pairs=[list(x) for x in pairs])
    return {"run_id": log.run_id, "jobs": jobs, "then": f"sparkwright calibrate --collect {log.run_id}"}


def collect(root: Path | str, run_id: str) -> dict:
    root = Path(root).resolve()
    try:
        log = RunLog(root, "calibrate", run_id)
    except ValueError as exc:
        raise CalibrationError(str(exc)) from exc
    start = next((r for r in log.records() if r.get("step") == "start"), None)
    if start is None:
        raise CalibrationError(f"no prepared calibration run {run_id}")
    cases = load_cases(root)
    personas = [p for p in start.get("personas", []) if p in INSPECTORS or p in load_all(root)]
    pairs = plan(cases, personas)  # recomputed: the run log is not trusted
    run_dir = log.path.with_suffix("")
    results = {}
    missing = []
    for cid, p in pairs:
        f = run_dir / f"{cid}__{p}.json"
        if not f.is_file():
            missing.append(f.name)
            results[(cid, p)] = None
        else:
            results[(cid, p)] = parse_findings(f.read_text(encoding="utf-8"))
    cfg, _ = config_mod.load(root)
    stats = score(cases, results)
    path, propose = write_report(root, {"host": stats}, cfg, len(cases))
    log.append("report", status="done", report=REPORT, missing=missing)
    return {"report": REPORT, "stats": stats, "propose_disable": propose, "missing": missing}


# ---- runner mode
def run(root: Path | str, router: Router, personas: list[str] | None = None, tiers: list[str] | None = None) -> dict:
    root = Path(root).resolve()
    personas = personas or INSPECTORS
    all_p = load_all(root)
    cases = load_cases(root)
    by_id = {c.id: c for c in cases}
    log = RunLog(root, "calibrate")
    tier_stats = {}
    for tier in tiers or [None]:
        cfg = copy.deepcopy(router.config)
        if tier:
            cfg["roles"] = {**cfg.get("roles", {}), **{p: tier for p in personas}}
        r = Router(cfg, router.overrides)
        results = {}
        for cid, p in plan(cases, personas):
            res = r.call(all_p[p], by_id[cid].context, force=True)
            results[(cid, p)] = parse_findings(res.text)
            log.append(f"call:{p}", status="done", case=cid, tier=res.tier, cost_usd=round(res.cost_usd, 6))
        tier_stats[tier or "configured"] = score(cases, results)
    cfg, _ = config_mod.load(root)
    _, propose = write_report(root, tier_stats, cfg, len(cases))
    return {"report": REPORT, "stats": tier_stats, "propose_disable": propose, "run_id": log.run_id}
