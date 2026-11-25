"""Visible task plans and persistent Code Mode checkpoints."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


VALID_STATUSES = {"pending", "in_progress", "completed", "failed", "blocked"}


@dataclass
class PlanStep:
    title: str
    status: str = "pending"
    note: str = ""


@dataclass
class TaskPlan:
    request: str = ""
    steps: list[PlanStep] = field(default_factory=list)

    def set_steps(self, request: str, steps: list[str]) -> None:
        self.request = request
        self.steps = [PlanStep(title=str(title).strip()) for title in steps if str(title).strip()]

    def update(self, step_number: int, status: str, note: str = "") -> dict[str, Any]:
        if status not in VALID_STATUSES:
            return {"status": "FAILURE", "message": f"Invalid plan status: {status}"}
        if not 1 <= step_number <= len(self.steps):
            return {"status": "FAILURE", "message": "Plan step is out of range."}
        step = self.steps[step_number - 1]
        step.status = status
        if note:
            step.note = note
        return {"status": "SUCCESS", "message": f"Step {step_number} is {status}.", "plan": self.to_dict()}

    def to_dict(self) -> dict[str, Any]:
        completed = sum(step.status == "completed" for step in self.steps)
        return {
            "request": self.request,
            "steps": [asdict(step) for step in self.steps],
            "completed": completed,
            "total": len(self.steps),
            "progress": completed / len(self.steps) if self.steps else 0.0,
        }


class CheckpointStore:
    def __init__(self, project_root: str | os.PathLike[str], retention: int = 20) -> None:
        import hashlib

        key = hashlib.sha256(str(Path(project_root).resolve()).encode("utf-8")).hexdigest()[:20]
        base = Path(os.getenv("APPDATA", os.path.expanduser("~"))) / "GD Assistant" / "code-checkpoints"
        self.dir_path = base / key
        self.dir_path.mkdir(parents=True, exist_ok=True)
        self.retention = max(1, int(retention or 20))

    def _path(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id)[:100] or "task"
        return self.dir_path / f"{safe}.json"

    def save(self, task_id: str, checkpoint: dict[str, Any]) -> None:
        data = dict(checkpoint)
        data["task_id"] = task_id
        data["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._path(task_id).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        files = sorted(self.dir_path.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files[self.retention:]:
            try:
                path.unlink()
            except OSError:
                pass

    def load(self, task_id: str) -> dict[str, Any] | None:
        try:
            data = json.loads(self._path(task_id).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def latest(self) -> dict[str, Any] | None:
        files = sorted(self.dir_path.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("status") in {"running", "paused", "blocked", "failed"}:
                    return data
            except (OSError, ValueError):
                continue
        return None

    def list(self) -> list[dict[str, Any]]:
        results = []
        for path in self.dir_path.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(data)
            except (OSError, ValueError):
                continue
        results.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return results
