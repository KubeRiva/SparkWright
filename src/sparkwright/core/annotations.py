"""Find tests annotated with the task they verify (SYSTEM S2.1)."""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from . import ids

ANNOT_RE = re.compile(rf"sparkwright:\s*(?P<id>{ids.ID_PATTERN})")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".sparkwright", "build", "dist"}


def _matches(rel: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch("/" + rel, "*/" + g.lstrip("*/")) for g in globs)


def test_files(root: Path, globs: list[str]) -> list[str]:
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        rel = p.relative_to(root).as_posix()
        if _matches(rel, globs):
            out.append(rel)
    return out


def scan(root: Path | str, globs: list[str]) -> dict[str, list[str]]:
    """Map task/requirement id -> sorted list of test files that reference it."""
    root = Path(root)
    found: dict[str, set[str]] = {}
    for rel in test_files(root, globs):
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in ANNOT_RE.finditer(text):
            found.setdefault(ids.canonical(m.group("id")), set()).add(rel)
    return {k: sorted(v) for k, v in found.items()}
