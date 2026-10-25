"""Library Checker: verify that called attributes of third-party modules exist (SYSTEM S5.5)."""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

STDLIB = set(getattr(sys, "stdlib_module_names", ()))


@dataclass
class LibIssue:
    file: str
    line: int
    message: str


def _local_roots(root: Path) -> set[str]:
    names = set()
    for base in [root, root / "src"] + [p / "src" for p in root.iterdir() if p.is_dir()]:
        if base.is_dir():
            for p in base.iterdir():
                if (p.is_dir() and (p / "__init__.py").exists()) or p.suffix == ".py":
                    names.add(p.stem)
    return names


def uses(source: str) -> list[tuple[str, str, int]]:
    """(module, attribute, line) for `alias.attr` where alias is an imported module."""
    tree = ast.parse(source)
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            out.append((aliases[node.value.id], node.attr, node.lineno))
    return out


PROBE = """
import importlib, json, sys
req = json.loads(sys.argv[1]); out = {}
for mod, attrs in req.items():
    try:
        m = importlib.import_module(mod)
    except Exception as exc:
        out[mod] = {"error": f"{type(exc).__name__}: {exc}"}
        continue
    out[mod] = {"missing": [a for a in attrs if not hasattr(m, a)]}
print(json.dumps(out))
"""


def check(root: Path | str, files: list[str], python: str = sys.executable, env: dict | None = None) -> list[LibIssue]:
    root = Path(root)
    local = _local_roots(root)
    wanted: dict[str, set[str]] = {}
    where: dict[tuple[str, str], tuple[str, int]] = {}
    for rel in files:
        p = root / rel
        if p.suffix != ".py" or not p.is_file():
            continue
        try:
            found = uses(p.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            return [LibIssue(rel, exc.lineno or 1, f"syntax error: {exc.msg}")]
        for mod, attr, line in found:
            top = mod.split(".")[0]
            if top in STDLIB or top in local:
                continue
            wanted.setdefault(mod, set()).add(attr)
            where.setdefault((mod, attr), (rel, line))
    if not wanted:
        return []
    req = {m: sorted(a) for m, a in wanted.items()}
    from .verify import sandboxed
    r = subprocess.run(sandboxed([python, "-c", PROBE, json.dumps(req)], env), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=root, timeout=120, env=env)
    if r.returncode != 0:
        return [LibIssue(files[0] if files else "", 1, f"library probe failed: {r.stderr.strip()[:300]}")]
    result = json.loads(r.stdout.strip().splitlines()[-1])
    issues = []
    for mod, info in sorted(result.items()):
        if "error" in info:
            rel, line = where[(mod, sorted(wanted[mod])[0])]
            issues.append(LibIssue(rel, line, f"cannot import {mod}: {info['error']}"))
        for attr in info.get("missing", []):
            rel, line = where[(mod, attr)]
            issues.append(LibIssue(rel, line, f"{mod}.{attr} does not exist in the installed version"))
    return issues
