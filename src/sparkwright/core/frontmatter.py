"""YAML front matter parsing (SYSTEM S1.1, decision D001)."""
from __future__ import annotations

import yaml


class FrontMatterError(ValueError):
    pass


class _NoAliasLoader(yaml.SafeLoader):
    """SafeLoader that rejects anchors and aliases."""

    def compose_node(self, parent, index):  # type: ignore[override]
        if self.check_event(yaml.AliasEvent):
            raise FrontMatterError("YAML aliases are not allowed")
        event = self.peek_event()
        if getattr(event, "anchor", None):
            raise FrontMatterError("YAML anchors are not allowed")
        return super().compose_node(parent, index)


def load_yaml(text: str):
    try:
        return yaml.load(text, Loader=_NoAliasLoader)  # noqa: S506 (safe subclass)
    except yaml.YAMLError as exc:
        raise FrontMatterError(f"invalid YAML: {exc}") from exc


def split(text: str) -> tuple[dict, str, int]:
    """Split a Markdown document into (meta, body, body_first_line_number).

    Line numbers are 1-based. Documents without front matter return ({}, text, 1).
    """
    text = text.replace("\r\n", "\n").lstrip("\ufeff")
    if not text.startswith("---\n"):
        return {}, text, 1
    end = text.find("\n---\n", 4)
    if end == -1:
        if text.endswith("\n---"):
            end = len(text) - 4
        else:
            raise FrontMatterError("front matter is not closed with '---'")
    raw = text[4:end]
    meta = load_yaml(raw) or {}
    if not isinstance(meta, dict):
        raise FrontMatterError("front matter must be a mapping")
    for key in meta:
        if not isinstance(key, str):
            raise FrontMatterError("front matter keys must be strings")
    body = text[end + 5:]
    body_line = raw.count("\n") + 4  # lines: '---', raw lines, '---', then body
    return meta, body, body_line
