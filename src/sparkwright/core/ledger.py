"""Traceability ledger: the generated graph of requirements, tests and commits (SYSTEM S2.1, S2.2)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import ids
from .approvals import Approval
from .gitlog import Commit
from .store import Repo

LEDGER_PATH = ".sparkwright/ledger.json"


@dataclass
class Node:
    id: str
    kind: str
    refs: list[str]
    file: str
    line: int
    status: str
    hash: str | None = None
    approved_hash: str | None = None
    children: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def build(repo: Repo, approvals: dict[str, Approval], tests: dict[str, list[str]], commits: list[Commit]) -> dict[str, Node]:
    nodes: dict[str, Node] = {}
    for eid, ev in repo.evidence.items():
        nodes[eid] = Node(eid, "evidence", [], ev.file, 1, ev.status)
    for rid, r in repo.requirements.items():
        nodes[rid] = Node(
            rid, r.kind, list(r.refs), r.file, r.line, repo.status_of(rid), r.hash,
            approvals[rid].hash if rid in approvals else None,
            tests=list(tests.get(rid, [])), files=list(r.extras.get("files", [])),
        )
    for n in list(nodes.values()):
        for ref in n.refs:
            if ref in nodes:
                nodes[ref].children.append(n.id)
    for c in commits:
        for t in c.tasks:
            if t in nodes:
                nodes[t].commits.append(c.sha[:12])
    for n in nodes.values():
        n.children.sort(key=ids.sort_key)
    return dict(sorted(nodes.items(), key=lambda kv: ids.sort_key(kv[0])))


def to_json(nodes: dict[str, Node]) -> str:
    return json.dumps({k: asdict(v) for k, v in nodes.items()}, sort_keys=True, indent=2) + "\n"


def write(root: Path | str, nodes: dict[str, Node]) -> Path:
    path = Path(root) / LEDGER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(nodes), encoding="utf-8", newline="\n")
    return path


def ancestors(nodes: dict[str, Node], rid: str) -> list[list[str]]:
    """All paths from rid up to roots, each path ordered rid -> root."""
    if rid not in nodes:
        return []
    paths: list[list[str]] = []

    def walk(cur: str, acc: list[str]) -> None:
        refs = [r for r in nodes[cur].refs if r in nodes] if cur in nodes else []
        if not refs:
            paths.append(acc)
            return
        for r in refs:
            if r in acc:  # cycle guard
                paths.append(acc + [r])
                continue
            walk(r, acc + [r])

    walk(rid, [rid])
    return paths


def descendants(nodes: dict[str, Node], rid: str) -> dict:
    """Nested tree of children with tests and commits."""
    seen: set[str] = set()

    def tree(cur: str) -> dict:
        n = nodes[cur]
        seen.add(cur)
        return {
            "id": cur, "kind": n.kind, "status": n.status,
            "tests": n.tests, "commits": n.commits,
            "children": [tree(c) for c in n.children if c not in seen],
        }

    return tree(rid) if rid in nodes else {}
