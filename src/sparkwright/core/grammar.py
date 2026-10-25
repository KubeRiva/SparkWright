"""Requirement line grammar (SYSTEM 'Requirement line grammar', S1.8).

    - **<ID>** [<ref>, <ref>, ...] <text>

Continuation lines are indented by two or more spaces. A fenced ```yaml block
directly after a task line declares task extras (files, invariants, prove).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from . import ids
from .frontmatter import FrontMatterError, load_yaml

LINE_RE = re.compile(
    r"^- \*\*(?P<id>[^*\s]+)\*\*\s+\[(?P<refs>[^\]]*)\]\s*(?P<text>.*)$"
)
# Looks like a requirement (bold known ID at bullet start) but lacks the [refs] part.
NEAR_MISS_RE = re.compile(rf"^- \*\*(?P<id>{ids.ID_PATTERN})\b")
FENCE_RE = re.compile(r"^(```|~~~)")
EXTRAS_KEYS = {"files", "invariants", "prove"}


@dataclass
class Requirement:
    id: str
    kind: str
    refs: list[str]
    text: str
    file: str
    line: int
    extras: dict = field(default_factory=dict)
    criteria: str = ""  # task files: the `## Acceptance criteria` section (D007)

    @property
    def hash2(self) -> str:
        """D007 lock: text, sorted parent refs, task extras and acceptance criteria. Recorded next to `hash`."""
        import json
        crit = "\n".join(" ".join(ln.split()) for ln in self.criteria.splitlines() if ln.strip())
        return text_hash(self.text + "\nrefs:" + ",".join(sorted(self.refs)) + "\nextras:"
                         + json.dumps(self.extras, sort_keys=True, default=str) + "\ncriteria:" + crit)

    @property
    def hash(self) -> str:
        """Text hash; for tasks with extras, the extras (sorted JSON) are part of the hash (SYSTEM grammar)."""
        if self.extras:
            import json
            return text_hash(self.text + "\n" + json.dumps(self.extras, sort_keys=True))
        return text_hash(self.text)


@dataclass
class ParseIssue:
    code: str
    message: str
    line: int
    id: str | None = None


def text_hash(text: str) -> str:
    normalised = " ".join(text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def parse_body(body: str, file: str, first_line: int = 1) -> tuple[list[Requirement], list[ParseIssue]]:
    reqs: list[Requirement] = []
    issues: list[ParseIssue] = []
    lines = body.split("\n")
    i = 0
    in_fence = False
    current: Requirement | None = None
    while i < len(lines):
        line = lines[i]
        lineno = first_line + i
        if FENCE_RE.match(line.strip()) and not line.startswith(" "):
            # Task extras block directly after a task requirement.
            if (
                not in_fence
                and current is not None
                and current.kind == "task"
                and line.strip().startswith(("```yaml", "~~~yaml"))
            ):
                block, j = _read_fence(lines, i)
                _apply_extras(current, block, lineno, issues)
                i = j + 1
                current = None
                continue
            in_fence = not in_fence
            current = None
            i += 1
            continue
        if in_fence:
            i += 1
            continue
        m = LINE_RE.match(line)
        if m:
            rid = ids.canonical(m.group("id"))
            kind = ids.kind_of(rid)
            refs = [ids.canonical(r.strip()) for r in m.group("refs").split(",") if r.strip()]
            if kind is None:
                issues.append(ParseIssue("grammar.unknown-id", f"'{rid}' is not a valid requirement ID", lineno, rid))
                current = None
            else:
                current = Requirement(rid, kind, refs, m.group("text").strip(), file, lineno)
                reqs.append(current)
            i += 1
            continue
        nm = NEAR_MISS_RE.match(line)
        if nm:
            issues.append(ParseIssue(
                "grammar.malformed",
                f"line looks like requirement {nm.group('id')} but does not match '- **<ID>** [<refs>] <text>'",
                lineno, nm.group("id"),
            ))
            current = None
            i += 1
            continue
        if current is not None and line.startswith("  ") and line.strip():
            current.text = f"{current.text} {line.strip()}".strip()
        elif current is not None and line.strip() == "":
            pass  # blank line: allow an extras fence after it
        else:
            current = None
        i += 1
    if in_fence:
        issues.append(ParseIssue("grammar.unclosed-fence", "code fence is not closed", first_line + len(lines) - 1))
    return reqs, issues


def _read_fence(lines: list[str], start: int) -> tuple[str, int]:
    marker = lines[start].strip()[:3]
    j = start + 1
    while j < len(lines) and not lines[j].strip().startswith(marker):
        j += 1
    return "\n".join(lines[start + 1:j]), j


def _apply_extras(req: Requirement, block: str, lineno: int, issues: list[ParseIssue]) -> None:
    try:
        data = load_yaml(block) or {}
    except FrontMatterError as exc:
        issues.append(ParseIssue("grammar.extras-invalid", str(exc), lineno, req.id))
        return
    if not isinstance(data, dict):
        issues.append(ParseIssue("grammar.extras-invalid", "task extras must be a mapping", lineno, req.id))
        return
    unknown = set(data) - EXTRAS_KEYS
    if unknown:
        issues.append(ParseIssue("grammar.extras-invalid", f"unknown task extras: {sorted(unknown)}", lineno, req.id))
    files = data.get("files", [])
    invariants = data.get("invariants", [])
    if not isinstance(files, list) or not all(isinstance(f, str) for f in files):
        issues.append(ParseIssue("grammar.extras-invalid", "'files' must be a list of globs", lineno, req.id))
        files = []
    if not isinstance(invariants, list):
        issues.append(ParseIssue("grammar.extras-invalid", "'invariants' must be a list", lineno, req.id))
        invariants = []
    req.extras = {"files": files, "invariants": invariants, "prove": bool(data.get("prove", False))}
