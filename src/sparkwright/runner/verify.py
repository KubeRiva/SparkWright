"""`sparkwright verify`: run the project's declared checks (SYSTEM S5.1).

Commands run with the project's `env:` settings from config, so builds in
workspaces and mutation copies can share one environment (for example
UV_PROJECT_ENVIRONMENT) instead of creating one per copy.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CheckResult:
    name: str
    command: str
    ok: bool
    output: str


def split_cmd(cmd: str) -> list[str]:
    """Split a command line on any platform; on Windows keep backslashes and drop surrounding quotes."""
    if os.name != "nt":
        return shlex.split(cmd)
    parts = shlex.split(cmd, posix=False)
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in "\"'" else p for p in parts]


def command_env(env: dict | None, repo: Path | str | None = None) -> dict:
    """os.environ plus config `env:` values; `{repo}` in a value is replaced by the main repository root."""
    out = dict(os.environ)
    for k, v in (env or {}).items():
        out[str(k)] = str(v).replace("{repo}", str(Path(repo).resolve()) if repo else "")
    out.setdefault("PYTHONIOENCODING", "utf-8")
    return out


def run_checks(root: Path | str, checks: dict, timeout: float = 900, only: list[str] | None = None,
               env: dict | None = None) -> list[CheckResult]:
    out = []
    for name, cmd in (checks or {}).items():
        if only and name not in only:
            continue
        try:
            r = subprocess.run(split_cmd(str(cmd)), cwd=root, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, env=env)
            text = ((r.stdout or "") + (r.stderr or ""))[-4000:]
            out.append(CheckResult(name, str(cmd), r.returncode == 0, text))
        except subprocess.TimeoutExpired:
            out.append(CheckResult(name, str(cmd), False, f"timed out after {timeout}s"))
        except OSError as exc:
            out.append(CheckResult(name, str(cmd), False, f"cannot run: {exc}"))
    return out
