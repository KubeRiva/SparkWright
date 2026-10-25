"""Load every spec file in a repository (SYSTEM S1)."""
from __future__ import annotations

import re

from dataclasses import dataclass, field
from pathlib import Path

from . import ids
from .frontmatter import FrontMatterError, split
from .grammar import ParseIssue, Requirement, parse_body

REQUIRED_META = ("id", "title", "type", "status")
STATUSES = {"draft", "in-review", "approved", "building", "done", "blocked", "changed", "rejected"}
EVIDENCE_STATUSES = STATUSES | {"confirmed"}
CHANGE_STATUSES = {"open", "approved", "rejected", "applied", "blocked"}


@dataclass
class SpecFile:
    path: str  # relative to repo root, forward slashes
    meta: dict
    requirements: list[Requirement] = field(default_factory=list)
    issues: list[ParseIssue] = field(default_factory=list)

    @property
    def id(self) -> str | None:
        value = self.meta.get("id")
        return ids.canonical(str(value)) if value is not None else None

    @property
    def status(self) -> str:
        return str(self.meta.get("status", "draft"))


@dataclass
class Evidence:
    id: str
    file: str
    simulated: bool
    status: str


@dataclass
class Repo:
    root: Path
    files: list[SpecFile]
    requirements: dict[str, Requirement]
    evidence: dict[str, Evidence]
    file_of: dict[str, SpecFile]          # requirement id -> owning file
    duplicates: list[tuple[str, str, int]]  # (id, file, line)

    def status_of(self, rid: str) -> str:
        if rid in self.file_of:
            return self.file_of[rid].status
        if rid in self.evidence:
            return self.evidence[rid].status
        return "unknown"


def _rel(root: Path, p: Path) -> str:
    return p.relative_to(root).as_posix()


def load(root: Path | str) -> Repo:
    root = Path(root).resolve()
    spec_dir = root / "specs"
    files: list[SpecFile] = []
    requirements: dict[str, Requirement] = {}
    evidence: dict[str, Evidence] = {}
    file_of: dict[str, SpecFile] = {}
    duplicates: list[tuple[str, str, int]] = []
    paths = sorted(spec_dir.rglob("*.md")) if spec_dir.is_dir() else []
    for p in paths:
        rel = _rel(root, p)
        try:
            text = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            files.append(SpecFile(rel, {}, issues=[ParseIssue("encoding.invalid", f"file is not valid UTF-8 ({exc.reason} at byte {exc.start})", 1)]))
            continue
        try:
            meta, body, first = split(text)
        except FrontMatterError as exc:
            sf = SpecFile(rel, {}, issues=[ParseIssue("frontmatter.invalid", str(exc), 1)])
            files.append(sf)
            continue
        sf = SpecFile(rel, meta)
        missing = [k for k in REQUIRED_META if k not in meta]
        if meta.get("type") in ("component", "task") and "risk" not in meta:
            missing.append("risk")
        if missing:
            sf.issues.append(ParseIssue("frontmatter.missing-field", f"missing front matter fields: {missing}", 1))
        allowed = {"evidence": EVIDENCE_STATUSES, "change": CHANGE_STATUSES}.get(meta.get("type"), STATUSES)
        if "status" in meta and str(meta["status"]) not in allowed:
            sf.issues.append(ParseIssue("frontmatter.invalid-status", f"unknown status '{meta['status']}'", 1))
        reqs, issues = parse_body(body, rel, first)
        if meta.get("type") in ("change", "review"):
            reqs = []  # quoted requirement lines in change requests and reviews are not definitions
        if meta.get("type") == "task":
            m = re.search(r"^#{2,3}[ \t]+acceptance criteria[ \t]*\n(.*?)(?=^#{1,3}[ \t]|\Z)", body, re.M | re.S | re.I)
            for r in reqs:
                if r.kind == "task":
                    r.criteria = m.group(1).strip() if m else ""
        sf.requirements, sf.issues = reqs, sf.issues + issues
        files.append(sf)
        if meta.get("type") == "evidence" and sf.id and ids.kind_of(sf.id) == "evidence":
            evidence[sf.id] = Evidence(sf.id, rel, bool(meta.get("simulated", False)), sf.status)
        for r in reqs:
            if r.id in requirements:
                duplicates.append((r.id, rel, r.line))
                continue
            requirements[r.id] = r
            file_of[r.id] = sf
    return Repo(root, files, requirements, evidence, file_of, duplicates)
