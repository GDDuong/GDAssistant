"""history.py: Session history manager for GD Assistant and Code Agent."""

import json
import os
from datetime import datetime

class HistoryManager:
    def __init__(self, filename="chat_history.json"):
        appdata = os.getenv("APPDATA")
        self.dir_path = os.path.join(appdata, "GD Assistant") if appdata else "."
        os.makedirs(self.dir_path, exist_ok=True)
        self.file_path = os.path.join(self.dir_path, filename)
        self.current_session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.sessions = self._load_all()

    def _load_all(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_session(self, messages):
        self.sessions[self.current_session_id] = {
            "updated_at": datetime.now().isoformat(),
            "messages": messages
        }
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.sessions, f, indent=2)
        except Exception:
            pass

    def get_session(self, session_id):
        return self.sessions.get(session_id, {}).get("messages", [])