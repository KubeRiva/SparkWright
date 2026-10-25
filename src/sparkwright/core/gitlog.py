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
    time: str = ""  # committer date, ISO 8601
    author_email: str = ""
    status: dict = field(default_factory=dict)  # path -> A/M/D/T (D007: the runner may only add review files)


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
    fmt = f"{_REC}%H{_FLD}%s{_FLD}%cI{_FLD}%ae{_FLD}%B{_FLD}"
    try:
        out = _git(root, "log", "--reverse", "--no-merges", "--no-renames", "--name-status", f"--format={fmt}", rng)
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitError(f"git log failed: {exc}") from exc
    if out.returncode != 0:
        raise GitError(f"git log failed: {out.stderr.strip()[:200]}")
    result: list[Commit] = []
    for rec in out.stdout.split(_REC)[1:]:
        parts = rec.split(_FLD)
        if len(parts) < 6:
            continue
        sha, subject, ctime, email, body, files_blob = parts[:6]
        c = Commit(sha, subject, body=body, time=ctime.strip(), author_email=email.strip().lower())
        roles = set()
        for kind, value in TRAILER_RE.findall(body):
            if kind == "Task":
                c.tasks.append(ids.canonical(value))
            else:
                roles.add(value.strip().lower())
        c.role = (roles.pop() if len(roles) == 1 else "conflict") if roles else None  # D008: disagreeing roles
        for row in files_blob.splitlines():
            kind, _, path = row.strip().partition("\t")
            if path:
                c.status[path.strip()] = kind[:1]
                c.files.append(path.strip())
        result.append(c)
    return result


@dataclass
class AddedLine:
    text: str
    sha: str
    author_email: str


_ADDED_CACHE: dict = {}


def added_lines(root: Path | str, path: str, baseline: str | None) -> list[AddedLine]:
    """Lines added to `path` by commits after `baseline` (oldest first), with each commit's author email.

    Cached per HEAD tree state for the duration of one `check` (see `clear_cache`)."""
    key = (str(root), path, baseline)
    if key in _ADDED_CACHE:
        return _ADDED_CACHE[key]
    _ADDED_CACHE[key] = result = _added_lines(root, path, baseline)
    return result


def clear_cache() -> None:
    _ADDED_CACHE.clear()


def _added_lines(root: Path | str, path: str, baseline: str | None) -> list[AddedLine]:
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


@dataclass
class DiffLine:
    sign: str  # "+" or "-"
    text: str
    sha: str
    author_email: str
    path: str


def diff_lines(root: Path | str, pathspec: str, baseline: str | None) -> list[DiffLine]:
    """Added and removed lines under `pathspec` in commits after `baseline`, oldest first (D007)."""
    rng = f"{baseline}..HEAD" if baseline else "HEAD"
    out = _git(root, "log", "--reverse", "--no-merges", "--no-renames", "-p", "--unified=0",
               f"--format={_REC}%H{_FLD}%ae", rng, "--", pathspec)
    if out.returncode != 0:
        raise GitError(f"git log for {pathspec} failed: {out.stderr.strip()[:200]}")
    result: list[DiffLine] = []
    for rec in out.stdout.split(_REC)[1:]:
        header, _, diff = rec.partition("\n")
        sha, _, email = header.partition(_FLD)
        path = ""
        for line in diff.splitlines():
            if line.startswith("+++ ") or line.startswith("--- "):
                if line.startswith("+++ "):
                    path = line[6:] if line.startswith("+++ b/") else path
                elif line.startswith("--- a/"):
                    path = line[6:]
                continue
            if line[:1] in "+-" and line:
                result.append(DiffLine(line[0], line[1:], sha.strip(), email.strip().lower(), path))
    return result


def shas_after(root: Path | str, rev: str) -> set[str] | None:
    """Commits in rev..HEAD, or None when `rev` is unknown."""
    out = _git(root, "rev-list", f"{rev}..HEAD")
    return set(out.stdout.split()) if out.returncode == 0 else None


def show(root: Path | str, rev: str, path: str) -> str | None:
    """File content at a revision, or None if it did not exist there."""
    out = _git(root, "show", f"{rev}:{path}")
    return out.stdout if out.returncode == 0 else None


def signer(root: Path | str, sha: str) -> tuple[str, str]:
    """(git signature status letter, signing key fingerprint) of a commit; ("N", "") when unsigned."""
    out = _git(root, "log", "-1", "--format=%G?%x00%GF%x00%GP", sha)
    parts = (out.stdout.strip().split("\x00") + ["", "", ""])[:3] if out.returncode == 0 else ["N", "", ""]
    return parts[0] or "N", (parts[1] or parts[2]).upper()


def commits_touching(root: Path | str, baseline: str | None, pathspec: str | list[str]) -> list[tuple[str, list[str], str, str, list[str]]]:
    """(sha, parent shas, author email, body, changed paths) of commits after `baseline` touching `pathspec`,
    oldest first, merges included with the paths they change against any parent (D007: an edit made while
    resolving a merge is still checked)."""
    rng = f"{baseline}..HEAD" if baseline else "HEAD"
    out = _git(root, "log", "--reverse", "--full-history", "-m", "--no-renames", "--name-only",
               f"--format={_REC}%H{_FLD}%P{_FLD}%ae{_FLD}%B{_FLD}", rng, "--",
               *([pathspec] if isinstance(pathspec, str) else pathspec))
    if out.returncode != 0:
        raise GitError(f"git log for {pathspec} failed: {out.stderr.strip()[:200]}")
    res: dict[str, tuple[str, list[str], str, str, list[str]]] = {}
    for rec in out.stdout.split(_REC)[1:]:
        parts = rec.split(_FLD)
        if len(parts) < 5:
            continue
        sha = parts[0].strip()
        files = [f.strip() for f in parts[4].splitlines() if f.strip()]
        if sha in res:
            res[sha][4].extend(f for f in files if f not in res[sha][4])
        else:
            res[sha] = (sha, parts[1].split(), parts[2].strip().lower(), parts[3], files)
    return list(res.values())


def read_blobs(root: Path | str, specs: list[str]) -> dict[str, str | None]:
    """Contents of many `rev:path` blobs in one git process (None when missing)."""
    out: dict[str, str | None] = {}
    if not specs:
        return out
    proc = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"], input=("\n".join(specs) + "\n").encode("utf-8"),
                          capture_output=True, timeout=120)
    data, pos = proc.stdout, 0
    for spec in specs:
        nl = data.find(b"\n", pos)
        if nl < 0:
            out[spec] = None
            continue
        header = data[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) == 3 and header[1] == "blob":
            size = int(header[2])
            out[spec] = data[pos:pos + size].decode("utf-8", "replace")
            pos += size + 1
        else:
            out[spec] = None
    return out


def ls_tree(root: Path | str, rev: str, path: str) -> list[str]:
    out = _git(root, "ls-tree", "-r", "--name-only", rev, "--", path)
    return [x for x in out.stdout.splitlines() if x.strip()] if out.returncode == 0 else []


def role_of(body: str) -> str | None:
    roles = {v.strip().lower() for k, v in TRAILER_RE.findall(body) if k == "Role"}
    return (roles.pop() if len(roles) == 1 else "conflict") if roles else None


def verify_commit(root: Path | str, sha: str) -> bool:
    return _git(root, "verify-commit", sha).returncode == 0


def user_identity(root: Path | str) -> tuple[str | None, str | None]:
    name = _git(root, "config", "user.name").stdout.strip() or None
    email = _git(root, "config", "user.email").stdout.strip() or None
    return name, email
