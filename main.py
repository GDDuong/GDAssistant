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

from tray import TrayDaemon
from translations import get_text

from local_tools import (
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
)

APP_NAME = "GD Assistant"
APP_VERSION = "v0.2-BETA"
_active_root = None
_active_hwnd = None
_mutex_handle = None

DEFAULT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_HOTKEY = "ctrl+alt+g"
DEFAULT_LANGUAGE = "en"
DEFAULT_PERSONALITY = ""

def get_system_instruction(personality: str) -> str:
    base = (
        "You are GD Assistant, a helpful personal Windows desktop assistant. "
        "You may use your approved local tools when requested: open_app, close_app, "
        "get_system_stats, search_files, open_url, get_current_time, remember_info, "
        "forget_info, get_all_memory, open_file, take_screenshot, click_at, type_text, "
        "press_key, and scroll_screen. "
        "Never claim to have performed a computer action unless the tool result confirms it. "
        "The local tool result is authoritative: if its status is SUCCESS, say the action succeeded; "
        "if FAILURE, report that it failed. "
        "When identifying click targets from screenshots, always output coordinates "
        "using a normalized 0 to 1000 integer scale (where x=0, y=0 is top-left and x=1000, y=1000 is bottom-right). "
        "Keep responses concise, conversational, and under 2-3 sentences when possible. "
        "Do not use markdown formatting like bullet points, bolding, or code blocks so responses "
        "sound natural when spoken."
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
        "hotkey": DEFAULT_HOTKEY,
        "language": DEFAULT_LANGUAGE,
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

def run_setup_wizard_lang() -> str | None:
    """Wizard Step 0: Language Selection."""
    import tkinter as tk
    result = {"lang": None, "success": False}

    root = tk.Tk()
    root.title(get_text("wizard_lang_title", "en"))
    root.geometry("400x200")
    root.resizable(False, False)
    root.configure(padx=20, pady=20)

    tk.Label(root, text=get_text("wizard_lang_heading", "en"), font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_lang_sub", "en"), font=("Arial", 9)).pack(anchor="w", pady=(0, 15))

    def on_select(lang_code):
        result["lang"] = lang_code
        result["success"] = True
        root.destroy()

    tk.Button(root, text="English", command=lambda: on_select("en"), bg="#0078D7", fg="white", width=20).pack(pady=5)
    tk.Button(root, text="Tiếng Việt", command=lambda: on_select("vi"), bg="#0078D7", fg="white", width=20).pack(pady=5)

    root.mainloop()
    return result["lang"] if result["success"] else None

def run_setup_wizard_step1(lang: str) -> tuple[str, str] | None:
    """Wizard Step 1: Input API key and model."""
    import tkinter as tk
    from tkinter import messagebox
    result = {"key": "", "model": DEFAULT_MODEL, "success": False}

    root = tk.Tk()
    root.title(get_text("wizard_step1_title", lang))
    root.geometry("460x310")
    root.resizable(False, False)
    root.configure(padx=20, pady=20)

    tk.Label(root, text=get_text("wizard_step1_heading", lang), font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_step1_sub", lang), font=("Arial", 9)).pack(anchor="w", pady=(0, 10))

    tk.Label(root, text=get_text("api_key_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
    entry_box = tk.Entry(root, width=52, show="*")
    entry_box.pack(anchor="w", pady=(3, 10))
    entry_box.focus_set()

    tk.Label(root, text=get_text("model_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
    model_entry = tk.Entry(root, width=52, fg="gray")
    model_entry.insert(0, DEFAULT_MODEL)
    model_entry.pack(anchor="w", pady=(3, 15))

    def on_focus_in(event):
        if model_entry.get() == DEFAULT_MODEL:
            model_entry.delete(0, tk.END)
            model_entry.config(fg="black")

    def on_focus_out(event):
        if not model_entry.get().strip():
            model_entry.insert(0, DEFAULT_MODEL)
            model_entry.config(fg="gray")

    model_entry.bind("<FocusIn>", on_focus_in)
    model_entry.bind("<FocusOut>", on_focus_out)

    def on_confirm():
        entered_key = entry_box.get().strip()
        if not entered_key:
            messagebox.showerror("Error", get_text("err_empty_key", lang), parent=root)
            return
        entered_model = model_entry.get().strip()
        if not entered_model or entered_model == DEFAULT_MODEL:
            entered_model = DEFAULT_MODEL
        result["key"] = entered_key
        result["model"] = entered_model
        result["success"] = True
        root.destroy()

    btn = tk.Button(root, text=get_text("btn_next", lang), command=on_confirm, bg="#0078D7", fg="white", width=16)
    btn.pack(anchor="e")
    root.mainloop()
    return (result["key"], result["model"]) if result["success"] else None

def run_setup_wizard_step2(lang: str) -> str | None:
    """Wizard Step 2: Configure keybinds."""
    import tkinter as tk
    hotkey_holder = {"hotkey": DEFAULT_HOTKEY, "success": False}

    root = tk.Tk()
    root.title(get_text("wizard_step2_title", lang))
    root.geometry("460x220")
    root.resizable(False, False)
    root.configure(padx=20, pady=20)

    tk.Label(root, text=get_text("wizard_step2_heading", lang), font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_step2_sub", lang), font=("Arial", 9)).pack(anchor="w", pady=(0, 15))

    tk.Label(root, text=get_text("hotkey_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
    hotkey_entry = tk.Entry(root, width=52, fg="gray")
    hotkey_entry.insert(0, DEFAULT_HOTKEY)
    hotkey_entry.pack(anchor="w", pady=(5, 20))
    hotkey_entry.focus_set()

    def on_focus_in(event):
        if hotkey_entry.get() == DEFAULT_HOTKEY:
            hotkey_entry.delete(0, tk.END)
            hotkey_entry.config(fg="black")

    def on_focus_out(event):
        if not hotkey_entry.get().strip():
            hotkey_entry.insert(0, DEFAULT_HOTKEY)
            hotkey_entry.config(fg="gray")

    hotkey_entry.bind("<FocusIn>", on_focus_in)
    hotkey_entry.bind("<FocusOut>", on_focus_out)

    def on_save():
        val = hotkey_entry.get().strip()
        if not val or val == DEFAULT_HOTKEY:
            val = DEFAULT_HOTKEY
        hotkey_holder["hotkey"] = val
        hotkey_holder["success"] = True
        root.destroy()

    btn = tk.Button(root, text=get_text("btn_next", lang), command=on_save, bg="#0078D7", fg="white", width=16)
    btn.pack(anchor="e")
    root.mainloop()
    return hotkey_holder["hotkey"] if hotkey_holder["success"] else None

def run_setup_wizard_step3(lang: str) -> str | None:
    """Wizard Step 3: Configure Custom Personality."""
    import tkinter as tk
    result = {"personality": "", "success": False}

    root = tk.Tk()
    root.title(get_text("wizard_step3_title", lang))
    root.geometry("460x320")
    root.resizable(False, False)
    root.configure(padx=20, pady=20)

    tk.Label(root, text=get_text("wizard_step3_heading", lang), font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_step3_sub", lang), font=("Arial", 9), justify="left").pack(anchor="w", pady=(0, 15))

    tk.Label(root, text=get_text("personality_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
    pers_text = tk.Text(root, height=5, width=52)
    pers_text.pack(anchor="w", pady=(3, 15))
    pers_text.focus_set()

    def on_finish():
        result["personality"] = pers_text.get("1.0", tk.END).strip()
        result["success"] = True
        root.destroy()

    btn = tk.Button(root, text=get_text("btn_finish", lang), command=on_finish, bg="#0078D7", fg="white", width=16)
    btn.pack(anchor="e")
    root.mainloop()
    return result["personality"] if result["success"] else None

def load_client(api_key: str) -> Any:
    try:
        from google import genai
    except ImportError as error:
        raise RuntimeError("Missing dependency. Run: python -m pip install -r requirements.txt") from error
    return genai.Client(api_key=api_key)

def get_response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    return text.strip() if text and text.strip() else "I couldn't generate a text response."

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

def send_message_with_tools(client: Any, model: str, config: Any, history: list[Any]) -> str:
    from google.genai import types
    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        log_debug(f"[GEMINI API] Sending prompt turn to model ({model}) [Round {round_num}]...")
        response = client.models.generate_content(model=model, contents=history, config=config)
        function_calls = getattr(response, "function_calls", None) or []

        if not function_calls:
            log_debug("[GEMINI API] Received direct text response.")
            history.append(response.candidates[0].content)
            return get_response_text(response)

        log_debug(f"[GEMINI API] Received {len(function_calls)} function call request(s).")
        history.append(response.candidates[0].content)
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
    def __init__(self, client: Any, model: str = DEFAULT_MODEL, personality: str = "") -> None:
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
        self.history: list[Any] = []

    def ask(self, message: str) -> str:
        self.history.append(self.types.Content(role="user", parts=[self.types.Part(text=message)]))
        return send_message_with_tools(self.client, self.model, self.config, self.history)

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

def launch_chat_ui(client: Any, model: str = DEFAULT_MODEL, lang: str = "en", personality: str = "") -> None:
    global _active_root, _active_hwnd
    try:
        import tkinter as tk
        from tkinter import scrolledtext, messagebox
    except ImportError as error:
        raise RuntimeError("Tkinter is required.") from error

    session = AssistantSession(client, model, personality)
    voice_app: Any = None

    root = tk.Tk()
    _active_root = root
    root.title(f"{APP_NAME} {APP_VERSION}")
    root.minsize(680, 500)
    root.configure(padx=14, pady=14)

    menubar = tk.Menu(root)
    file_menu = tk.Menu(menubar, tearoff=0)

    def open_settings_dialog():
        settings_win = tk.Toplevel(root)
        settings_win.title(get_text("settings_title", lang))
        settings_win.geometry("500x520")
        settings_win.resizable(False, False)
        settings_win.configure(padx=20, pady=20)
        settings_win.transient(root)
        settings_win.grab_set()

        tk.Label(settings_win, text=get_text("settings_title", lang), font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 10))
        current_key = get_api_key()
        app_cfg = load_app_config()

        tk.Label(settings_win, text=get_text("api_key_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        key_entry = tk.Entry(settings_win, width=60, show="*")
        key_entry.insert(0, current_key)
        key_entry.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("model_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        model_entry = tk.Entry(settings_win, width=60)
        model_entry.insert(0, app_cfg.get("model", DEFAULT_MODEL))
        model_entry.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("hotkey_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        hotkey_entry = tk.Entry(settings_win, width=60)
        hotkey_entry.insert(0, app_cfg.get("hotkey", DEFAULT_HOTKEY))
        hotkey_entry.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("personality_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        pers_text = tk.Text(settings_win, height=4, width=45)
        pers_text.insert("1.0", app_cfg.get("personality", ""))
        pers_text.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("language_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        lang_var = tk.StringVar(value=app_cfg.get("language", "en"))
        tk.Radiobutton(settings_win, text="English", variable=lang_var, value="en").pack(anchor="w")
        tk.Radiobutton(settings_win, text="Tiếng Việt", variable=lang_var, value="vi").pack(anchor="w")

        def save_settings():
            new_key = key_entry.get().strip()
            if not new_key:
                messagebox.showerror("Error", get_text("err_empty_key", lang), parent=settings_win)
                return
            save_api_key(new_key)
            save_app_config({
                "model": model_entry.get().strip() or DEFAULT_MODEL,
                "hotkey": hotkey_entry.get().strip() or DEFAULT_HOTKEY,
                "personality": pers_text.get("1.0", tk.END).strip(),
                "language": lang_var.get()
            })
            messagebox.showinfo("Success", get_text("settings_saved_msg", lang), parent=settings_win)
            settings_win.destroy()

        tk.Button(settings_win, text=get_text("btn_save", lang), command=save_settings, bg="#0078D7", fg="white", width=20).pack(anchor="e", pady=10)

    file_menu.add_command(label=get_text("menu_settings", lang), command=open_settings_dialog)
    file_menu.add_separator()
    file_menu.add_command(label=get_text("menu_exit", lang), command=lambda: os._exit(0))
    menubar.add_cascade(label=get_text("menu_file", lang), menu=file_menu)
    root.config(menu=menubar)

    root.update_idletasks()
    hwnd = root.winfo_id()
    _active_hwnd = ctypes.windll.user32.GetParent(hwnd) or hwnd
    root.protocol("WM_DELETE_WINDOW", root.withdraw)
    root.after(100, lambda: bring_to_foreground(_active_hwnd))

    transcript = scrolledtext.ScrolledText(root, wrap=tk.WORD, state=tk.DISABLED)
    transcript.grid(row=0, column=0, columnspan=3, sticky="nsew")

    message_box = tk.Entry(root)
    message_box.grid(row=1, column=0, sticky="ew", pady=(12, 0))

    send_button = tk.Button(root, text=get_text("btn_send", lang))
    send_button.grid(row=1, column=1, sticky="e", padx=(8, 0), pady=(12, 0))

    mic_button = tk.Button(root, text=get_text("btn_voice", lang), width=12)
    mic_button.grid(row=1, column=2, sticky="e", padx=(6, 0), pady=(12, 0))

    status = tk.StringVar(value=get_text("status_ready", lang))
    tk.Label(root, textvariable=status, anchor="w").grid(row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0))

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    def add_message(speaker: str, text: str) -> None:
        transcript.configure(state=tk.NORMAL)
        transcript.insert(tk.END, f"{speaker}: {text}\n\n")
        transcript.configure(state=tk.DISABLED)
        transcript.see(tk.END)

    def set_inputs_enabled(enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        message_box.configure(state=state)
        send_button.configure(state=state)
        mic_button.configure(state=state)

    def perform_text_request(message: str) -> None:
        try:
            reply = session.ask(message)
        except Exception as error:
            reply = f"Request failed: {friendly_error(error)}"
        def finish():
            add_message("GD", reply)
            status.set(get_text("status_ready", lang))
            set_inputs_enabled(True)
            message_box.focus_set()
        root.after(0, finish)

    def submit_message(_event: Any = None) -> None:
        message = message_box.get().strip()
        if not message: return
        if message.lower() in {"/quit", "/exit"}:
            root.destroy()
            os._exit(0)
        message_box.delete(0, tk.END)
        add_message("You", message)
        status.set(get_text("status_thinking", lang))
        set_inputs_enabled(False)
        threading.Thread(target=perform_text_request, args=(message,), daemon=True).start()

    def perform_voice_request() -> None:
        nonlocal voice_app
        try:
            if voice_app is None:
                root.after(0, lambda: status.set("Loading speech model..."))
                from voice import VoiceAssistant
                voice_app = VoiceAssistant(debug=DEBUG_CONSOLE)

            root.after(0, lambda: [status.set(get_text("status_listening", lang)), mic_button.configure(text=get_text("status_listening", lang))])
            user_text = voice_app.listen_dynamic()
            if not user_text:
                def finish_empty():
                    add_message("GD", "I didn't hear anything.")
                    status.set(get_text("status_ready", lang))
                    mic_button.configure(text=get_text("btn_voice", lang))
                    set_inputs_enabled(True)
                root.after(0, finish_empty)
                return

            root.after(0, lambda: [add_message("You (Voice)", user_text), status.set(get_text("status_thinking", lang)), mic_button.configure(text=get_text("status_thinking", lang))])
            reply = session.ask(user_text)

            root.after(0, lambda: [add_message("GD", reply), status.set(get_text("status_speaking", lang)), mic_button.configure(text=get_text("status_speaking", lang))])
            voice_app.speak(reply)
        except Exception as error:
            root.after(0, lambda: add_message("GD", f"Voice request failed: {friendly_error(error)}"))
        finally:
            def restore_ui():
                status.set(get_text("status_ready", lang))
                mic_button.configure(text=get_text("btn_voice", lang))
                set_inputs_enabled(True)
                message_box.focus_set()
            root.after(0, restore_ui)

    def start_voice_listening() -> None:
        set_inputs_enabled(False)
        threading.Thread(target=perform_voice_request, daemon=True).start()

    send_button.configure(command=submit_message)
    mic_button.configure(command=start_voice_listening)
    message_box.bind("<Return>", submit_message)

    add_message("GD", f"{get_text('welcome_msg', lang)} (Model: {model})")
    message_box.focus_set()
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
    parser.add_argument("--console", action="store_true", dest="console", help="show system debug, tool, STT, and TTS logs in the launching console")
    parser.add_argument("--terminal", action="store_true", help="use the original terminal-only chat interface")
    parser.add_argument("--voice", action="store_true", help="start in terminal voice-only mode")
    parser.add_argument("--firstboot", action="store_true", help="force the first-time setup wizard to run")
    arguments = parser.parse_args()

    DEBUG_CONSOLE = bool(arguments.console)

    if DEBUG_CONSOLE:
        print(f"\n===============================================================\n DEBUG CONSOLE MODE FOR {APP_NAME.upper()}\n {APP_VERSION}\n===============================================================\n", flush=True)
    elif not arguments.terminal:
        hide_console_window()

    api_key = get_api_key()
    model = app_config.get("model", DEFAULT_MODEL)
    hotkey = app_config.get("hotkey", DEFAULT_HOTKEY)
    personality = app_config.get("personality", DEFAULT_PERSONALITY)

    if not api_key or arguments.firstboot:
        lang_res = run_setup_wizard_lang()
        if not lang_res: return 2
        lang = lang_res

        step1_res = run_setup_wizard_step1(lang)
        if not step1_res: return 2
        api_key, model = step1_res
        save_api_key(api_key)

        hotkey_res = run_setup_wizard_step2(lang)
        if not hotkey_res: return 2
        hotkey = hotkey_res

        pers_res = run_setup_wizard_step3(lang)
        if pers_res is None: return 2
        personality = pers_res

        save_app_config({"model": model, "hotkey": hotkey, "language": lang, "personality": personality})

    try:
        client = load_client(api_key)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 2

    if arguments.terminal:
        chat_loop(client, model, personality)
    elif arguments.voice:
        from voice import VoiceAssistant
        voice_app = VoiceAssistant(debug=DEBUG_CONSOLE)
        voice_app.run_voice_loop(AssistantSession(client, model, personality))
    else:
        def open_gui_safely():
            global _active_root, _active_hwnd
            if _active_root is not None:
                try:
                    _active_root.deiconify()
                    if _active_hwnd:
                        bring_to_foreground(_active_hwnd)
                    return
                except Exception:
                    pass
            threading.Thread(target=lambda: launch_chat_ui(client, model, lang, personality), daemon=True).start()

        tray_daemon = TrayDaemon(on_open_chat=open_gui_safely, on_quit=lambda: os._exit(0))
        threading.Thread(target=tray_daemon.run_tray, daemon=True).start()

        try:
            import keyboard
            keyboard.add_hotkey(hotkey, open_gui_safely)
        except Exception as e:
            print(f"[NOTICE] Failed to register hotkey '{hotkey}': {e}")

        launch_chat_ui(client, model, lang, personality)
    return 0

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())