"""Neutral skill format (SYSTEM S8.3): authored once, rendered per host."""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources

from ..core.frontmatter import split


@dataclass
class Skill:
    name: str
    description: str
    cli: str
    personas: list[str] = field(default_factory=list)
    body: str = ""

    def render(self, **slots: str) -> str:
        out = self.body
        for key, value in slots.items():
            out = out.replace("{{" + key + "}}", value)
        if "{{" in out:
            raise ValueError(f"skill {self.name} has unfilled slots")
        return out


def load_skills() -> list[Skill]:
    out = []
    sdir = resources.files("sparkwright") / "data" / "skills"
    for entry in sorted(sdir.iterdir(), key=lambda e: e.name):
        if entry.name.endswith(".md"):
            meta, body, _ = split(entry.read_text(encoding="utf-8"))
            out.append(Skill(meta["name"], meta["description"], meta.get("cli", ""), list(meta.get("personas", [])), body))
    return out
