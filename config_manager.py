import json
import os
from pathlib import Path
from typing import Any

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_HOTKEY = "ctrl+alt+g"
DEFAULT_PERSONALITY = "You are GD Assistant, a helpful, concise, and friendly personal Windows desktop assistant."

def get_app_dir() -> Path:
    """Return the base application directory in APPDATA."""
    app_dir = Path(os.getenv("APPDATA", os.path.expanduser("~"))) / "GD Assistant"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

CONFIG_PATH = get_app_dir() / "config.json"
API_CONFIG_PATH = get_app_dir() / "api.json"

def load_app_config() -> dict[str, Any]:
    """Load model, hotkey, and personality configuration from APPDATA."""
    config = {
        "model": DEFAULT_MODEL,
        "hotkey": DEFAULT_HOTKEY,
        "personality": DEFAULT_PERSONALITY
    }
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open(encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    config.update(data)
        except Exception:
            pass
    return config

def save_app_config(config_data: dict[str, Any]) -> None:
    """Save configuration to APPDATA."""
    current = load_app_config()
    current.update(config_data)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(current, f, indent=4)

def get_api_key() -> str:
    """Read local API key, preferring environment variable."""
    environment_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if environment_key:
        return environment_key

    if API_CONFIG_PATH.exists():
        try:
            with API_CONFIG_PATH.open(encoding="utf-8") as config_file:
                config = json.load(config_file)
                if isinstance(config, dict):
                    key = config.get("gemini_api_key", "")
                    return key.strip() if isinstance(key, str) else ""
        except Exception:
            pass
    return ""

def save_api_key(api_key: str) -> None:
    """Save API key securely to local storage."""
    config_data = {}
    if API_CONFIG_PATH.exists():
        try:
            with API_CONFIG_PATH.open(encoding="utf-8") as f:
                config_data = json.load(f)
        except Exception:
            pass
    config_data["gemini_api_key"] = api_key.strip()
    with API_CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)