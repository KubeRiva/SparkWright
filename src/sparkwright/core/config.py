"""Project configuration (.sparkwright/config.yaml)."""
from __future__ import annotations

import copy
from pathlib import Path

from .frontmatter import FrontMatterError, load_yaml

CONFIG_PATH = ".sparkwright/config.yaml"
CONFIGURABLE_GATES = {"component", "task"}

DEFAULTS: dict = {
    "models": {},
    "roles": {},
    "budgets": {"per_run_usd": 10.0, "per_level_usd": {}},
    "gates": {"component": "auto", "task": "auto"},
    "checks": {},
    "prove": None,             # S5.6: command run for `prove: true` tasks; {files} = the task's changed source files
    "env": {},                 # extra environment for checks/builds; {repo} = main repository root
    "python": None,            # interpreter for the Library Checker (default: the one running sparkwright)
    "mutation": {"min": 0.8, "time_budget_s": 300},
    "calibration": {"min_catch_rate": 0.5},   # S10.3
    "security_review": {"min_changed_lines": 20},  # D006: high-risk builds with smaller source diffs skip it
    "review": {"disabled": []},               # personas a human removed from default reviews after calibration
    "approvers": [],           # [{name, email}] allowed to approve (S6.3, D002)
    "require_signed": False,
    "baseline": None,          # commit hash; trailer/drift checks apply after it
    "trailers": "required",    # required | warn | off
    "test_globs": ["tests/**/*", "test/**/*", "**/*_test.*", "**/*.test.*", "**/test_*.py"],
    # Paths no agent role may change, whatever the config says (S6.5, S6.6).
    "always_protected": [".sparkwright/config.yaml", "specs/approvals.jsonl", "specs/constitution.md",
                         "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".claude/**", ".codex/**", ".agents/**", ".gemini/**",
                         "personas/**"],
    "protected": {
        "builder": ["specs/**", ".sparkwright/config.yaml", "AGENTS.md", "personas/**"],
        "test-author": ["src/**", "specs/**"],
        "property-tester": ["src/**", "specs/**"],
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(root: Path | str) -> tuple[dict, list[str]]:
    """Return (config, errors). Missing file means defaults."""
    path = Path(root) / CONFIG_PATH
    errors: list[str] = []
    data: dict = {}
    if path.is_file():
        try:
            data = load_yaml(path.read_text(encoding="utf-8")) or {}
        except FrontMatterError as exc:
            return copy.deepcopy(DEFAULTS), [f"config: {exc}"]
        if not isinstance(data, dict):
            return copy.deepcopy(DEFAULTS), ["config: must be a mapping"]
    if data.get("trailers") is False:  # YAML reads unquoted `off` as False
        data["trailers"] = "off"
    if isinstance(data.get("protected"), dict):  # config may add protected paths, never remove defaults
        merged = {role: list(globs) for role, globs in DEFAULTS["protected"].items()}
        for role, globs in data["protected"].items():
            merged.setdefault(role, [])
            merged[role] = sorted(set(merged[role]) | set(globs or []))
        data["protected"] = merged
    gates = data.get("gates") or {}
    bad = sorted(set(gates) - CONFIGURABLE_GATES)
    if bad:
        errors.append(f"config: gates {bad} may not be overridden (only {sorted(CONFIGURABLE_GATES)})")
    for g, v in gates.items():
        if g in CONFIGURABLE_GATES and v not in ("auto", "human"):
            errors.append(f"config: gate '{g}' must be 'auto' or 'human'")
    if data.get("trailers", "required") not in ("required", "warn", "off"):
        errors.append("config: trailers must be required, warn or off")
    cfg = _merge(DEFAULTS, data)
    cfg["always_protected"] = sorted(set(DEFAULTS["always_protected"]) | set(data.get("always_protected") or []))
    return cfg, errors
