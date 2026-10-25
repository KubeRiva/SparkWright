"""Saboteur: diff-scoped mutation testing for Python (SYSTEM S5.3, S3.4).

Mutants are applied to a temporary copy of the repository, never to the user's
working tree. Only lines changed since `base` are mutated.
"""
from __future__ import annotations

import ast
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

COMPARE_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
                ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.Is: ast.IsNot, ast.IsNot: ast.Is, ast.In: ast.NotIn, ast.NotIn: ast.In}
BINOP_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.Div: ast.Mult, ast.FloorDiv: ast.Mult, ast.Mod: ast.Mult}
IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".venv", ".venv-*", "venv", "node_modules", ".sparkwright", "*.pyc",
                                ".mypy_cache", ".pytest_cache", ".ruff_cache", ".worktrees")


@dataclass
class Mutant:
    file: str
    line: int
    description: str
    source: str  # full mutated module source


@dataclass
class MutationReport:
    total: int = 0
    killed: int = 0
    survivors: list[Mutant] = field(default_factory=list)
    timed_out_budget: bool = False
    baseline_ok: bool = True
    message: str = ""
    changed_source: int = 0      # changed source files considered

    @property
    def partial(self) -> bool:
        return self.timed_out_budget

    @property
    def score(self) -> float:
        return 1.0 if self.total == 0 else self.killed / self.total


def changed_lines(root: Path, base: str) -> dict[str, set[int]]:
    out = subprocess.run(["git", "-C", str(root), "diff", "-U0", base, "--", "*.py"], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"git diff failed: {out.stderr.strip()}")
    result: dict[str, set[int]] = {}
    current = None
    for line in out.stdout.splitlines():
        if line.startswith("+++ "):
            path = line[4:]
            current = path[2:] if path.startswith("b/") else None
        elif line.startswith("@@") and current:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                result.setdefault(current, set()).update(range(start, start + count))
    untracked = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(root), "ls-files", "-o", "--exclude-standard", "--", "*.py"],
                               capture_output=True, text=True)
    for rel in untracked.stdout.splitlines():
        path = root / rel
        if rel.strip() and path.is_file():
            n = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
            result.setdefault(rel, set()).update(range(1, n + 1))
    return {k: v for k, v in result.items() if v}


class _Collector(ast.NodeVisitor):
    def __init__(self, lines: set[int]):
        self.lines, self.sites = lines, []

    def generic_visit(self, node):
        line = getattr(node, "lineno", None)
        if line in self.lines:
            if isinstance(node, ast.Compare):
                for i, op in enumerate(node.ops):
                    if type(op) in COMPARE_SWAP:
                        self.sites.append((node, "compare", i))
            elif isinstance(node, ast.BinOp) and type(node.op) in BINOP_SWAP:
                self.sites.append((node, "binop", 0))
            elif isinstance(node, ast.BoolOp):
                self.sites.append((node, "boolop", 0))
            elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
                self.sites.append((node, "bool", 0))
            elif isinstance(node, ast.Constant) and type(node.value) in (int, float):
                self.sites.append((node, "number", 0))
            elif isinstance(node, ast.Return) and node.value is not None:
                self.sites.append((node, "return", 0))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                self.sites.append((node, "not", 0))
        super().generic_visit(node)


def mutants_for(path: str, source: str, lines: set[int]) -> list[Mutant]:
    tree = ast.parse(source)
    col = _Collector(lines)
    col.visit(tree)
    out: list[Mutant] = []
    for idx in range(len(col.sites)):
        t = ast.parse(source)  # fresh tree per mutant
        c = _Collector(lines)
        c.visit(t)
        node, kind, i = c.sites[idx]
        desc = ""
        if kind == "compare":
            old = type(node.ops[i]); node.ops[i] = COMPARE_SWAP[old](); desc = f"{old.__name__} -> {type(node.ops[i]).__name__}"
        elif kind == "binop":
            old = type(node.op); node.op = BINOP_SWAP[old](); desc = f"{old.__name__} -> {type(node.op).__name__}"
        elif kind == "boolop":
            old = type(node.op); node.op = ast.Or() if old is ast.And else ast.And(); desc = f"{old.__name__} -> {type(node.op).__name__}"
        elif kind == "bool":
            desc = f"{node.value} -> {not node.value}"; node.value = not node.value
        elif kind == "number":
            desc = f"{node.value} -> {node.value + 1}"; node.value = node.value + 1
        elif kind == "return":
            desc = "return value -> None"; node.value = ast.Constant(None)
        elif kind == "not":
            desc = "remove 'not'"
            parent_holder = node
            # replace UnaryOp by its operand via a wrapper: not x -> (x)
            replacement = node.operand
            for p in ast.walk(t):
                for fname, value in ast.iter_fields(p):
                    if value is parent_holder:
                        setattr(p, fname, replacement)
                    elif isinstance(value, list):
                        for j, item in enumerate(value):
                            if item is parent_holder:
                                value[j] = replacement
        ast.fix_missing_locations(t)
        out.append(Mutant(path, node.lineno, desc, ast.unparse(t)))
    return out


class TestCommandError(RuntimeError):
    pass


def _run(cmd: str, cwd: Path, timeout: float, env: dict | None = None) -> bool:
    from .verify import split_cmd, sandboxed
    try:
        r = subprocess.run(sandboxed(split_cmd(cmd), env), cwd=cwd, capture_output=True, timeout=timeout, env=env)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False  # a hang counts as the tests catching the mutant
    except OSError as exc:
        raise TestCommandError(f"cannot run test command {cmd!r}: {exc}") from exc


def _is_test(path: str, globs: list[str] | None) -> bool:
    import fnmatch
    if globs:
        return any(fnmatch.fnmatch(path, g) or (g.endswith("/**") and path.startswith(g[:-2])) for g in globs)
    return Path(path).name.startswith("test_") or "/tests/" in f"/{path}"


def run(root: Path | str, base: str, test_cmd: str, time_budget_s: float = 300, per_test_timeout_s: float = 60,
        test_globs: list[str] | None = None, env: dict | None = None) -> MutationReport:
    root = Path(root).resolve()
    report = MutationReport()
    targets = changed_lines(root, base)
    targets = {f: l for f, l in targets.items() if not _is_test(f, test_globs)}
    report.changed_source = len(targets)
    if not targets:
        report.message = "no changed Python source lines to mutate"
        return report
    deadline = time.monotonic() + time_budget_s
    with tempfile.TemporaryDirectory(prefix="sparkwright-mut-") as td:
        work = Path(td) / "repo"
        shutil.copytree(root, work, ignore=IGNORE)
        try:
            baseline_passes = _run(test_cmd, work, per_test_timeout_s * 5, env)
        except TestCommandError as exc:
            report.baseline_ok = False
            report.message = str(exc)
            return report
        if not baseline_passes:
            report.baseline_ok = False
            report.message = "tests fail before mutation; fix them first"
            return report
        for rel, lines in sorted(targets.items()):
            src_path = work / rel
            if not src_path.is_file():
                continue
            original = src_path.read_text(encoding="utf-8")
            try:
                muts = mutants_for(rel, original, lines)
            except SyntaxError:
                continue
            for m in muts:
                if time.monotonic() > deadline:
                    report.timed_out_budget = True
                    break
                report.total += 1
                try:
                    src_path.write_text(m.source, encoding="utf-8")
                    survived = _run(test_cmd, work, per_test_timeout_s, env)
                finally:
                    src_path.write_text(original, encoding="utf-8")
                if survived:
                    report.survivors.append(m)
                else:
                    report.killed += 1
    if report.total == 0:
        report.message = "no mutants could be generated from the changed source lines"
    else:
        report.message = f"mutation score {report.score:.2f} ({report.killed}/{report.total} killed)" + (
            " (partial: time budget reached)" if report.partial else "")
    return report
