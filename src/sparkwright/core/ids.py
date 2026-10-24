"""Requirement ID grammar (SYSTEM S1.2)."""
from __future__ import annotations

import re

# Order matters: more specific patterns first (task before component).
_KINDS: list[tuple[str, str]] = [
    ("task", r"C\d+\.\d+\.\d+\.T\d+"),
    ("component", r"C\d+\.\d+\.\d+"),
    ("change", r"CR\d+"),
    ("system", r"S\d+\.\d+"),
    ("vision", r"V\d+"),
    ("evidence", r"E\d+"),
    ("assumption", r"A\d+"),
    ("review", r"R\d+"),
    ("decision", r"D\d+"),
]
_COMPILED = [(k, re.compile(p)) for k, p in _KINDS]

ID_PATTERN = "|".join(f"(?:{p})" for _, p in _KINDS)

#: Levels that form the spec pyramid, top to bottom.
PYRAMID = ["vision", "system", "component", "task"]

#: For each requirement kind, the kinds its refs must point to.
PARENT_KINDS: dict[str, tuple[str, ...]] = {
    "vision": ("evidence", "assumption"),
    "system": ("vision",),
    "component": ("system",),
    "task": ("component",),
    "assumption": (),
}

#: For each kind, the kind of its children in the pyramid.
CHILD_KIND: dict[str, str] = {
    "vision": "system",
    "system": "component",
    "component": "task",
}


def kind_of(identifier: str) -> str | None:
    """Return the kind of an ID, or None if it matches no known pattern."""
    for kind, pattern in _COMPILED:
        if pattern.fullmatch(identifier):
            return kind
    return None


def is_id(identifier: str) -> bool:
    return kind_of(identifier) is not None


def sort_key(identifier: str) -> tuple:
    """Natural sort: V2 before V10, S1.2 before S1.10."""
    parts = re.split(r"(\d+)", identifier)
    return tuple(int(p) if p.isdigit() else p for p in parts)


def canonical(identifier: str) -> str:
    """Remove leading zeros from every number in an ID (S1.2): E01 -> E1, C02.3.01.T04 -> C2.3.1.T4."""
    if kind_of(identifier) is None:
        return identifier
    return re.sub(r"\d+", lambda m: str(int(m.group(0))), identifier)
