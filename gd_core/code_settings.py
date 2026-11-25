"""Shared Code Mode defaults and configuration normalization."""

from __future__ import annotations

import os
from typing import Any


DEFAULT_CODE_SETTINGS: dict[str, Any] = {
    "permission_mode": "project_autonomous",
    "max_iterations": 20,
    "command_timeout": 120,
    "ignored_dirs": [],
    "approved_patterns": [],
    "auto_index": True,
    "checkpoint_retention": 20,
    "allow_dependency_install": True,
    "editor_font_size": 11,
    "tab_size": 4,
    "default_project_dir": ".",
}


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def normalize_code_settings(value: Any) -> dict[str, Any]:
    data = value if isinstance(value, dict) else {}
    settings = {**DEFAULT_CODE_SETTINGS, **data}
    if settings["permission_mode"] not in {"supervised", "project_autonomous", "advanced"}:
        settings["permission_mode"] = "project_autonomous"
    settings["max_iterations"] = _bounded_int(settings.get("max_iterations"), 20, 1, 100)
    settings["command_timeout"] = _bounded_int(settings.get("command_timeout"), 120, 5, 3600)
    settings["checkpoint_retention"] = _bounded_int(settings.get("checkpoint_retention"), 20, 1, 200)
    settings["editor_font_size"] = _bounded_int(settings.get("editor_font_size"), 11, 8, 24)
    settings["tab_size"] = _bounded_int(settings.get("tab_size"), 4, 2, 8)
    settings["auto_index"] = bool(settings.get("auto_index", True))
    settings["allow_dependency_install"] = bool(settings.get("allow_dependency_install", True))
    ignored = settings.get("ignored_dirs") or []
    if isinstance(ignored, str):
        ignored = [item.strip() for item in ignored.splitlines() if item.strip()]
    settings["ignored_dirs"] = [str(item).strip().replace("\\", "/").strip("/") for item in ignored if str(item).strip()]
    approved = settings.get("approved_patterns") or []
    if isinstance(approved, str):
        approved = [item.strip() for item in approved.splitlines() if item.strip()]
    settings["approved_patterns"] = [str(item).strip() for item in approved if str(item).strip()]
    default_dir = str(settings.get("default_project_dir") or ".").strip()
    settings["default_project_dir"] = default_dir if os.path.isdir(default_dir) else "."
    return settings
