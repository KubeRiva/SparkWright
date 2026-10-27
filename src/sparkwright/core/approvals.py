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
    risk: str | None = None  # risk tier of the owning file when approved (S6.2)
    hash2: str | None = None  # D007: also locks parent refs and acceptance criteria


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
            out.append(Approval(aid, d["hash"], d["approver"], d["role"], cr, d["time"],
                                str(d["risk"]) if d.get("risk") else None, d.get("hash2")))
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            errors.append(f"{APPROVALS_PATH}:{n}: invalid entry ({exc})")
    return out, errors


def latest(entries: list[Approval]) -> dict[str, Approval]:
    result: dict[str, Approval] = {}
    for e in entries:  # file order is chronological; last one wins
        if e.role != "human" and not e.id.startswith("test:"):
            continue  # D009: only test locks may come from the runner; anything else never counts
        result[e.id] = e
    return result


def append(root: Path | str, entries: list[Approval]) -> None:
    path = Path(root) / APPROVALS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for e in entries:
            d = asdict(e)
            for k in ("risk", "hash2"):
                if d.get(k) is None:
                    d.pop(k, None)
            if d.get("hash2"):
                d["v"] = 2  # hash scheme version (D009): version 2 = hash + hash2 as defined in SYSTEM "Hashes"
            fh.write(json.dumps(d, sort_keys=True) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def risk_of(repo, rid: str) -> str | None:
    """Risk tier of the file that owns a requirement (None when the file declares none)."""
    sf = repo.file_of.get(rid)
    r = sf.meta.get("risk") if sf is not None else None
    return str(r).strip().lower() if r else None


def risk_matches(appr: Approval, repo, rid: str) -> bool:
    """An approval recorded under another risk tier no longer counts (S6.2: risk changes need a human)."""
    return appr.risk is None or appr.risk.strip().lower() == risk_of(repo, rid)


def matches(appr: Approval, req) -> bool:
    """The approval still holds for this requirement's current content (D007: hash2 when recorded)."""
    if appr.hash != req.hash:
        return False
    return appr.hash2 is None or appr.hash2 == req.hash2
