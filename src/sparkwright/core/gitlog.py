"""Read commits, trailers and changed files from git (SYSTEM S2.1, S2.6, S6.5)."""
from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import ids

TRAILER_RE = re.compile(r"^SparkWright-(Task|Role):\s*(\S+)\s*$", re.M)
_REC = "\x1e"
_FLD = "\x1f"


@dataclass
class Commit:
    sha: str
    subject: str
    tasks: list[str] = field(default_factory=list)
    role: str | None = None
    files: list[str] = field(default_factory=list)
    body: str = ""


class GitError(RuntimeError):
    pass


def git_available() -> bool:
    return shutil.which("git") is not None


def is_repo(root: Path | str) -> bool:
    if not git_available():
        return False
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0 and out.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def _git(root: Path | str, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def commits(root: Path | str, baseline: str | None = None) -> list[Commit]:
    """Commits after `baseline` (exclusive), oldest first.

    Returns [] for a repository with no commits. Raises GitError when the
    baseline is unknown (for example a shallow clone) or git log fails, so the
    caller can report it instead of silently skipping commit checks.
    """
    head = _git(root, "rev-parse", "--verify", "-q", "HEAD")
    if head.returncode != 0:
        return []  # no commits yet
    if baseline:
        if _git(root, "cat-file", "-e", f"{baseline}^{{commit}}").returncode != 0:
            raise GitError(f"baseline commit {baseline} is not in this repository (shallow clone? fetch full history)")
    rng = f"{baseline}..HEAD" if baseline else "HEAD"
    fmt = f"{_REC}%H{_FLD}%s{_FLD}%B{_FLD}"
    try:
        out = _git(root, "log", "--reverse", "--no-merges", "--no-renames", "--name-only", f"--format={fmt}", rng)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git log failed: {exc}") from exc
    if out.returncode != 0:
        raise GitError(f"git log failed: {out.stderr.strip()[:200]}")
    result: list[Commit] = []
    for rec in out.stdout.split(_REC)[1:]:
        parts = rec.split(_FLD)
        if len(parts) < 4:
            continue
        sha, subject, body, files_blob = parts[0], parts[1], parts[2], parts[3]
        c = Commit(sha, subject, body=body)
        for kind, value in TRAILER_RE.findall(body):
            if kind == "Task":
                c.tasks.append(ids.canonical(value))
            else:
                c.role = value
        c.files = [f.strip() for f in files_blob.splitlines() if f.strip()]
        result.append(c)
    return result


@dataclass
class AddedLine:
    text: str
    sha: str
    author_email: str


def added_lines(root: Path | str, path: str, baseline: str | None) -> list[AddedLine]:
    """Lines added to `path` by commits after `baseline` (oldest first), with each commit's author email."""
    rng = f"{baseline}..HEAD" if baseline else "HEAD"
    out = _git(root, "log", "--reverse", "--no-merges", "-p", "--unified=0",
               f"--format={_REC}%H{_FLD}%ae", rng, "--", path)
    if out.returncode != 0:
        raise GitError(f"git log for {path} failed: {out.stderr.strip()[:200]}")
    result: list[AddedLine] = []
    for rec in out.stdout.split(_REC)[1:]:
        header, _, diff = rec.partition("\n")
        sha, _, email = header.partition(_FLD)
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                result.append(AddedLine(line[1:], sha.strip(), email.strip().lower()))
    return result


def show(root: Path | str, rev: str, path: str) -> str | None:
    """File content at a revision, or None if it did not exist there."""
    out = _git(root, "show", f"{rev}:{path}")
    return out.stdout if out.returncode == 0 else None


def verify_commit(root: Path | str, sha: str) -> bool:
    return _git(root, "verify-commit", sha).returncode == 0


def user_identity(root: Path | str) -> tuple[str | None, str | None]:
    name = _git(root, "config", "user.name").stdout.strip() or None
    email = _git(root, "config", "user.email").stdout.strip() or None
    return name, email
