"""`sparkwright verify`: run the project's declared checks (SYSTEM S5.1)."""
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


def run_checks(root: Path | str, checks: dict, timeout: float = 900, only: list[str] | None = None) -> list[CheckResult]:
    out = []
    for name, cmd in (checks or {}).items():
        if only and name not in only:
            continue
        try:
            r = subprocess.run(shlex.split(str(cmd), posix=(os.name != "nt")), cwd=root,
                               capture_output=True, text=True, timeout=timeout)
            text = (r.stdout + r.stderr)[-4000:]
            out.append(CheckResult(name, str(cmd), r.returncode == 0, text))
        except subprocess.TimeoutExpired:
            out.append(CheckResult(name, str(cmd), False, f"timed out after {timeout}s"))
        except OSError as exc:
            out.append(CheckResult(name, str(cmd), False, f"cannot run: {exc}"))
    return out
