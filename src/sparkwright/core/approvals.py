"""Append-only approvals log (SYSTEM S2.4, S6.3)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import ids

APPROVALS_PATH = "specs/approvals.jsonl"


@dataclass
class Approval:
    id: str
    hash: str
    approver: str
    role: str
    change_request: str | None
    time: str


def read(root: Path | str) -> tuple[list[Approval], list[str]]:
    path = Path(root) / APPROVALS_PATH
    out: list[Approval] = []
    errors: list[str] = []
    if not path.is_file():
        return out, errors
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            aid = d["id"] if str(d["id"]).startswith("test:") else ids.canonical(str(d["id"]))
            cr = ids.canonical(d["change_request"]) if d.get("change_request") else None
            out.append(Approval(aid, d["hash"], d["approver"], d["role"], cr, d["time"]))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append(f"{APPROVALS_PATH}:{n}: invalid entry ({exc})")
    return out, errors


def latest(entries: list[Approval]) -> dict[str, Approval]:
    result: dict[str, Approval] = {}
    for e in entries:  # file order is chronological; last one wins
        result[e.id] = e
    return result


def append(root: Path | str, entries: list[Approval]) -> None:
    path = Path(root) / APPROVALS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(asdict(e), sort_keys=True) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")
