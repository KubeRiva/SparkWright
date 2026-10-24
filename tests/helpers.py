"""Test helpers: build throwaway repositories."""
from __future__ import annotations

import io
import json
import subprocess
import tempfile
import textwrap
from contextlib import redirect_stdout
from pathlib import Path

from sparkwright.cli import main


def write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return p


def spec(id_: str, type_: str, body: str, status: str = "draft", extra: str = "") -> str:
    return f"---\nid: {id_}\ntitle: t\ntype: {type_}\nstatus: {status}\nrisk: low\n{extra}---\n\n" + textwrap.dedent(body).lstrip("\n")


def basic_repo(root: Path) -> None:
    write(root, "specs/evidence/E1.md", "---\nid: E1\ntitle: t\ntype: evidence\nstatus: draft\n---\n\nQuotes.\n")
    write(root, "specs/vision.md", spec("VISION", "vision", "- **V1** [E1] When asked, the system shall trace.\n"))
    write(root, "specs/system.md", spec("SYSTEM", "system", "- **S1.1** [V1] The parser shall parse.\n"))


def run_cli(root: Path, *args: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["-C", str(root), *args, "--json"])
    return code, json.loads(buf.getvalue())


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def git_init(root: Path) -> None:
    git(root, "init", "-q")
    if not (root / ".gitignore").exists():
        (root / ".gitignore").write_text(".sparkwright/ledger.json\n.sparkwright/runs/\n")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "Tester")
    git(root, "config", "commit.gpgsign", "false")


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


class TempRepo:
    def __enter__(self) -> Path:
        self._td = tempfile.TemporaryDirectory()
        return Path(self._td.name)

    def __exit__(self, *exc):
        self._td.cleanup()
