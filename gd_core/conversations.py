"""conversations.py: Persistent per-conversation storage for Chat and Code modes."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

AUTO_TITLE_MAX_LEN = 48


def default_history_dir() -> Path:
    base = Path(os.getenv("APPDATA", os.path.expanduser("~"))) / "GD Assistant" / "history"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _new_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{os.urandom(3).hex()}"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ConversationStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.dir_path = Path(base_dir) if base_dir else default_history_dir()
        self.dir_path.mkdir(parents=True, exist_ok=True)

    def _path(self, conv_id: str) -> Path:
        return self.dir_path / f"{conv_id}.json"

    def list_conversations(self, kind: str, include_archived: bool = False) -> list[dict[str, Any]]:
        """Return conversations of one kind, newest activity first."""
        conversations: list[dict[str, Any]] = []
        for file_path in self.dir_path.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("type") != kind:
                continue
            if data.get("status", "active") != "active" and not include_archived:
                continue
            conversations.append(data)
        conversations.sort(key=lambda conv: conv.get("updated_at", ""), reverse=True)
        return conversations

    def create_conversation(
        self,
        kind: str,
        title: str = "",
        workspace: str | os.PathLike[str] | None = None,
        extra_dirs: list[str] | None = None,
    ) -> dict[str, Any]:
        now = _now()
        conversation: dict[str, Any] = {
            "id": _new_id(),
            "type": kind,
            "title": (title or "").strip() or "New Chat",
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "workspace": str(workspace) if workspace else "",
            "extra_dirs": list(extra_dirs or []),
            "titled": False,
            "messages": [],
        }
        self.save_conversation(conversation)
        return conversation

    def load_conversation(self, conv_id: str) -> dict[str, Any] | None:
        try:
            with open(self._path(conv_id), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def save_conversation(self, conversation: dict[str, Any]) -> None:
        conversation["updated_at"] = _now()
        try:
            with open(self._path(conversation["id"]), "w", encoding="utf-8") as f:
                json.dump(conversation, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def append_message(self, conv_id: str, role: str, content: str) -> None:
        conversation = self.load_conversation(conv_id)
        if conversation is None:
            return
        conversation.setdefault("messages", []).append({"role": role, "content": content})
        if role == "user" and not conversation.get("titled"):
            condensed = re.sub(r"\s+", " ", content).strip()
            if condensed:
                conversation["title"] = condensed[:AUTO_TITLE_MAX_LEN] + ("…" if len(condensed) > AUTO_TITLE_MAX_LEN else "")
                conversation["titled"] = True
        self.save_conversation(conversation)

    def rename_conversation(self, conv_id: str, title: str) -> None:
        conversation = self.load_conversation(conv_id)
        if conversation is None:
            return
        conversation["title"] = title.strip() or conversation.get("title", "")
        conversation["titled"] = True
        self.save_conversation(conversation)

    def set_status(self, conv_id: str, status: str) -> None:
        conversation = self.load_conversation(conv_id)
        if conversation is None:
            return
        conversation["status"] = status
        self.save_conversation(conversation)

    def delete_conversation(self, conv_id: str) -> None:
        try:
            self._path(conv_id).unlink()
        except OSError:
            pass

    def convert_to_code(self, conv_id: str, workspace: str | os.PathLike[str]) -> None:
        """One-way conversion: a chat becomes a Code project and never reverts."""
        conversation = self.load_conversation(conv_id)
        if conversation is None:
            return
        conversation["type"] = "code"
        conversation["workspace"] = str(workspace)
        conversation["extra_dirs"] = []
        self.save_conversation(conversation)
