"""Parallel builds (SYSTEM S3.8).

Tasks whose `files` globs cannot touch the same path may build at the same time in their own
worktrees. Glob overlap is judged conservatively (when in doubt, they overlap). Before a build is
marked ready, the engine compares the files it actually changed with every other unmerged build
and with what the main branch changed since this build started, and stops on any overlap.
"""
from __future__ import annotations

import fnmatch
import json
import re
import subprocess
import threading
from pathlib import Path

from ..core import ids, store

WILD = re.compile(r"[*?\[]")
MAIN_REPO_LOCK = threading.Lock()  # serialises worktree creation and final gates within one process


def _prefix(glob: str) -> str:
    m = WILD.search(glob)
    return glob[: m.start()] if m else glob


def globs_may_intersect(a: list[str], b: list[str]) -> bool:
    for ga in a:
        for gb in b:
            if ga == gb or fnmatch.fnmatchcase(ga, gb) or fnmatch.fnmatchcase(gb, ga):
                return True
            pa, pb = _prefix(ga), _prefix(gb)
            wild_a, wild_b = bool(WILD.search(ga)), bool(WILD.search(gb))
            if wild_a and pb.startswith(pa):
                return True
            if wild_b and pa.startswith(pb):
                return True
    return False


def plan_batches(root: Path | str, tasks: list[str]) -> list[list[str]]:
    """Greedy grouping: each batch holds tasks whose globs pairwise cannot overlap. Order is kept."""
    repo = store.load(root)
    batches: list[list[str]] = []
    files = {}
    for t in tasks:
        t = ids.canonical(t)
        if t not in repo.requirements or ids.kind_of(t) != "task":
            raise ValueError(f"{t} is not a defined task")
        files[t] = list(repo.requirements[t].extras.get("files") or [])
        if not files[t]:
            raise ValueError(f"{t} declares no files")
    for t in files:
        for batch in batches:
            if not any(globs_may_intersect(files[t], files[o]) for o in batch):
                batch.append(t)
                break
        else:
            batches.append([t])
    return batches


def _git(root: Path, *args: str) -> str:
    r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else ""


def active_builds(root: Path | str) -> list[dict]:
    """Latest state of every build run that is in progress or ready but not merged into HEAD."""
    root = Path(root)
    runs = root / ".sparkwright" / "runs"
    latest: dict[str, dict] = {}
    for p in sorted(runs.glob("build-*.jsonl")) if runs.is_dir() else []:
        state = None
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("step") == "state" and isinstance(rec.get("state"), dict):
                state = rec["state"]
        m = re.fullmatch(r"build-(.+?)(?:-(\d+))?", p.stem)
        if not state or not m:
            continue
        task, n = m.group(1), int(m.group(2) or 1)
        if task in latest and latest[task]["run_no"] > n:
            continue
        latest[task] = {"task": task, "run_no": n, **state}
    out = []
    for task, st in latest.items():
        if st.get("phase") in ("blocked", "changed", "prepare") or not st.get("branch") or not st.get("base"):
            continue
        tip = _git(root, "rev-parse", "--verify", "-q", st["branch"]).strip()
        if not tip:
            continue
        # an in-progress build is active even before its first commit; a ready one until it is merged
        merged = st.get("phase") == "ready" and subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", tip, "HEAD"], capture_output=True).returncode == 0
        if not merged:
            out.append(st)
    return out


def changed_files(root: Path | str, base: str, rev: str) -> set[str]:
    return {f for f in _git(Path(root), "diff", "--name-only", base, rev).splitlines() if f and not f.startswith("specs/")}
