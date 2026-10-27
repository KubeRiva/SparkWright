"""Resumable run logs (SYSTEM S3.2, S9.3)."""
from __future__ import annotations

import json

from ..core.secrets import redact
import re
import time
import uuid
from pathlib import Path

RUNS_DIR = ".sparkwright/runs"


class RunLog:
    def __init__(self, root: Path | str, workflow: str, run_id: str | None = None):
        self.root = Path(root)
        self.workflow = workflow
        self.run_id = run_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{workflow}-{uuid.uuid4().hex[:6]}"
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.run_id) or ".." in self.run_id:
            raise ValueError(f"invalid run id {self.run_id!r}")
        runs = (self.root / RUNS_DIR).resolve()
        self.path = (runs / f"{self.run_id}.jsonl").resolve()
        if runs not in self.path.parents:
            raise ValueError(f"run id {self.run_id!r} points outside {RUNS_DIR}")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, step: str, **data) -> None:
        rec = {"run": self.run_id, "workflow": self.workflow, "step": step, **data}
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(redact(json.dumps(rec, sort_keys=True)) + "\n")  # S11.3

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn write must not break resume
        return out

    def completed(self) -> dict[str, dict]:
        """Map step name -> its 'done' record, used to resume an interrupted run."""
        return {r["step"]: r for r in self.records() if r.get("status") == "done"}

    def total_cost(self) -> float:
        return sum(float(r.get("cost_usd", 0) or 0) for r in self.records())
