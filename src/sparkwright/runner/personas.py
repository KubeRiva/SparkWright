"""Persona definitions (SYSTEM S4.1).

Built-in personas ship in sparkwright/data/personas. A project may override one
by placing a file with the same name in ./personas/ (a human-gated path).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from ..core.frontmatter import split


@dataclass
class Persona:
    name: str
    version: str
    tier: str
    job: str
    never_sees: list[str] = field(default_factory=list)
    output: str = "findings"
    prompt: str = ""
    source: str = "builtin"

    def system_prompt(self) -> str:
        return f"persona: {self.name}\nversion: {self.version}\n\n{self.prompt.strip()}\n"


def _parse(text: str, source: str) -> Persona:
    meta, body, _ = split(text)
    return Persona(
        name=str(meta["name"]), version=str(meta.get("version", "1")), tier=str(meta.get("tier", "mid")),
        job=str(meta.get("job", "")), never_sees=list(meta.get("never_sees", [])),
        output=str(meta.get("output", "findings")), prompt=body, source=source,
    )


def load_all(root: Path | str | None = None) -> dict[str, Persona]:
    out: dict[str, Persona] = {}
    pdir = resources.files("sparkwright") / "data" / "personas"
    for entry in pdir.iterdir():
        if entry.name.endswith(".md"):
            p = _parse(entry.read_text(encoding="utf-8"), "builtin")
            out[p.name] = p
    if root is not None:
        local = Path(root) / "personas"
        if local.is_dir():
            for f in sorted(local.glob("*.md")):
                p = _parse(f.read_text(encoding="utf-8"), f"personas/{f.name}")
                out[p.name] = p
    return out
