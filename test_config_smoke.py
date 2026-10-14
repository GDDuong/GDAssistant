"""Round-trip check for config.json / api.json handling after the audit refactor.

Asserts the on-disk format is unchanged: same keys, same indent=4 JSON object,
defaults still seeded into config.json, only gemini_api_key in api.json.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

# Sandbox before importing main: CONFIG_PATH, API_CONFIG_PATH and the atexit
# temp-file cleanup all resolve %APPDATA% at import time.
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="gd_cfg_")
sys.path.insert(0, str(Path(__file__).parent))

import main

CONFIG_KEYS = {
    "model", "code_model", "share_chat_code_model", "theme", "hotkey",
    "hotkey_voice", "hotkey_code", "language", "voice_device",
    "wake_word_enabled", "wake_phrase", "personality",
}


def fresh():
    for path in (main.CONFIG_PATH, main.API_CONFIG_PATH):
        if path.exists():
            path.unlink()


def test_defaults_without_files():
    fresh()
    assert set(main.load_app_config()) == CONFIG_KEYS
    assert main.get_api_key() == ""


def test_config_keeps_every_default_and_the_written_value():
    fresh()
    main.save_app_config({"theme": "light", "extra_key": 1})
    raw = main.CONFIG_PATH.read_text(encoding="utf-8")
    assert raw == json.dumps(main.load_app_config(), indent=4), "config.json drifted"
    on_disk = json.loads(raw)
    assert CONFIG_KEYS <= set(on_disk), "defaults were not seeded"
    assert on_disk["theme"] == "light" and on_disk["extra_key"] == 1


def test_api_key_round_trip_strips_and_isolates():
    fresh()
    main.save_api_key("  secret123  ")
    raw = main.API_CONFIG_PATH.read_text(encoding="utf-8")
    assert raw == json.dumps({"gemini_api_key": "secret123"}, indent=4), raw
    assert main.get_api_key() == "secret123"
    assert set(main.load_app_config()) == CONFIG_KEYS, "api key leaked into config"


def test_corrupt_files_fall_back_without_raising():
    for corrupt in ("not json at all", "[1, 2, 3]", '{"gemini_api_key": 42}'):
        fresh()
        main.CONFIG_PATH.write_text(corrupt, encoding="utf-8")
        main.API_CONFIG_PATH.write_text(corrupt, encoding="utf-8")
        # A config.json that is a dict still merges unknown keys, as before.
        assert CONFIG_KEYS <= set(main.load_app_config()), corrupt
        assert main.get_api_key() == ""


def test_environment_key_wins():
    fresh()
    main.save_api_key("from-file")
    os.environ["GEMINI_API_KEY"] = "  from-env  "
    assert main.get_api_key() == "from-env"
    del os.environ["GEMINI_API_KEY"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"OK  {fn.__name__}")
    print(f"\n{len(tests)} config checks passed")
