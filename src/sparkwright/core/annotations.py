"""Find tests annotated with the task they verify (SYSTEM S2.1)."""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path

from . import ids

ANNOT_RE = re.compile(rf"sparkwright:\s*(?P<id>{ids.ID_PATTERN})")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".sparkwright", "build", "dist"}


def _git_files(root: Path) -> list[str] | None:
    """Tracked plus untracked-but-not-ignored files, via git (fast on large trees); None outside a repo."""
    try:
        r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), "ls-files", "-z", "--cached",
                            "--others", "--exclude-standard"], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return sorted({f for f in r.stdout.decode("utf-8", "replace").split("\0") if f})


def _matches(rel: str, globs: list[str]) -> bool:
    from .globs import match
    return match(rel, globs) or any(fnmatch.fnmatch("/" + rel, "*/" + g.lstrip("*/")) for g in globs)


def test_files(root: Path, globs: list[str]) -> list[str]:
    listed = _git_files(root)
    if listed is not None:
        return [rel for rel in listed if not any(part in SKIP_DIRS for part in rel.split("/"))
                and _matches(rel, globs) and (root / rel).is_file()]
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):  # prune skipped directories instead of walking them
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".venv"))
        for name in sorted(filenames):
            rel = (Path(dirpath) / name).relative_to(root).as_posix()
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
