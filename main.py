"""GD Assistant: a local Windows chat assistant with a safe tool allowlist."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import multiprocessing
from pathlib import Path
from typing import Any, Callable
import atexit
import glob
import tempfile
import time

from gd_core.attachments import display_summary, load_binary_parts, prepare_message
from gd_core.conversations import ConversationStore
from gd_core.translations import get_text
from ui_tk.mdrender import strip_markdown
from ui_tk.themes import get_theme
from ui_tk.tray import TrayDaemon

from gd_core.local_tools import (
    close_app,
    forget_info,
    get_all_memory,
    get_current_time,
    get_system_stats,
    load_memory,
    open_app,
    open_file,
    open_url,
    remember_info,
    search_files,
    take_screenshot,
    click_at,
    type_text,
    press_key,
    scroll_screen,
    confirm_action,
    set_timer,
    cancel_timer,
    list_windows,
    focus_window,
    minimize_all,
    write_local_file,
    read_local_file,
    search_and_read_webpage,
    get_clipboard,
    set_clipboard,
    media_control,
    get_battery_status,
    get_active_window,
)

APP_NAME = "GD Assistant"
APP_VERSION = "v0.5.1.2-ALPHA"
_active_root = None
_active_hwnd = None
_ui_mode = "chat"
_mutex_handle = None

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_CODE_MODEL = "gemini-3.5-flash-lite"
DEFAULT_HOTKEY = "ctrl+alt+g"
DEFAULT_VOICE_HOTKEY = "ctrl+alt+v"
DEFAULT_CODE_HOTKEY = "ctrl+alt+c"
DEFAULT_WAKE_PHRASE = "hey assistant"
DEFAULT_LANGUAGE = "en"
DEFAULT_PERSONALITY = ""
DEFAULT_THEME = "light"
COMMON_GEMINI_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
)

def get_system_instruction(personality: str) -> str:
    base = (
        "You are GD Assistant, a helpful personal Windows desktop assistant. "
        "You may use your approved local tools when requested: open_app, close_app, "
        "get_system_stats, search_files, open_url, get_current_time, remember_info, "
        "forget_info, get_all_memory, open_file, take_screenshot, click_at, type_text, "
        "press_key, scroll_screen, set_timer, cancel_timer, list_windows, focus_window, "
        "minimize_all, write_local_file, read_local_file, search_web, get_clipboard, "
        "set_clipboard, media_control, get_battery_status, and get_active_window. "
        "Never claim to have performed a computer action unless the tool result confirms it. "
        "The local tool result is authoritative: if its status is SUCCESS, say the action succeeded; "
        "if FAILURE, report that it failed. "
        "When identifying click targets from screenshots, always output coordinates "
        "using a normalized 0 to 1000 integer scale (where x=0, y=0 is top-left and x=1000, y=1000 is bottom-right). "
        "Keep responses concise, conversational, and under 2-3 sentences when possible. "
        "Each user message begins with a source tag: [TEXT] means it was typed in the chat box, "
        "[VOICE] means it was spoken through the microphone. "
        "Use GitHub-flavored markdown formatting (bold, italics, lists, headings, code blocks, links) "
        "ONLY when the message begins with [TEXT], because typed replies are displayed on screen. "
        "When the message begins with [VOICE] or has no tag, reply in plain conversational text with "
        "absolutely no markdown formatting, so it sounds natural when spoken aloud."
    )
    if personality and personality.strip():
        base += f"\n\nUser's Custom Persona/Instructions:\n{personality.strip()}"
    return base

MAX_TOOL_ROUNDS = 12
DEBUG_CONSOLE = False

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "open_app",
        "description": "Opens one approved Windows app. Only use when the user explicitly asks to open an app.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "The requested app name, for example 'Notepad'."}
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "close_app",
        "description": "Closes one running approved Windows app. Only use when the user explicitly asks to close an app.",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "The app to close, for example 'Notepad'."}
            },
            "required": ["app_name"],
        },
    },
    {
        "name": "get_system_stats",
        "description": "Reports current CPU, memory, and disk usage on the user's PC.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "search_files",
        "description": "Searches file names inside the user's home folder for a text query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for within file names."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_url",
        "description": "Opens an http or https URL in the user's default browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "An absolute https:// or https:// URL."}
            },
            "required": ["url"],
        },
    },
    {
        "name": "get_current_time",
        "description": "Returns the current local date and time.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "remember_info",
        "description": "Saves a piece of key-value information into persistent local memory.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Short topic name (e.g. 'favorite_browser', 'nickname')."},
                "value": {"type": "string", "description": "The information to remember."},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget_info",
        "description": "Deletes a specific key from local memory when requested by the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The memory key to delete."}
            },
            "required": ["key"],
        },
    },
    {
        "name": "get_all_memory",
        "description": "Lists all key-value entries stored in local persistent memory.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "open_file",
        "description": "Opens a local file or directory using the default Windows application.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "The absolute path to the local file or folder to open."}
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "take_screenshot",
        "description": "Captures the user's primary monitor display.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "click_at",
        "description": "Clicks the mouse at a target location on screen. Always use normalized coordinates (0-1000).",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Normalized X location (0 = far left, 1000 = far right)."},
                "y": {"type": "integer", "description": "Normalized Y location (0 = top edge, 1000 = bottom edge)."},
                "button": {"type": "string", "description": "Mouse button: 'left', 'right', or 'middle'. Default is 'left'."},
                "clicks": {"type": "integer", "description": "Number of clicks (1 for single click, 2 for double click)."},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Simulates keyboard keystrokes to type text directly into active focus.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The target text string to type out."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "press_key",
        "description": "Presses an individual key (e.g., 'enter', 'esc', 'space') or a shortcut combination (e.g., 'ctrl+c', 'alt+tab').",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key identifier or shortcut string."}
            },
            "required": ["key"],
        },
    },
    {
        "name": "scroll_screen",
        "description": "Scrolls primary display vertically. Positive integers scroll UP; negative integers scroll DOWN.",
        "parameters": {
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "Scroll distance units (e.g. -300 to scroll down, 300 to scroll up)."}
            },
            "required": ["amount"],
        },
    },
    {
        "name": "set_timer",
        "description": "Starts a countdown timer that beeps and shows a popup when it finishes. Use for requests like 'set a timer for 10 minutes' or 'remind me in 30 seconds'.",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "Countdown length in seconds (1 to 86400)."},
                "label": {"type": "string", "description": "Short name for the timer, e.g. 'tea' or 'meeting'."},
            },
            "required": ["seconds"],
        },
    },
    {
        "name": "cancel_timer",
        "description": "Cancels a running timer by its label.",
        "parameters": {
            "type": "object",
            "properties": {
                "label": {"type": "string", "description": "The timer label given when it was created."}
            },
            "required": ["label"],
        },
    },
    {
        "name": "list_windows",
        "description": "Lists the titles of all open windows on the desktop.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "focus_window",
        "description": "Brings an open window to the front (restores it if minimized), matched by a snippet of its title.",
        "parameters": {
            "type": "object",
            "properties": {
                "title_match": {"type": "string", "description": "Case-insensitive snippet of the window title, e.g. 'Notepad' or 'report.txt'."}
            },
            "required": ["title_match"],
        },
    },
    {
        "name": "minimize_all",
        "description": "Minimizes every open window except GD Assistant itself (like pressing Show Desktop).",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "write_local_file",
        "description": "Saves text to a file inside the user's home folder. Use for 'write this to a file', notes, or quick drafts.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path under the user's home directory."},
                "content": {"type": "string", "description": "The text to write."},
                "append": {"type": "boolean", "description": "True adds to the end of the file; default false replaces it."},
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "read_local_file",
        "description": "Reads a text file inside the user's home folder and returns its contents. Use for 'what does my file say' requests.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path under the user's home directory."}
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "search_web",
        "description": "Searches the web for a query, opens the top result, and returns a text summary of that page.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query, e.g. 'latest python release date'."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_clipboard",
        "description": "Returns the current text content of the clipboard.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "set_clipboard",
        "description": "Copies text to the clipboard, replacing its current content. Use for 'copy this' requests.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The text to copy to the clipboard."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "media_control",
        "description": "Controls media playback and system volume: play_pause, next, previous, volume_up, volume_down, or mute.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "One of: play_pause, next, previous, volume_up, volume_down, mute."}
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_battery_status",
        "description": "Reports battery percentage and charging state; says so clearly on desktops without a battery.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_active_window",
        "description": "Returns the title of the window that currently has focus.",
        "parameters": {"type": "object", "properties": {}},
    },
]

TOOL_REGISTRY: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "open_app": lambda args: open_app(args.get("app_name")),
    "close_app": lambda args: (
        close_app(args.get("app_name"))
        if confirm_action(f"Close application '{args.get('app_name')}'?")
        else {"status": "FAILURE", "message": "User blocked this action via security modal."}
    ),
    "get_system_stats": lambda _args: get_system_stats(),
    "search_files": lambda args: search_files(args.get("query")),
    "open_url": lambda args: open_url(args.get("url")),
    "get_current_time": lambda _args: get_current_time(),
    "remember_info": lambda args: remember_info(args.get("key", ""), args.get("value", "")),
    "forget_info": lambda args: forget_info(args.get("key", "")),
    "get_all_memory": lambda _args: get_all_memory(),
    "open_file": lambda args: open_file(args.get("file_path", "")),
    "take_screenshot": lambda _args: take_screenshot(),
    "click_at": lambda args: click_at(
        int(args.get("x", 0)),
        int(args.get("y", 0)),
        str(args.get("button", "left")),
        int(args.get("clicks", 1)),
    ),
    "type_text": lambda args: type_text(str(args.get("text", ""))),
    "press_key": lambda args: (
        press_key(str(args.get("key", "")))
        if not any(blocked in str(args.get("key", "")).lower() for blocked in ["alt+f4", "ctrl+w"])
        or confirm_action(f"Execute shortcut '{args.get('key')}'?")
        else {"status": "FAILURE", "message": "User blocked key action via security modal."}
    ),
    "scroll_screen": lambda args: scroll_screen(int(args.get("amount", 0))),
    "set_timer": lambda args: set_timer(args.get("seconds"), str(args.get("label", ""))),
    "cancel_timer": lambda args: cancel_timer(str(args.get("label", ""))),
    "list_windows": lambda _args: list_windows(),
    "focus_window": lambda args: focus_window(str(args.get("title_match", ""))),
    "minimize_all": lambda _args: (
        minimize_all()
        if confirm_action("Minimize all open windows?")
        else {"status": "FAILURE", "message": "User blocked this action via security modal."}
    ),
    "write_local_file": lambda args: write_local_file(
        str(args.get("file_path", "")),
        str(args.get("content", "")),
        bool(args.get("append", False)),
    ),
    "read_local_file": lambda args: read_local_file(str(args.get("file_path", "")), debug=DEBUG_CONSOLE),
    "search_web": lambda args: search_and_read_webpage(str(args.get("query", ""))),
    "get_clipboard": lambda _args: get_clipboard(),
    "set_clipboard": lambda args: set_clipboard(str(args.get("text", "")), debug=DEBUG_CONSOLE),
    "media_control": lambda args: media_control(str(args.get("action", "")), debug=DEBUG_CONSOLE),
    "get_battery_status": lambda _args: get_battery_status(),
    "get_active_window": lambda _args: get_active_window(),
}

def get_audio_save_path() -> Path:
    return Path(tempfile.gettempdir()) / "gd_assistant_recording.wav"

def check_single_instance() -> bool:
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    mutex_name = "Global\\GDAssistant_SingleInstance_Mutex"
    global _mutex_handle
    _mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)
    if kernel32.GetLastError() == 183:
        return False
    return True

def get_app_dir() -> Path:
    app_dir = Path(os.getenv("APPDATA", os.path.expanduser("~"))) / "GD Assistant"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

CONFIG_PATH = get_app_dir() / "config.json"
API_CONFIG_PATH = get_app_dir() / "api.json"

def hide_console_window() -> None:
    if sys.platform == "win32":
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)

def log_debug(message: str) -> None:
    if DEBUG_CONSOLE:
        print(message, flush=True)

def load_app_config() -> dict[str, Any]:
    config = {
        "model": DEFAULT_MODEL,
        "code_model": DEFAULT_CODE_MODEL,
        "share_chat_code_model": True,
        "theme": DEFAULT_THEME,
        "hotkey": DEFAULT_HOTKEY,
        "hotkey_voice": DEFAULT_VOICE_HOTKEY,
        "hotkey_code": DEFAULT_CODE_HOTKEY,
        "language": DEFAULT_LANGUAGE,
        "voice_device": None,
        "wake_word_enabled": False,
        "wake_phrase": DEFAULT_WAKE_PHRASE,
        "voice_orb_enabled": True,
        # 0.93 ≈ the shipped glass look (alpha ~237); 1.0 = fully opaque.
        "window_opacity": 0.93,
        "maximize_opaque": True,
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
    current = load_app_config()
    current.update(config_data)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(current, f, indent=4)


_qt_service = None
_qt_lock = threading.Lock()
_orb_expanded = False


def _orb_raise_main_window() -> None:
    """Clicking a truncated answer pill expands into the chat window."""
    service = get_qt_service()
    if service is None:
        return
    if not service.chat_raise():
        service.chat_op("show")


def wire_orb_expand(orb) -> None:
    """Connect the pill's expandRequested exactly once (per voice turn)."""
    global _orb_expanded
    if orb is None or _orb_expanded:
        return
    _orb_expanded = True
    try:
        orb.on_expand(_orb_raise_main_window)
    except Exception:
        pass


def menu_descriptors(menu: Any) -> list[dict[str, Any]]:
    """Describe a tk.Menu as plain data for the Qt popup renderer. Indices
    stay aligned with the menu entries so Qt can invoke the Tk command."""
    items: list[dict[str, Any]] = []
    last = menu.index("end")
    if last is None:
        return items
    for index in range(last + 1):
        if menu.type(index) == "separator":
            items.append({"separator": True})
            continue
        items.append({
            "label": menu.entrycget(index, "label"),
            "enabled": str(menu.entrycget(index, "state")) != "disabled",
        })
    return items


def invoke_menu_item(menu: Any, index: int) -> None:
    try:
        menu.invoke(index)
    except Exception as error:
        log_debug(f"[QT] menu entry {index} failed: {error}")


def get_qt_service(debug_flag: bool = False):
    """Lazily start the shared Qt UI service (menu popups, settings window,
    voice orb). Returns None if Qt is unavailable — the Tk app must never
    break because of the Qt layer (incremental-migration rule)."""
    global _qt_service
    with _qt_lock:
        if _qt_service is None:
            try:
                from ui_qt.service import QtUiService

                _qt_service = QtUiService()
                log_debug(
                    f"[QT] motion tick {_qt_service.motion_tick_ms} ms (refresh-matched)"
                )
            except Exception as error:
                log_debug(f"[QT] unavailable: {error}")
                return None
        return _qt_service

_hotkey_registry: dict[str, dict[str, Any]] = {}

def register_hotkey(action: str, keys: str, callback) -> bool:
    """Bind (or rebind) a global shortcut for a named action."""
    unregister_hotkey(action)
    try:
        import keyboard
        handle = keyboard.add_hotkey(keys, callback)
    except Exception as error:
        log_debug(f"[HOTKEY] Failed to register '{keys}' for '{action}': {error}")
        return False
    _hotkey_registry[action] = {"keys": keys, "handle": handle, "callback": callback}
    log_debug(f"[HOTKEY] Registered '{keys}' for '{action}'")
    return True

def unregister_hotkey(action: str) -> None:
    entry = _hotkey_registry.pop(action, None)
    if entry is None:
        return
    log_debug(f"[HOTKEY] Unregistered '{entry['keys']}' from '{action}'")
    try:
        import keyboard
        keyboard.remove_hotkey(entry["handle"])
    except Exception:
        pass

def update_hotkey(action: str, keys: str) -> bool:
    """Re-point an already-bound action at a new key combination."""
    entry = _hotkey_registry.get(action)
    if entry is None:
        return True
    if entry["keys"] == keys:
        return True
    log_debug(f"[HOTKEY] Rebinding '{action}': '{entry['keys']}' -> '{keys}'")
    return register_hotkey(action, keys, entry["callback"])


def get_code_model(config: dict[str, Any], chat_model: str) -> str:
    """Select the configured code model, optionally sharing the chat model."""
    if config.get("share_chat_code_model", True):
        return chat_model
    return str(config.get("code_model", DEFAULT_CODE_MODEL)).strip() or DEFAULT_CODE_MODEL

def get_api_key() -> str:
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

def apply_combobox_style(window_root: Any, palette: dict[str, str]) -> None:
    """Style editable Combobox controls and their popup lists on Windows."""
    from tkinter import ttk

    style = ttk.Style(window_root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(
        "GDAssistant.TCombobox",
        fieldbackground=palette["input"],
        background=palette["button"],
        foreground=palette["foreground"],
        arrowcolor=palette["foreground"],
        bordercolor=palette["border"],
        lightcolor=palette["border"],
        darkcolor=palette["border"],
    )
    style.map(
        "GDAssistant.TCombobox",
        fieldbackground=[("disabled", palette["panel"]), ("readonly", palette["input"])],
        foreground=[("disabled", palette["muted"])],
        selectbackground=[("readonly", palette["accent"])],
        selectforeground=[("readonly", "#ffffff")],
    )
    window_root.option_add("*TCombobox*Listbox.background", palette["panel"])
    window_root.option_add("*TCombobox*Listbox.foreground", palette["foreground"])
    window_root.option_add("*TCombobox*Listbox.selectBackground", palette["accent"])
    window_root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

def open_wizard_window(title: str, geometry: str, theme: str) -> tuple[Any, dict[str, str]]:
    """Create one themed setup-wizard window and return it with its palette."""
    import tkinter as tk

    palette = get_theme(theme)
    root = tk.Tk()
    root.title(title)
    root.geometry(geometry)
    root.resizable(False, False)
    root.configure(padx=20, pady=20, bg=palette["background"])
    apply_combobox_style(root, palette)
    return root, palette

def run_setup_wizard_lang() -> str | None:
    """Wizard Step 0: Language Selection."""
    import tkinter as tk
    result = {"lang": None, "success": False}

    root, colors = open_wizard_window(get_text("wizard_lang_title", "en"), "400x200", "light")

    label_options = {"bg": colors["background"], "fg": colors["foreground"]}
    tk.Label(root, text=get_text("wizard_lang_heading", "en"), font=("Arial", 14, "bold"), **label_options).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_lang_sub", "en"), font=("Arial", 9), **label_options).pack(anchor="w", pady=(0, 15))

    def on_select(lang_code):
        result["lang"] = lang_code
        result["success"] = True
        root.destroy()

    tk.Button(root, text="English", command=lambda: on_select("en"), bg=colors["accent"], fg="#ffffff", activebackground=colors["accent_active"], activeforeground="#ffffff", width=20).pack(pady=5)
    tk.Button(root, text="Tiếng Việt", command=lambda: on_select("vi"), bg=colors["accent"], fg="#ffffff", activebackground=colors["accent_active"], activeforeground="#ffffff", width=20).pack(pady=5)

    root.mainloop()
    return result["lang"] if result["success"] else None

def run_setup_wizard_step1(lang: str, theme: str = DEFAULT_THEME) -> tuple[str, str, str, bool] | None:
    """Wizard Step 2: Input API key and choose the chat/code models."""
    import tkinter as tk
    from tkinter import messagebox
    from tkinter import ttk
    result = {"key": "", "model": DEFAULT_MODEL, "code_model": DEFAULT_CODE_MODEL, "share": True, "success": False}

    root, colors = open_wizard_window(get_text("wizard_step1_title", lang), "460x400", theme)

    label_options = {"bg": colors["background"], "fg": colors["foreground"]}
    entry_options = {
        "bg": colors["input"],
        "fg": colors["foreground"],
        "insertbackground": colors["foreground"],
        "highlightbackground": colors["border"],
        "highlightcolor": colors["accent"],
    }

    tk.Label(root, text=get_text("wizard_step1_heading", lang), font=("Arial", 14, "bold"), **label_options).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_step1_sub", lang), font=("Arial", 9), **label_options).pack(anchor="w", pady=(0, 10))

    tk.Label(root, text=get_text("api_key_label", lang), font=("Arial", 9, "bold"), **label_options).pack(anchor="w")
    entry_box = tk.Entry(root, width=52, show="*", **entry_options)
    entry_box.pack(anchor="w", pady=(3, 10))
    entry_box.focus_set()

    tk.Label(root, text=get_text("chat_model_label", lang), font=("Arial", 9, "bold"), **label_options).pack(anchor="w")
    model_entry = ttk.Combobox(root, width=52, values=COMMON_GEMINI_MODELS, state="normal", style="GDAssistant.TCombobox")
    model_entry.set(DEFAULT_MODEL)
    model_entry.pack(anchor="w", pady=(3, 6))

    share_var = tk.BooleanVar(value=True)
    share_check = tk.Checkbutton(
        root,
        text=get_text("share_models_label", lang),
        variable=share_var,
        bg=colors["background"],
        fg=colors["foreground"],
        activebackground=colors["background"],
        activeforeground=colors["foreground"],
        selectcolor=colors["input"],
        justify=tk.LEFT,
        wraplength=420,
    )
    share_check.pack(anchor="w", pady=(0, 6))

    tk.Label(root, text=get_text("code_model_label", lang), font=("Arial", 9, "bold"), **label_options).pack(anchor="w")
    code_model_entry = ttk.Combobox(root, width=52, values=COMMON_GEMINI_MODELS, state="normal", style="GDAssistant.TCombobox")
    code_model_entry.set(DEFAULT_CODE_MODEL)
    code_model_entry.pack(anchor="w", pady=(3, 15))

    def update_code_model_state() -> None:
        code_model_entry.configure(state=tk.DISABLED if share_var.get() else "normal")

    share_check.configure(command=update_code_model_state)
    update_code_model_state()

    def on_confirm():
        entered_key = entry_box.get().strip()
        if not entered_key:
            messagebox.showerror("Error", get_text("err_empty_key", lang), parent=root)
            return
        result["key"] = entered_key
        result["model"] = model_entry.get().strip() or DEFAULT_MODEL
        result["code_model"] = code_model_entry.get().strip() or DEFAULT_CODE_MODEL
        result["share"] = share_var.get()
        result["success"] = True
        root.destroy()

    tk.Button(
        root,
        text=get_text("btn_next", lang),
        command=on_confirm,
        bg=colors["accent"],
        fg="#ffffff",
        activebackground=colors["accent_active"],
        activeforeground="#ffffff",
        width=16,
    ).pack(anchor="e")
    root.mainloop()
    if not result["success"]:
        return None
    return (result["key"], result["model"], result["code_model"], result["share"])

def run_setup_wizard_theme(lang: str) -> str | None:
    """Wizard Step 1: Pick the interface theme."""
    import tkinter as tk
    result = {"theme": DEFAULT_THEME, "success": False}

    root, colors = open_wizard_window(get_text("wizard_prefs_title", lang), "400x200", "light")

    label_options = {"bg": colors["background"], "fg": colors["foreground"]}
    tk.Label(root, text=get_text("wizard_prefs_heading", lang), font=("Arial", 14, "bold"), **label_options).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_prefs_sub", lang), font=("Arial", 9), **label_options).pack(anchor="w", pady=(0, 15))

    def on_select(choice: str) -> None:
        result["theme"] = choice
        result["success"] = True
        root.destroy()

    # Light is the recommended default, so it leads and takes initial focus.
    light_btn = tk.Button(root, text=get_text("appearance_light", lang), command=lambda: on_select("light"), bg=colors["accent"], fg="#ffffff", activebackground=colors["accent_active"], activeforeground="#ffffff", width=20)
    light_btn.pack(pady=5)
    light_btn.focus_set()
    tk.Button(root, text=get_text("appearance_dark", lang), command=lambda: on_select("dark"), bg=colors["accent"], fg="#ffffff", activebackground=colors["accent_active"], activeforeground="#ffffff", width=20).pack(pady=5)

    root.bind("<Return>", lambda _event: on_select("light"))
    root.mainloop()
    return result["theme"] if result["success"] else None

def run_setup_wizard_step2(lang: str, theme: str = DEFAULT_THEME) -> tuple[str, int | None] | None:
    """Wizard Step 3: Choose the microphone and configure keybinds."""
    import tkinter as tk
    from tkinter import ttk
    hotkey_holder = {"hotkey": DEFAULT_HOTKEY, "device": None, "success": False}

    root, colors = open_wizard_window(get_text("wizard_step2_title", lang), "460x300", theme)

    label_options = {"bg": colors["background"], "fg": colors["foreground"]}
    entry_options = {
        "bg": colors["input"],
        "fg": colors["foreground"],
        "insertbackground": colors["foreground"],
        "highlightbackground": colors["border"],
        "highlightcolor": colors["accent"],
    }

    tk.Label(root, text=get_text("wizard_step2_heading", lang), font=("Arial", 14, "bold"), **label_options).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_step2_sub", lang), font=("Arial", 9), **label_options).pack(anchor="w", pady=(0, 15))

    from gd_core.voice import get_input_devices

    tk.Label(root, text=get_text("settings_mic_label", lang), font=("Arial", 9, "bold"), **label_options).pack(anchor="w")
    mic_devices = get_input_devices()
    mic_values = [get_text("mic_default_option", lang)] + [name for _, name in mic_devices]
    mic_entry = ttk.Combobox(root, width=52, values=mic_values, state="readonly", style="GDAssistant.TCombobox")
    mic_position = 0
    stored_device = load_app_config().get("voice_device")
    for position, (device_index, _) in enumerate(mic_devices, start=1):
        if device_index == stored_device:
            mic_position = position
            break
    mic_entry.current(mic_position)
    mic_entry.pack(anchor="w", pady=(3, 10))

    tk.Label(root, text=get_text("hotkey_label", lang), font=("Arial", 9, "bold"), **label_options).pack(anchor="w")
    hotkey_entry = tk.Entry(root, width=52, **entry_options)
    hotkey_entry.insert(0, DEFAULT_HOTKEY)
    hotkey_entry.pack(anchor="w", pady=(3, 20))
    hotkey_entry.focus_set()

    def on_save():
        mic_choice = mic_entry.current()
        val = hotkey_entry.get().strip()
        if not val or val == DEFAULT_HOTKEY:
            val = DEFAULT_HOTKEY
        hotkey_holder["hotkey"] = val
        hotkey_holder["device"] = None if mic_choice <= 0 else mic_devices[mic_choice - 1][0]
        hotkey_holder["success"] = True
        root.destroy()

    tk.Button(
        root,
        text=get_text("btn_next", lang),
        command=on_save,
        bg=colors["accent"],
        fg="#ffffff",
        activebackground=colors["accent_active"],
        activeforeground="#ffffff",
        width=16,
    ).pack(anchor="e")
    root.mainloop()
    return (hotkey_holder["hotkey"], hotkey_holder["device"]) if hotkey_holder["success"] else None

def run_setup_wizard_step3(lang: str, theme: str = DEFAULT_THEME) -> str | None:
    """Wizard Step 4: Configure Custom Personality."""
    import tkinter as tk
    result = {"personality": "", "success": False}

    root, colors = open_wizard_window(get_text("wizard_step3_title", lang), "460x320", theme)

    label_options = {"bg": colors["background"], "fg": colors["foreground"]}
    entry_options = {
        "bg": colors["input"],
        "fg": colors["foreground"],
        "insertbackground": colors["foreground"],
        "highlightbackground": colors["border"],
        "highlightcolor": colors["accent"],
    }

    tk.Label(root, text=get_text("wizard_step3_heading", lang), font=("Arial", 14, "bold"), **label_options).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_step3_sub", lang), font=("Arial", 9), justify="left", **label_options).pack(anchor="w", pady=(0, 15))

    tk.Label(root, text=get_text("personality_label", lang), font=("Arial", 9, "bold"), **label_options).pack(anchor="w")
    pers_text = tk.Text(root, height=5, width=52, **entry_options)
    pers_text.pack(anchor="w", pady=(3, 15))
    pers_text.focus_set()

    def on_finish():
        result["personality"] = pers_text.get("1.0", tk.END).strip()
        result["success"] = True
        root.destroy()

    tk.Button(
        root,
        text=get_text("btn_finish", lang),
        command=on_finish,
        bg=colors["accent"],
        fg="#ffffff",
        activebackground=colors["accent_active"],
        activeforeground="#ffffff",
        width=16,
    ).pack(anchor="e")
    root.mainloop()
    return result["personality"] if result["success"] else None

def load_client(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as error:
        raise RuntimeError("Missing dependency. Run: python -m pip install -r requirements.txt") from error
    return genai.Client(api_key=api_key)

def execute_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    log_debug(f"[TOOL REQUEST] Executing tool '{name}' with arguments: {arguments}")
    handler = TOOL_REGISTRY.get(name)
    if handler is None:
        result = {"status": "FAILURE", "message": f"Tool '{name}' is not approved."}
    else:
        try:
            result = handler(arguments)
        except Exception as error:
            log_debug(f"[TOOL ERROR] Exception during '{name}': {type(error).__name__}: {error}")
            result = {"status": "FAILURE", "message": f"'{name}' failed unexpectedly."}

    status = result.get("status", "UNKNOWN")
    details = result.get("message") or result.get("data") or "No details."
    log_debug(f"[TOOL RESULT] Status: {status} | Details: {details}")
    return result

def _response_parts(item: Any) -> list[Any]:
    candidates = getattr(item, "candidates", None) or []
    content = getattr(candidates[0], "content", None) if candidates else None
    return list(getattr(content, "parts", None) or [])

def send_message_with_tools(
    client: Any,
    model: str,
    config: Any,
    history: list[Any],
    on_text: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> str:
    from google.genai import types

    streamed_pieces: list[str] = []

    def emit_text(text: str) -> None:
        if not text:
            return
        streamed_pieces.append(text)
        if on_text is not None:
            on_text(text)

    def stream_round() -> tuple[list[Any], bool]:
        parts: list[Any] = []
        try:
            stream = client.models.generate_content_stream(model=model, contents=history, config=config)
            for chunk in stream:
                if stop_event is not None and stop_event.is_set():
                    return parts, True
                for part in _response_parts(chunk):
                    parts.append(part)
                    text = getattr(part, "text", None)
                    if text and not getattr(part, "thought", False):
                        emit_text(text)
        except Exception as error:
            if parts:
                log_debug(f"[GEMINI API] Stream interrupted mid-response: {type(error).__name__}: {error}")
                return parts, True
            log_debug(f"[GEMINI API] Streaming unavailable ({type(error).__name__}); using standard request.")
            response = client.models.generate_content(model=model, contents=history, config=config)
            return _response_parts(response), False
        return parts, False

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        log_debug(f"[GEMINI API] Sending prompt turn to model ({model}) [Round {round_num}]...")
        parts, interrupted = stream_round()
        function_calls = [
            part.function_call for part in parts if getattr(part, "function_call", None) is not None
        ]

        if interrupted:
            # A truncated turn must not carry dangling function calls, or the
            # next request would demand tool responses that never ran.
            safe_parts = [part for part in parts if getattr(part, "function_call", None) is None]
            if safe_parts:
                history.append(types.Content(role="model", parts=safe_parts))
            return "".join(streamed_pieces)

        if not function_calls:
            log_debug("[GEMINI API] Received direct text response.")
            history.append(types.Content(role="model", parts=parts))
            text = "".join(
                str(getattr(part, "text", "") or "")
                for part in parts
                if not getattr(part, "thought", False)
            )
            if on_text is not None and streamed_pieces:
                text = "".join(streamed_pieces)
            return text if text.strip() else "I couldn't generate a text response."

        log_debug(f"[GEMINI API] Received {len(function_calls)} function call request(s).")
        history.append(types.Content(role="model", parts=parts))
        round_had_text = any(
            getattr(part, "text", None) and not getattr(part, "thought", False) for part in parts
        )
        if round_had_text:
            emit_text("\n\n")
        result_parts = []
        for tool_call in function_calls:
            arguments = dict(tool_call.args or {})
            result = execute_tool_call(tool_call.name, arguments)
            result_parts.append(
                types.Part.from_function_response(
                    name=tool_call.name,
                    response={"result": result},
                )
            )
            if tool_call.name == "take_screenshot" and result.get("status") == "SUCCESS":
                image_path = result.get("path")
                if image_path and os.path.exists(image_path):
                    try:
                        with open(image_path, "rb") as image_file:
                            image_bytes = image_file.read()
                        result_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
                        log_debug("[VISION SYSTEM] Attached screenshot to context.")
                    except Exception as error:
                        log_debug(f"[VISION ERROR] Failed to load screenshot: {error}")
        history.append(types.Content(role="user", parts=result_parts))
    raise RuntimeError("The assistant requested too many consecutive tool calls.")

class AssistantSession:
    def __init__(
        self,
        client: Any,
        model: str = DEFAULT_MODEL,
        personality: str = "",
        seed_messages: list[dict[str, str]] | None = None,
    ) -> None:
        from google.genai import types
        saved_memory = load_memory()
        memory_prompt = (
            f"\n\nCurrent Local Persistent Memory (%APPDATA%/GD Assistant/memory.json):\n{json.dumps(saved_memory, indent=2)}\n"
            "Use 'remember_info' to save new details, 'forget_info' to remove details, and 'get_all_memory' to inspect memory."
        )
        self.client = client
        self.model = model
        self.types = types
        self.config = types.GenerateContentConfig(
            system_instruction=get_system_instruction(personality) + memory_prompt,
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.history: list[Any] = [
            types.Content(
                role="model" if str(message.get("role")) == "assistant" else "user",
                parts=[types.Part(text=str(message.get("content", "")))],
            )
            for message in (seed_messages or [])
        ]

    def ask(self, message: str) -> str:
        self.history.append(self.types.Content(role="user", parts=[self.types.Part(text=message)]))
        return send_message_with_tools(self.client, self.model, self.config, self.history)

    def ask_stream(
        self,
        message: str,
        on_text: Callable[[str], None],
        stop_event: threading.Event | None = None,
        extra_parts: list[Any] | None = None,
    ) -> str:
        parts = [self.types.Part(text=message), *(extra_parts or [])]
        self.history.append(self.types.Content(role="user", parts=parts))
        return send_message_with_tools(
            self.client,
            self.model,
            self.config,
            self.history,
            on_text=on_text,
            stop_event=stop_event,
        )

def chat_loop(client: Any, model: str, personality: str = "") -> None:
    session = AssistantSession(client, model, personality)
    print(f"{APP_NAME} {APP_VERSION} Terminal initialized (Model: {model}). Type '/quit' to exit.\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            sys.exit(0)
        if not user_input:
            continue
        if user_input.lower() in ["/quit", "/exit", "exit", "quit"]:
            sys.exit(0)
        try:
            print(f"GD: {session.ask(user_input)}")
        except Exception as error:
            print(f"GD: Request failed ({type(error).__name__}): {friendly_error(error)}", file=sys.stderr)

def bring_to_foreground(hwnd: int) -> None:
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.ShowWindow(hwnd, 9)
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0043)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0043)

        foreground_hwnd = user32.GetForegroundWindow()
        if foreground_hwnd == hwnd: return

        current_thread_id = kernel32.GetCurrentThreadId()
        foreground_thread_id = user32.GetWindowThreadProcessId(foreground_hwnd, None)
        if foreground_thread_id and foreground_thread_id != current_thread_id:
            user32.AttachThreadInput(current_thread_id, foreground_thread_id, True)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)
        else:
            user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)
    except Exception as e:
        log_debug(f"[FOCUS ERROR] {e}")

def launch_chat_ui(
    client: Any,
    model: str = DEFAULT_MODEL,
    lang: str = "en",
    personality: str = "",
    theme: str = DEFAULT_THEME,
) -> None:
    global _active_root, _active_hwnd, _ui_mode
    try:
        import tkinter as tk
        from tkinter import messagebox
    except ImportError as error:
        raise RuntimeError("Tkinter is required.") from error

    service = get_qt_service()
    if service is None:
        # The chat UI lives in Qt now; without it a bare Tk window would be a
        # broken half-migration, so refuse to start instead of degrading.
        notice_root = tk.Tk()
        notice_root.withdraw()
        messagebox.showerror(APP_NAME, get_text("qt_required_msg", lang))
        notice_root.destroy()
        return

    session = AssistantSession(client, model, personality)
    voice_app: Any = None
    colors = get_theme(theme)

    def warm_voice_model() -> None:
        """Preload optional speech components without delaying the interface."""
        try:
            from gd_core.voice import preload_tts_voice, preload_voice_assistant

            # TTS warm-up is quick and network-bound; the Whisper model load
            # is heavier, so it runs right after on the same background worker.
            preload_tts_voice(debug=DEBUG_CONSOLE)
            preload_voice_assistant(debug=DEBUG_CONSOLE)
        except Exception as error:
            log_debug(f"[STT WARNING] Voice preload could not start: {error}")

    # Text Chat and Code Mode remain immediately available while this optional
    # worker imports Faster-Whisper and warms its local model in the background.
    threading.Thread(target=warm_voice_model, daemon=True, name="gd-voice-preload").start()

    root = tk.Tk()
    _active_root = root
    _ui_mode = "chat"
    root.title(f"{APP_NAME} {APP_VERSION}")
    root.minsize(680, 500)
    root.configure(padx=14, pady=14, bg=colors["background"])
    # Chat mode lives in the Qt window; the Tk root stays withdrawn and only
    # reappears when Code Mode packs its panel into it.
    root.withdraw()

    # The File/Mode menus stay tk.Menu objects as the source of truth for
    # labels/commands; they are rendered by the Qt popup (menu_descriptors +
    # invoke_menu_item) wherever the File/Mode buttons live.
    file_menu = tk.Menu(root, tearoff=0)
    mode_menu = tk.Menu(root, tearoff=0)

    hotkey_specs = (
        ("open", "hotkey_label", DEFAULT_HOTKEY),
        ("voice", "hotkey_voice_label", DEFAULT_VOICE_HOTKEY),
        ("code", "hotkey_code_label", DEFAULT_CODE_HOTKEY),
    )

    def apply_settings(values: dict[str, Any]) -> list[str]:
        """Apply a settings payload built by either settings UI (Tk or Qt).
        Returns the hotkey actions whose registration failed."""
        nonlocal model, session, code_panel, theme, personality
        new_hotkeys: dict[str, str] = {}
        for action, _label_key, default_value in hotkey_specs:
            key = "hotkey" if action == "open" else f"hotkey_{action}"
            new_hotkeys[action] = str(values.get(key) or "").strip() or default_value
        failed_actions = [
            action for action, keys in new_hotkeys.items()
            if not update_hotkey(action, keys)
        ]
        log_debug(
            "[SETTINGS] Saved. Hotkeys: "
            + ", ".join(f"{action}={keys}" for action, keys in new_hotkeys.items())
        )
        if failed_actions:
            log_debug(f"[SETTINGS] Hotkey registration failed for: {', '.join(failed_actions)}")
        save_api_key(str(values.get("api_key") or "").strip())
        new_chat_model = str(values.get("model") or "").strip() or DEFAULT_MODEL
        new_personality = str(values.get("personality") or "").strip()
        new_voice_device = values.get("voice_device")
        new_opacity = max(0.4, min(1.0, float(values.get("window_opacity", 0.93) or 0.93)))
        new_maximize_opaque = bool(values.get("maximize_opaque", True))
        save_app_config({
            "model": new_chat_model,
            "code_model": str(values.get("code_model") or "").strip() or DEFAULT_CODE_MODEL,
            "share_chat_code_model": bool(values.get("share_chat_code_model", True)),
            "theme": values.get("theme") or DEFAULT_THEME,
            "hotkey": new_hotkeys["open"],
            "hotkey_voice": new_hotkeys["voice"],
            "hotkey_code": new_hotkeys["code"],
            "voice_device": new_voice_device,
            "wake_word_enabled": bool(values.get("wake_word_enabled", False)),
            "wake_phrase": str(values.get("wake_phrase") or "").strip() or DEFAULT_WAKE_PHRASE,
            "voice_orb_enabled": bool(values.get("voice_orb_enabled", True)),
            "window_opacity": new_opacity,
            "maximize_opaque": new_maximize_opaque,
            "personality": new_personality,
            "language": values.get("language") or "en",
        })
        service.chat_op(
            "opacity",
            {"value": new_opacity, "maximize_opaque": new_maximize_opaque},
        )
        log_debug(
            f"[SETTINGS] Window opacity {new_opacity} "
            f"(opaque when maximized: {new_maximize_opaque})"
        )
        from gd_core.voice import set_voice_input_device

        set_voice_input_device(new_voice_device)
        apply_wake_settings()
        # Apply the selected chat model now; a Code panel is rebuilt using
        # the current share/separate-code-model choice on its next display.
        model = new_chat_model
        personality = new_personality
        session = AssistantSession(
            client, model, personality,
            seed_messages=(current_conv or {}).get("messages"),
        )
        theme = values.get("theme") or DEFAULT_THEME
        apply_chat_theme(theme)
        code_was_visible = code_panel is not None and bool(code_panel.winfo_manager())
        if code_panel is not None:
            code_panel.destroy()
            code_panel = None
        if code_was_visible:
            switch_to_code()
        return failed_actions

    def qt_settings_payload() -> dict[str, Any]:
        from gd_core.voice import get_input_devices

        cfg = load_app_config()
        mic_devices = list(get_input_devices())
        mic_position = 0
        for position, (device_index, _name) in enumerate(mic_devices, start=1):
            if device_index == cfg.get("voice_device"):
                mic_position = position
                break
        return {
            "api_key": get_api_key(),
            "models": list(COMMON_GEMINI_MODELS),
            "model": cfg.get("model", DEFAULT_MODEL),
            "code_model": cfg.get("code_model", DEFAULT_CODE_MODEL),
            "share_chat_code_model": bool(cfg.get("share_chat_code_model", True)),
            "hotkey": cfg.get("hotkey", DEFAULT_HOTKEY),
            "hotkey_voice": cfg.get("hotkey_voice", DEFAULT_VOICE_HOTKEY),
            "hotkey_code": cfg.get("hotkey_code", DEFAULT_CODE_HOTKEY),
            "mic_devices": mic_devices,
            "mic_position": mic_position,
            "wake_word_enabled": bool(cfg.get("wake_word_enabled", False)),
            "wake_phrase": cfg.get("wake_phrase", DEFAULT_WAKE_PHRASE),
            "voice_orb_enabled": bool(cfg.get("voice_orb_enabled", True)),
            "theme": cfg.get("theme", DEFAULT_THEME),
            "language": cfg.get("language", "en"),
            "window_opacity": cfg.get("window_opacity", 0.93),
            "maximize_opaque": bool(cfg.get("maximize_opaque", True)),
            "personality": cfg.get("personality", ""),
        }

    def finish_qt_settings(values: dict[str, Any]) -> None:
        # Runs on the Tk thread (scheduled by open_qt_settings via root.after).
        if not str(values.get("api_key") or "").strip():
            service.notice("Error", get_text("err_empty_key", lang), "error")
            return
        failed_actions = apply_settings(values)
        if failed_actions:
            service.notice(
                get_text("settings_success_title", lang),
                get_text("settings_hotkey_failed_msg", lang),
                "warning",
            )
        else:
            service.notice(
                get_text("settings_success_title", lang),
                get_text("settings_saved_msg", lang),
            )

    def open_qt_settings() -> bool:
        try:
            service.on_settings_saved(
                lambda values: root.after(0, lambda: finish_qt_settings(values))
            )
            service.open_settings(qt_settings_payload(), colors, lang)
            return True
        except Exception as error:
            log_debug(f"[QT] settings window failed: {error}")
            return False

    def open_settings_dialog() -> None:
        if not open_qt_settings():
            log_debug("[QT] settings unavailable")

    file_menu.add_command(label=get_text("menu_settings", lang), command=open_settings_dialog)
    file_menu.add_separator()
    file_menu.add_command(label=get_text("menu_exit", lang), command=lambda: os._exit(0))

    mode_bar = tk.Frame(root, bg=colors["panel"], padx=4, pady=3)
    mode_bar.pack(fill=tk.X, side=tk.TOP, pady=(0, 8))

    store = ConversationStore()
    current_conv: dict[str, Any] | None = None
    sidebar_archived = False

    def sidebar_rows() -> list[dict[str, Any]]:
        suffix = get_text("sidebar_archived_suffix", lang)
        rows: list[dict[str, Any]] = []
        for conv in store.list_conversations("chat", include_archived=sidebar_archived):
            title = str(conv.get("title") or "...")
            label = title + suffix if conv.get("status") == "archived" else title
            rows.append({"id": conv["id"], "label": label, "title": title})
        return rows

    def push_sidebar_rows() -> None:
        service.chat_op("rows", {
            "rows": sidebar_rows(),
            "current": current_conv["id"] if current_conv else None,
        })

    def persist_chat_message(conv: dict[str, Any] | None, role: str, content: str) -> None:
        if conv is None:
            return
        store.append_message(conv["id"], role, content)
        push_sidebar_rows()

    def apply_chat_conversation(conv: dict[str, Any]) -> None:
        nonlocal current_conv, session
        current_conv = conv
        session = AssistantSession(
            client, model, personality, seed_messages=conv.get("messages") or []
        )
        service.chat_op("clear")
        for message in conv.get("messages") or []:
            content = str(message.get("content", ""))
            if message.get("role") == "user":
                add_message("You", content)
            else:
                add_markdown_message("GD", content)
        push_sidebar_rows()

    def start_new_chat() -> None:
        conv = store.create_conversation("chat", title=get_text("sidebar_new_chat", lang))
        apply_chat_conversation(conv)

    def open_chat_conversation(conv_id: str | None) -> None:
        if conv_id is None:
            start_new_chat()
            return
        conv = store.load_conversation(conv_id)
        if conv is not None and conv.get("type") == "chat":
            apply_chat_conversation(conv)

    def convert_chat_to_code(conv_id: str, target_dir: str) -> None:
        # The confirm + folder pick ran in the Qt sidebar; this only mutates
        # the store and switches modes.
        conv = store.load_conversation(conv_id)
        if conv is None or conv.get("type") != "chat":
            return
        store.convert_to_code(conv_id, target_dir)
        if current_conv is not None and current_conv["id"] == conv_id:
            start_new_chat()
        else:
            push_sidebar_rows()
        switch_to_code(conv_id)

    menu_button_rects: dict[str, list[int]] = {}

    def show_dropdown(menu: Any, rects: dict[str, list[int]]) -> None:
        """Open the themed popup for a File/Mode menu. ``rects`` carries the
        live button rectangles (global coords) so a dismiss click swallowed by
        the popup's mouse grab can be replayed as a sibling menu open."""
        menu_button_rects.clear()
        menu_button_rects.update(dict(rects))
        try:
            service.on_menu_trigger(
                lambda index: root.after(0, lambda: invoke_menu_item(menu, index))
            )
            service.on_menu_closed(
                lambda point: root.after(0, lambda: handle_menu_dismiss(menu, point))
            )
            service.show_menu(menu_descriptors(menu), colors)
        except Exception as error:
            log_debug(f"[QT] menu failed: {error}")

    def tk_button_rect(button: Any) -> list[int]:
        return [
            button.winfo_rootx(), button.winfo_rooty(),
            button.winfo_width(), button.winfo_height(),
        ]

    def tk_menu_rects() -> dict[str, list[int]]:
        return {"file": tk_button_rect(file_button), "mode": tk_button_rect(mode_button)}

    file_button = tk.Button(
        mode_bar,
        text=get_text("menu_file", lang),
        command=lambda: show_dropdown(file_menu, tk_menu_rects()),
        relief=tk.FLAT,
        bg=colors["panel"],
        fg=colors["foreground"],
        activebackground=colors["button_active"],
        activeforeground=colors["foreground"],
        padx=10,
    )
    file_button.pack(side=tk.LEFT)
    mode_button = tk.Button(
        mode_bar,
        text=get_text("menu_mode", lang),
        command=lambda: show_dropdown(mode_menu, tk_menu_rects()),
        relief=tk.FLAT,
        bg=colors["panel"],
        fg=colors["foreground"],
        activebackground=colors["button_active"],
        activeforeground=colors["foreground"],
        padx=10,
    )
    mode_button.pack(side=tk.LEFT)

    def handle_menu_dismiss(menu: Any, point: Any) -> None:
        """Replay a dismiss click the Qt popup's mouse grab swallowed: if the
        user hit the sibling File/Mode button, open that menu right away so
        switching menus stays one click (Esc and item picks arrive as None)."""
        if point is None:
            return
        sibling_kind = "mode" if menu is file_menu else "file"
        rect = menu_button_rects.get(sibling_kind)
        if not rect:
            return
        x, y = point
        if rect[0] <= x < rect[0] + rect[2] and rect[1] <= y < rect[1] + rect[3]:
            show_dropdown(mode_menu if menu is file_menu else file_menu, menu_button_rects)

    def capture_root_hwnd() -> None:
        """Lazily resolve the Tk root's top-level hwnd for bring_to_foreground.
        Only Code Mode needs it, and by then the root is actually mapped."""
        global _active_hwnd
        if _active_hwnd is not None:
            return
        try:
            root.update_idletasks()
            hwnd = root.winfo_id()
            _active_hwnd = ctypes.windll.user32.GetParent(hwnd) or hwnd
        except Exception as error:
            log_debug(f"[HWND] capture failed: {error}")

    root.protocol("WM_DELETE_WINDOW", root.withdraw)

    pending_files: list[Path] = []

    def push_attachments() -> None:
        service.chat_op("attachments", {"paths": [str(path) for path in pending_files]})

    def queue_attachments(paths: list[Any]) -> None:
        added = 0
        for item in paths:
            path = Path(str(item))
            if path not in pending_files:
                pending_files.append(path)
                added += 1
        if added:
            log_debug(f"[ATTACH] Queued {added} file(s) for the next message")
        push_attachments()

    def remove_attachment(index: int) -> None:
        if 0 <= index < len(pending_files):
            pending_files.pop(index)
        push_attachments()

    def clear_attachments() -> None:
        pending_files.clear()
        push_attachments()

    class _StatusProxy:
        """StringVar stand-in: routes status text into the Qt chat window."""

        def set(self, text: str) -> None:
            service.chat_op("status", {"text": text})

    status = _StatusProxy()
    inputs_enabled = True

    def add_message(speaker: str, text: str) -> None:
        service.chat_op("append", {"speaker": speaker, "text": text, "markdown": False})

    def add_markdown_message(speaker: str, text: str) -> None:
        service.chat_op("append", {"speaker": speaker, "text": text, "markdown": True})

    def set_inputs_enabled(enabled: bool) -> None:
        nonlocal inputs_enabled
        inputs_enabled = enabled
        service.chat_op("inputs", {"enabled": enabled})

    def set_mic_label(text: str) -> None:
        service.chat_op("mic_text", {"text": text})

    stream_pieces: list[str] = []
    stream_render_job: str | None = None

    def begin_stream_block() -> None:
        service.chat_op("stream_begin")

    def render_stream_text() -> None:
        nonlocal stream_render_job
        stream_render_job = None
        service.chat_op("stream_replace", {"text": "".join(stream_pieces)})

    def schedule_stream_render() -> None:
        nonlocal stream_render_job
        if stream_render_job is None:
            stream_render_job = root.after(50, render_stream_text)

    active_stop_event: threading.Event | None = None

    def set_send_stop_mode(stop_mode: bool) -> None:
        service.chat_op("send_mode", {"stop": stop_mode})

    def stop_current_request() -> None:
        if active_stop_event is not None:
            active_stop_event.set()
        status.set(get_text("status_stopping", lang))

    def apply_chat_theme(theme_name: str) -> None:
        """Apply the selected shared appearance to the Qt chat window and to
        the Tk widgets that remain (the Code Mode host and its menu bar)."""
        nonlocal colors
        colors = get_theme(theme_name)
        root.configure(bg=colors["background"])
        mode_bar.configure(bg=colors["panel"])
        for button in (file_button, mode_button):
            button.configure(
                bg=colors["panel"],
                fg=colors["foreground"],
                activebackground=colors["button_active"],
                activeforeground=colors["foreground"],
            )
        service.chat_op("palette", {"palette": colors})

    def perform_text_request(
        message: str,
        request_session: AssistantSession,
        request_conv: dict[str, Any] | None,
        stop_event: threading.Event,
        binary_paths: list[Path] | None = None,
    ) -> None:
        nonlocal active_stop_event
        request_failed = False
        streamed = False

        def on_chunk(chunk: str) -> None:
            nonlocal streamed
            streamed = True
            stream_pieces.append(chunk)
            root.after(0, schedule_stream_render)

        try:
            extra_parts = load_binary_parts(binary_paths, debug=DEBUG_CONSOLE) if binary_paths else None
            reply = request_session.ask_stream(message, on_chunk, stop_event, extra_parts=extra_parts)
        except Exception as error:
            request_failed = True
            reply = get_text("request_failed", lang).format(error=friendly_error(error))

        def finish():
            nonlocal active_stop_event
            active_stop_event = None
            if stream_render_job is not None:
                root.after_cancel(stream_render_job)
            if request_failed:
                if streamed:
                    service.chat_op("stream_replace", {"text": "".join(stream_pieces)})
                service.chat_op("stream_finish", {
                    "text": reply, "markdown": False, "append": bool(streamed),
                })
            elif streamed:
                service.chat_op("stream_finish", {
                    "text": "".join(stream_pieces), "markdown": True,
                })
            else:
                service.chat_op("stream_finish", {"text": reply, "markdown": True})
            if not request_failed and reply:
                persist_chat_message(request_conv, "assistant", reply)
            set_send_stop_mode(False)
            status.set(get_text("status_ready", lang))
            set_inputs_enabled(True)
            service.chat_op("focus_input")
        root.after(0, finish)

    def submit_message(text: str) -> None:
        nonlocal active_stop_event
        message = str(text or "").strip()
        if not message and not pending_files: return
        if message and message.lower() in {"/quit", "/exit"}:
            root.destroy()
            os._exit(0)
        service.chat_op("clear_input")
        files = list(pending_files)
        clear_attachments()
        if files:
            summary = display_summary(files)
            add_message("You", f"{message}\n{summary}" if message else summary)
        else:
            add_message("You", message)
        request_text, binary_paths = prepare_message(message, files, debug=DEBUG_CONSOLE)
        persist_chat_message(current_conv, "user", request_text)
        stream_pieces.clear()
        stop_event = threading.Event()
        active_stop_event = stop_event
        status.set(get_text("status_thinking", lang))
        set_inputs_enabled(False)
        begin_stream_block()
        set_send_stop_mode(True)
        threading.Thread(
            target=perform_text_request,
            args=(f"[TEXT] {request_text}", session, current_conv, stop_event, binary_paths),
            daemon=True,
        ).start()

    def perform_voice_request() -> None:
        nonlocal voice_app
        request_session = session
        request_conv = current_conv
        orb = get_qt_service() if load_app_config().get("voice_orb_enabled", True) else None
        wire_orb_expand(orb)
        try:
            if wake_listener is not None:
                wake_listener.pause()
            if voice_app is None:
                root.after(0, lambda: status.set(get_text("status_loading_voice", lang)))
                from gd_core.voice import get_voice_assistant

                voice_app = get_voice_assistant(debug=DEBUG_CONSOLE, device=load_app_config().get("voice_device"))

            root.after(0, lambda: [status.set(get_text("status_listening", lang)), set_mic_label(get_text("status_listening", lang))])
            if orb is not None:
                orb.show_state("listening")
            user_text = voice_app.listen_dynamic(
                on_level=(orb.set_level if orb is not None else None)
            )
            if not user_text:
                def finish_empty():
                    add_message("GD", get_text("voice_no_speech", lang))
                    status.set(get_text("status_ready", lang))
                    set_mic_label(get_text("btn_voice", lang))
                    set_inputs_enabled(True)
                if orb is not None:
                    orb.hide()
                root.after(0, finish_empty)
                return

            if orb is not None:
                orb.show_state("thinking")
            root.after(0, lambda: [add_message("You (Voice)", user_text), persist_chat_message(request_conv, "user", user_text), status.set(get_text("status_thinking", lang)), set_mic_label(get_text("status_thinking", lang))])
            reply = strip_markdown(request_session.ask(f"[VOICE] {user_text}"))

            if orb is not None:
                orb.show_state("result", reply)
            root.after(0, lambda: [add_message("GD", reply), persist_chat_message(request_conv, "assistant", reply), status.set(get_text("status_speaking", lang)), set_mic_label(get_text("status_speaking", lang))])
            voice_app.speak(reply)
            if orb is not None:
                orb.hide_after_turn()
        except Exception as error:
            if orb is not None:
                orb.hide()
            root.after(0, lambda: add_message("GD", get_text("voice_request_failed", lang).format(error=friendly_error(error))))
        finally:
            def restore_ui():
                status.set(get_text("status_ready", lang))
                set_mic_label(get_text("btn_voice", lang))
                set_inputs_enabled(True)
                if wake_listener is not None:
                    wake_listener.resume()
                service.chat_op("focus_input")
            root.after(0, restore_ui)

    def start_voice_listening() -> None:
        set_inputs_enabled(False)
        threading.Thread(target=perform_voice_request, daemon=True).start()

    # Chat and Code intentionally share one Tk root. Switching modes never
    # starts a second GD Assistant process, so the single-instance guard stays
    # meaningful and both modes can use the same configured API client.
    code_panel: Any | None = None

    wake_listener = None

    def handle_wake() -> None:
        # Wake word drives Chat Mode only; Code Mode sessions ignore it.
        if code_panel is not None and code_panel.winfo_manager():
            return
        if not inputs_enabled:
            return
        service.chat_op("show")
        start_voice_listening()

    def apply_wake_settings() -> None:
        nonlocal wake_listener
        if wake_listener is not None:
            wake_listener.stop()
            wake_listener = None
        wake_cfg = load_app_config()
        if not wake_cfg.get("wake_word_enabled"):
            log_debug("[WAKE] Wake word disabled in settings")
            return
        log_debug(f"[WAKE] Starting wake listener with phrase '{wake_cfg.get('wake_phrase') or DEFAULT_WAKE_PHRASE}'")
        from gd_core.wakeword import WakeWordListener

        wake_listener = WakeWordListener(
            phrase=wake_cfg.get("wake_phrase") or DEFAULT_WAKE_PHRASE,
            device=wake_cfg.get("voice_device"),
            debug=DEBUG_CONSOLE,
            on_wake=lambda: root.after(0, handle_wake),
        )
        wake_listener.start()

    apply_wake_settings()

    def switch_to_chat() -> None:
        global _ui_mode
        _ui_mode = "chat"
        if code_panel is not None:
            code_panel.pack_forget()
        root.withdraw()
        service.chat_op("show")
        service.chat_op("focus_input")

    def switch_to_code(conversation_id: str | None = None) -> None:
        global _ui_mode
        nonlocal code_panel
        _ui_mode = "code"
        service.chat_op("hide")
        if code_panel is None:
            from ui_tk.code_gui import CodeAgentPanel

            current_config = load_app_config()
            code_model = get_code_model(current_config, model)
            code_panel = CodeAgentPanel(
                root,
                client,
                model=code_model,
                start_dir=os.getcwd(),
                theme=theme,
                debug=DEBUG_CONSOLE,
                lang=lang,
                conversation_id=conversation_id,
            )
        elif conversation_id:
            code_panel.load_conversation(conversation_id)
        root.deiconify()
        capture_root_hwnd()
        code_panel.pack(fill=tk.BOTH, expand=True)
        root.title(f"{APP_NAME} {APP_VERSION} — {get_text('mode_code', lang)}")
        root.after(50, lambda: bring_to_foreground(_active_hwnd) if _active_hwnd else None)

    # Voice and Code shortcuts only mean something while this window exists,
    # so they join the global "open" hotkey here rather than in main().
    def hotkey_voice_action() -> None:
        log_debug("[HOTKEY] Voice hotkey fired")
        # keyboard delivers callbacks on its own hook thread.
        root.after(0, handle_wake)

    def hotkey_code_action() -> None:
        def toggle() -> None:
            if code_panel is not None and code_panel.winfo_manager():
                log_debug("[HOTKEY] Code hotkey -> switching to Chat")
                switch_to_chat()
            else:
                log_debug("[HOTKEY] Code hotkey -> switching to Code")
                switch_to_code()
        root.after(0, toggle)

    ui_cfg = load_app_config()
    register_hotkey("voice", ui_cfg.get("hotkey_voice", DEFAULT_VOICE_HOTKEY), hotkey_voice_action)
    register_hotkey("code", ui_cfg.get("hotkey_code", DEFAULT_CODE_HOTKEY), hotkey_code_action)

    def open_terminal_code() -> None:
        """Close this instance before its terminal Code mode begins."""
        import subprocess

        source_path = str(Path(__file__).resolve())
        code_model = get_code_model(load_app_config(), model)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        if getattr(sys, "frozen", False):
            # The delay gives this process time to release its Windows mutex.
            command = (
                f'ping 127.0.0.1 -n 2 >nul & start "GD Assistant Code" '
                f'cmd.exe /k "\"{sys.executable}\" --code --model \"{code_model}\""'
            )
            subprocess.Popen(["cmd.exe", "/c", command], creationflags=creation_flags)
        else:
            launcher = (
                "import subprocess, sys, time; "
                "time.sleep(1); "
                "subprocess.call(sys.argv[1:], "
                "creationflags=getattr(subprocess, 'CREATE_NEW_CONSOLE', 0))"
            )
            subprocess.Popen(
                [sys.executable, "-c", launcher, sys.executable, source_path, "--code", "--model", code_model],
                creationflags=creation_flags,
            )

        root.destroy()
        os._exit(0)

    mode_menu.add_command(label=get_text("mode_chat", lang), command=switch_to_chat)
    mode_menu.add_command(label=get_text("mode_code", lang), command=switch_to_code)
    mode_menu.add_separator()
    mode_menu.add_command(label=get_text("mode_open_code_terminal", lang), command=open_terminal_code)

    def handle_chat_event(op: str, payload: Any) -> None:
        """Dispatch a gesture from the Qt chat window (always on the Tk thread)."""
        nonlocal sidebar_archived
        if op == "send":
            submit_message(str(payload or ""))
        elif op == "stop":
            stop_current_request()
        elif op == "mic":
            start_voice_listening()
        elif op == "attach_files":
            queue_attachments(list(payload or []))
        elif op == "remove_attachment":
            remove_attachment(int(payload))
        elif op == "clear_attachments":
            clear_attachments()
        elif op == "menu":
            data = payload or {}
            kind = str(data.get("kind") or "file")
            show_dropdown(file_menu if kind == "file" else mode_menu, data.get("rects") or {})
        elif op == "close":
            log_debug("[CHAT] Window hidden; app stays alive in the tray")
        elif op == "sidebar_open":
            open_chat_conversation(payload)
        elif op == "sidebar_new":
            start_new_chat()
        elif op == "sidebar_rename":
            conv_id, title = payload
            store.rename_conversation(str(conv_id), str(title))
            push_sidebar_rows()
        elif op == "sidebar_status":
            conv_id, status_value = payload
            store.set_status(str(conv_id), str(status_value))
            if status_value == "archived" and current_conv is not None and current_conv.get("id") == conv_id:
                open_chat_conversation(None)
            else:
                push_sidebar_rows()
        elif op == "sidebar_delete":
            conv_id = str(payload)
            store.delete_conversation(conv_id)
            if current_conv is not None and current_conv.get("id") == conv_id:
                open_chat_conversation(None)
            else:
                push_sidebar_rows()
        elif op == "sidebar_convert":
            conv_id, target_dir = payload
            convert_chat_to_code(str(conv_id), str(target_dir))
        elif op == "sidebar_archived":
            sidebar_archived = bool(payload)
            push_sidebar_rows()
        else:
            log_debug(f"[CHAT] Unknown op: {op}")

    service.on_chat_event(
        lambda op, payload: root.after(0, lambda: handle_chat_event(op, payload))
    )
    window_cfg = load_app_config()
    # Create the window (hidden) before any content ops: the service drops
    # every op until "open" has built it. Content first, then show + focus.
    service.open_chat_window({
        "palette": colors,
        "lang": lang,
        "title": f"{APP_NAME} {APP_VERSION}",
        "header": get_text("mode_chat", lang),
        "opacity": float(window_cfg.get("window_opacity") or 0.93),
        "maximize_opaque": bool(window_cfg.get("maximize_opaque", True)),
    })
    recent_chats = store.list_conversations("chat")
    if recent_chats:
        apply_chat_conversation(recent_chats[0])
    else:
        start_new_chat()
        add_message("GD", f"{get_text('welcome_msg', lang)} (Model: {model})")
    service.chat_op("show")
    service.chat_op("focus_input")
    root.mainloop()

def friendly_error(error: Exception) -> str:
    message = str(error).lower()
    if "api key" in message or "unauth" in message or "permission" in message:
        return "check that GEMINI_API_KEY is valid and has Gemini API access."
    if "rate" in message or "resource exhausted" in message or "429" in message:
        return "rate limit reached; wait a moment and try again."
    if "servererror" in type(error).__name__.lower() or any(status in message for status in ("500", "502", "503", "504")):
        return "Gemini is temporarily unavailable. Wait a few seconds, then retry your message."
    if "network" in message or "connection" in message or "timeout" in message:
        return "network error; check your connection and try again."
    return "Gemini could not complete that request. Please try again."

def cleanup_temp_files() -> None:
    app_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "GD Assistant")
    screenshot_path = os.path.join(app_dir, "current_screen.png")
    if os.path.exists(screenshot_path):
        try: os.remove(screenshot_path)
        except: pass
    audio_files = glob.glob(os.path.join(app_dir, "*.mp3")) + glob.glob(os.path.join(app_dir, "*.wav"))
    for file_path in audio_files:
        try: os.remove(file_path)
        except: pass

atexit.register(cleanup_temp_files)

def main() -> int:
    global DEBUG_CONSOLE

    app_config = load_app_config()
    lang = app_config.get("language", "en")

    if not check_single_instance():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("GD Assistant", get_text("already_running", lang))
            root.destroy()
        except Exception:
            pass
        return 0

    parser = argparse.ArgumentParser(description="GD Assistant")
    parser.add_argument(
        "--debug",
        action="store_true",
        dest="debug",
        help="show system and Coding Agent round/tool diagnostics in the launching console",
    )
    parser.add_argument("--terminal", action="store_true", help="use the original terminal-only chat interface")
    parser.add_argument("--voice", action="store_true", help="start in terminal voice-only mode")
    parser.add_argument("--firstboot", action="store_true", help="force the first-time setup wizard to run")
    parser.add_argument("--code", action="store_true", help="start in Claude Code-style interactive programming mode")
    parser.add_argument("--workspace", type=str, default=".", help="initial workspace folder for code mode")
    parser.add_argument("--gui", action="store_true", help="launch graphical interface (can be combined with --code)")
    parser.add_argument("--codegui", action="store_true", help="direct shortcut to launch Coding Agent GUI")
    parser.add_argument("--model", type=str, default=None, help="override the Gemini model name")
    arguments = parser.parse_args()

    DEBUG_CONSOLE = bool(arguments.debug)

    if DEBUG_CONSOLE:
        print(f"\n===============================================================\n DEBUG CONSOLE MODE FOR {APP_NAME.upper()}\n {APP_VERSION}\n===============================================================\n", flush=True)
    elif not arguments.terminal and not arguments.code:
        hide_console_window()

    api_key = get_api_key()
    model = app_config.get("model", DEFAULT_MODEL)
    theme = app_config.get("theme", DEFAULT_THEME)
    hotkey = app_config.get("hotkey", DEFAULT_HOTKEY)
    personality = app_config.get("personality", DEFAULT_PERSONALITY)

    if not api_key or arguments.firstboot:
        # Qt wizard is the primary path; the legacy Tk steps remain only as
        # the fallback when the Qt layer is unavailable (migration rule).
        wizard_data: dict | None = None
        qt_wizard_ok = False
        try:
            wizard_service = get_qt_service()
            if wizard_service is not None:
                from gd_core.voice import get_input_devices

                wizard_data = wizard_service.run_wizard({
                    "language": lang,
                    "theme": theme,
                    "model": model,
                    "code_model": app_config.get("code_model", DEFAULT_CODE_MODEL),
                    "share_chat_code_model": app_config.get("share_chat_code_model", True),
                    "hotkey": hotkey,
                    "models": list(COMMON_GEMINI_MODELS),
                    "mic_devices": list(get_input_devices()),
                    "voice_device": app_config.get("voice_device"),
                    "personality": personality,
                    "window_opacity": app_config.get("window_opacity", 0.93),
                })
                qt_wizard_ok = True
        except Exception as error:
            log_debug(f"[QT] wizard failed: {error}")

        if not qt_wizard_ok:
            lang_res = run_setup_wizard_lang()
            if not lang_res: return 2
            lang = lang_res

            theme_res = run_setup_wizard_theme(lang)
            if theme_res is None: return 2
            theme = theme_res

            step1_res = run_setup_wizard_step1(lang, theme)
            if not step1_res: return 2
            api_key, model, code_model, share_models = step1_res
            save_api_key(api_key)

            step2_res = run_setup_wizard_step2(lang, theme)
            if not step2_res: return 2
            hotkey, voice_device = step2_res

            pers_res = run_setup_wizard_step3(lang, theme)
            if pers_res is None: return 2
            personality = pers_res
            wizard_data = {
                "language": lang, "theme": theme, "window_opacity": 0.93,
                "api_key": api_key, "model": model, "code_model": code_model,
                "share_chat_code_model": share_models, "hotkey": hotkey,
                "voice_device": voice_device, "personality": personality,
            }
        elif wizard_data is None:
            return 2

        lang = wizard_data["language"]
        theme = wizard_data["theme"]
        api_key = wizard_data["api_key"]
        model = wizard_data["model"]
        hotkey = wizard_data["hotkey"]
        personality = wizard_data["personality"]
        save_api_key(api_key)

        save_app_config({
            "model": model,
            "code_model": wizard_data["code_model"],
            "share_chat_code_model": wizard_data["share_chat_code_model"],
            "theme": theme,
            "voice_device": wizard_data["voice_device"],
            "hotkey": hotkey,
            "language": lang,
            "window_opacity": wizard_data.get("window_opacity", 0.93),
            "personality": personality
        })

    try:
        client = load_client(api_key)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 2

    if arguments.code or arguments.codegui:
        active_code_model = arguments.model or get_code_model(app_config, model)

        if arguments.gui or arguments.codegui:
            from ui_tk.code_gui import launch_coding_gui
            launch_coding_gui(
                client,
                model=active_code_model,
                start_dir=arguments.workspace,
                theme=theme,
                debug=DEBUG_CONSOLE,
                lang=lang,
            )
            return 0
        else:
            from code_cli import launch_coding_cli
            launch_coding_cli(
                client,
                model=active_code_model,
                start_dir=arguments.workspace,
                debug=DEBUG_CONSOLE,
                lang=lang,
            )
            return 0

    if arguments.terminal:
        chat_loop(client, model, personality)
    elif arguments.voice:
        from gd_core.voice import VoiceAssistant
        voice_app = VoiceAssistant(debug=DEBUG_CONSOLE)
        voice_app.run_voice_loop(AssistantSession(client, model, personality))
    else:
        def open_gui_safely():
            log_debug("[HOTKEY] Open hotkey fired")
            global _active_root, _active_hwnd
            service = get_qt_service()
            if service is not None:
                if service.chat_raise():
                    return
                if _ui_mode != "code":
                    service.chat_op("show")
                    return
                if _active_hwnd:
                    bring_to_foreground(_active_hwnd)
                    return
            if _active_root is not None:
                try:
                    _active_root.deiconify()
                    if _active_hwnd:
                        bring_to_foreground(_active_hwnd)
                    return
                except Exception:
                    pass
            threading.Thread(
                target=lambda: launch_chat_ui(client, model, lang, personality, theme),
                daemon=True,
            ).start()

        tray_daemon = TrayDaemon(
            on_open_chat=open_gui_safely,
            on_quit=lambda: os._exit(0),
            app_name=APP_NAME,
            app_version=APP_VERSION,
        )
        threading.Thread(target=tray_daemon.run_tray, daemon=True).start()

        register_hotkey("open", hotkey, open_gui_safely)

        launch_chat_ui(client, model, lang, personality, theme)
    return 0

if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        # Ctrl+C / IDE Stop: hard-exit like the tray Quit. Normal teardown
        # fires the native hotkey/tray callbacks mid-finalization -> 0xC000041D.
        cleanup_temp_files()
        os._exit(0)
