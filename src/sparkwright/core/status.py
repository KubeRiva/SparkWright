"""Derived per-requirement status (SYSTEM S2.8, decision D003)."""
from __future__ import annotations

from .approvals import Approval, risk_matches, matches as content_matches
from .events import Event
from .store import Repo

BUILD_EVENTS = {"building", "blocked", "done"}


def derive(repo: Repo, latest_approvals: dict[str, Approval], events: list[Event]) -> dict[str, str]:
    """Return {requirement id: derived status}. Event and approval order is file order (append-only)."""
    timeline: dict[str, list[tuple[int, str, object]]] = {}
    seq = 0
    for e in events:
        seq += 1
        timeline.setdefault(e.id, []).append((seq, "event", e))
    # approvals carry ISO times; events too. Merge by time, events and approvals with equal time keep file order.
    out: dict[str, str] = {}
    for rid, req in repo.requirements.items():
        appr = latest_approvals.get(rid)
        approved_now = appr is not None and content_matches(appr, req) and risk_matches(appr, repo, rid)
        if appr is not None and content_matches(appr, req) and not risk_matches(appr, repo, rid):
            out[rid] = "draft"  # S6.2: the risk tier changed since approval; a human must re-approve first
            continue
        evs = [e for _, _, e in timeline.get(rid, [])]
        last_changed = max((e.time for e in evs if e.event == "changed"), default=None)
        if last_changed and not (approved_now and appr.time >= last_changed):
            applied = any(e.event == "cr-applied" and e.time >= last_changed for e in evs)
            out[rid] = "in-review" if applied else "changed"  # S3.10: an applied CR puts its target back in review
            continue
        build = [e for e in evs if e.event in BUILD_EVENTS and (last_changed is None or e.time >= last_changed)]
        if build:
            out[rid] = build[-1].event
            continue
        if approved_now:
            out[rid] = "approved"
            continue
        fm = repo.status_of(rid)
        out[rid] = fm if fm in ("draft", "in-review", "rejected") else "draft"
    return out
