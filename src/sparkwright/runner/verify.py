"""`sparkwright verify`: run the project's declared checks (SYSTEM S5.1).

Commands run with the project's `env:` settings from config, so builds in
workspaces and mutation copies can share one environment (for example
UV_PROJECT_ENVIRONMENT) instead of creating one per copy.
"""
from __future__ import annotations

import os
import re
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


SECRET_RE = re.compile(
    r"(^|_)(API_?KEY|ACCESS_?KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIALS?|PRIVATE_?KEY|AUTH|PAT|DSN|WEBHOOK)($|_)"
    r"|^(DATABASE_URL|KUBECONFIG|SSH_AUTH_SOCK|GPG_AGENT_INFO|NETRC)$"
    r"|^(ANTHROPIC|OPENAI|AWS|AZURE|GOOGLE_APPLICATION|GCP|GH|GITHUB|STRIPE)_", re.I)


def scrub(env: dict, keep: list[str] | None = None) -> dict:
    """D007: remove secrets from the environment of AI-written code (tests, mutants, library imports).

    SSH_AUTH_SOCK and GPG_AGENT_INFO are removed too, so AI-written code cannot sign commits as the user.
    `keep` names are matched without regard to case.
    """
    keep_set = {k.upper() for k in (keep or [])}
    return {k: v for k, v in env.items() if k.upper() in keep_set or not SECRET_RE.search(k)}


NO_NET = "SPARKWRIGHT_SANDBOX_NO_NET"


def command_env(env: dict | None, repo: Path | str | None = None, keep: list[str] | None = None,
                sandbox: dict | None = None) -> dict:
    """os.environ without secrets, plus config `env:` values; `{repo}` in a value is the main repository root.

    D009 (S6.10): with `sandbox.isolate_home` (default on) HOME and USERPROFILE point at an empty folder, so
    AI-written code does not find credentials kept in the user's home folder at their usual paths; with
    `sandbox.network: false` commands run without network where the OS allows it (Linux `unshare -rn`)."""
    sb = sandbox if sandbox is not None else {}
    out = scrub(dict(os.environ), keep)
    if sb.get("isolate_home", True):
        import hashlib
        import tempfile
        tag = hashlib.sha256(str(Path(repo).resolve() if repo else "").encode("utf-8")).hexdigest()[:12]
        home = Path(tempfile.gettempdir()) / f"sparkwright-home-{tag}"
        home.mkdir(parents=True, exist_ok=True)
        for k in ("HOME", "USERPROFILE"):
            if k in out or k == "HOME":
                out[k] = str(home)
        for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
            out.pop(k, None)
        out.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    if sb.get("network", True) is False:
        out[NO_NET] = "1"
    for k, v in (env or {}).items():
        out[str(k)] = str(v).replace("{repo}", str(Path(repo).resolve()) if repo else "")
    out.setdefault("PYTHONIOENCODING", "utf-8")
    return out


def sandboxed(argv: list[str], env: dict | None) -> list[str]:
    """Prefix argv to cut network access when the sandbox asks for it and the OS supports it."""
    if env and env.get(NO_NET) == "1":
        import shutil
        import sys
        if sys.platform.startswith("linux") and shutil.which("unshare"):
            return ["unshare", "-rn", *argv]
        raise OSError("sandbox.network is false but this system cannot cut network access (needs Linux `unshare`)")
    return argv


def run_checks(root: Path | str, checks: dict, timeout: float = 900, only: list[str] | None = None,
               env: dict | None = None) -> list[CheckResult]:
    out = []
    for name, cmd in (checks or {}).items():
        if only and name not in only:
            continue
        try:
            r = subprocess.run(sandboxed(split_cmd(str(cmd)), env), cwd=root, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=timeout, env=env)
            text = ((r.stdout or "") + (r.stderr or ""))[-4000:]
            out.append(CheckResult(name, str(cmd), r.returncode == 0, text))
        except subprocess.TimeoutExpired:
            out.append(CheckResult(name, str(cmd), False, f"timed out after {timeout}s"))
        except OSError as exc:
            out.append(CheckResult(name, str(cmd), False, f"cannot run: {exc}"))
    return out
