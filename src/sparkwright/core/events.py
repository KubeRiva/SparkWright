"""Append-only status events (SYSTEM S2.5, S2.8, decision D003)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import ids
from .approvals import now

EVENTS_PATH = "specs/events.jsonl"
EVENT_KINDS = {"changed", "building", "blocked", "done", "cr-applied", "reviewed"}


def reviewed_since(events: list["Event"], rid: str, text_hash: str, since: str | None) -> bool:
    """True when a non-failing review saw exactly this text at or after `since` (S3.10)."""
    return any(e.id == rid and e.event == "reviewed" and (since is None or e.time >= since)
               and (e.reason or "").split(" ")[-1] == text_hash for e in events)


@dataclass
class Event:
    id: str
    event: str
    time: str
    run: str | None = None
    reason: str | None = None


def read(root: Path | str) -> tuple[list[Event], list[str]]:
    path = Path(root) / EVENTS_PATH
    out: list[Event] = []
    errors: list[str] = []
    if not path.is_file():
        return out, errors
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if d["event"] not in EVENT_KINDS:
                raise KeyError(f"unknown event {d['event']!r}")
            out.append(Event(ids.canonical(str(d["id"])), d["event"], d["time"], d.get("run"), d.get("reason")))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append(f"{EVENTS_PATH}:{n}: invalid entry ({exc})")
    return out, errors


def append(root: Path | str, entries: list[Event]) -> None:
    path = Path(root) / EVENTS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps({k: v for k, v in asdict(e).items() if v is not None}, sort_keys=True) + "\n")


def make(rid: str, event: str, run: str | None = None, reason: str | None = None) -> Event:
    return Event(ids.canonical(rid), event, now(), run, reason)
