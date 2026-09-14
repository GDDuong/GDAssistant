"""GD Assistant: a local Windows chat assistant with a safe tool allowlist."""

from __future__ import annotations

import argparse
import atexit
import ctypes
import glob
import json
import multiprocessing
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

from history_manager import HistoryManager
from config_manager import (
    load_app_config,
    save_app_config,
    get_api_key,
    save_api_key,
    DEFAULT_MODEL,
    DEFAULT_HOTKEY,
)
from translations import get_text, TRANSLATIONS

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
    search_and_read_webpage,
    read_clipboard,
    write_clipboard,
    read_local_file,
)
from tray import TrayDaemon

APP_NAME = "GD Assistant"
APP_VERSION = "v0.2-BETA"
_active_root = None
_active_hwnd = None
_mutex_handle = None

IMMUTABLE_GUARDRAILS = """
### CORE GUARDRAILS & RULES (NON-NEGOTIABLE)
1. **Truthfulness in Actions**: Never claim to have performed a computer or desktop action (like opening an app, clicking, or typing) unless a tool result explicitly confirms success.
2. **Mandatory Tool Use**: Always leverage your tools to fetch live web data, read files, or check clipboard contents rather than guessing.
3. **Voice-Optimized Output**: Avoid heavy Markdown formatting (like tables or massive code blocks) to ensure smooth text-to-speech reading.
"""

MAX_TOOL_ROUNDS = 12
DEBUG_CONSOLE = False

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "open_app",
        "description": "Opens one approved Windows app.",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string", "description": "The requested app name."}},
            "required": ["app_name"],
        },
    },
    {
        "name": "close_app",
        "description": "Closes one running approved Windows app.",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string", "description": "The app to close."}},
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
            "properties": {"query": {"type": "string", "description": "Text to search for."}},
            "required": ["query"],
        },
    },
    {
        "name": "open_url",
        "description": "Opens an http or https URL in the user's default browser.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "An absolute http:// or https:// URL."}},
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
                "key": {"type": "string", "description": "Short topic name."},
                "value": {"type": "string", "description": "The information to remember."},
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "forget_info",
        "description": "Deletes a specific key from local memory when requested.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string", "description": "The memory key to delete."}},
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
            "properties": {"file_path": {"type": "string", "description": "The absolute path to open."}},
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
        "description": "Clicks mouse at normalized target coordinates (0 to 1000).",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string"},
                "clicks": {"type": "integer"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "type_text",
        "description": "Simulates typing text directly into active focus.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "press_key",
        "description": "Presses an individual key or shortcut combination.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "scroll_screen",
        "description": "Scrolls primary display vertically.",
        "parameters": {
            "type": "object",
            "properties": {"amount": {"type": "integer"}},
            "required": ["amount"],
        },
    },
    {
        "name": "search_and_read_webpage",
        "description": "Search the web and read top matching URL content.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "read_clipboard",
        "description": "Read text stored in clipboard.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "write_clipboard",
        "description": "Copy text to system clipboard.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "read_local_file",
        "description": "Read content of a specified local file.",
        "parameters": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
]

TOOL_REGISTRY: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "open_app": lambda args: open_app(args.get("app_name")),
    "close_app": lambda args: (
        close_app(args.get("app_name"))
        if confirm_action(f"Close application '{args.get('app_name')}'?")
        else {"status": "FAILURE", "message": "User blocked action."}
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
        else {"status": "FAILURE", "message": "User blocked action."}
    ),
    "scroll_screen": lambda args: scroll_screen(int(args.get("amount", 0))),
    "search_and_read_webpage": lambda args: search_and_read_webpage(str(args.get("query", ""))),
    "read_clipboard": lambda _args: read_clipboard(),
    "write_clipboard": lambda args: write_clipboard(str(args.get("text", ""))),
    "read_local_file": lambda args: read_local_file(str(args.get("file_path", ""))),
}

def build_system_instruction() -> str:
    """Combine immutable guardrails, user-configured personality, and local persistent memory."""
    config = load_app_config()
    custom_personality = config.get("personality", "").strip()
    saved_memory = load_memory()
    memory_prompt = (
        f"\n\nCurrent Local Persistent Memory:\n{json.dumps(saved_memory, indent=2)}\n"
        "Use 'remember_info' to save new details, 'forget_info' to remove details, and 'get_all_memory' to inspect memory."
    )
    personality_section = f"\n\n### USER-DEFINED PERSONALITY & TONE\n{custom_personality}" if custom_personality else ""
    return f"{IMMUTABLE_GUARDRAILS}{personality_section}\n{memory_prompt}"

def check_single_instance() -> bool:
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.windll.kernel32
    mutex_name = "Global\\GDAssistant_SingleInstance_Mutex"
    global _mutex_handle
    _mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)
    return kernel32.GetLastError() != 183

def hide_console_window() -> None:
    if sys.platform == "win32":
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)

def log_debug(message: str) -> None:
    if DEBUG_CONSOLE:
        print(message, flush=True)

# ----------------- WIZARD STEPS ----------------- #

def run_setup_wizard_lang() -> str:
    """Wizard Pre-Step: Choose language (English / Tiếng Việt)."""
    import tkinter as tk

    selected_lang = {"lang": "en"}
    root = tk.Tk()
    t = TRANSLATIONS["en"]
    root.title(t["wizard_lang_title"])
    root.geometry("440x210")
    root.resizable(False, False)
    root.configure(padx=20, pady=20)

    tk.Label(root, text=t["wizard_lang_heading"], font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=t["wizard_lang_sub"], font=("Arial", 9)).pack(anchor="w", pady=(0, 20))

    frame = tk.Frame(root)
    frame.pack(fill="x", pady=10)

    def choose(lang: str):
        selected_lang["lang"] = lang
        root.destroy()

    btn_en = tk.Button(frame, text="English 🇺🇸", font=("Arial", 10, "bold"), width=16, height=2, command=lambda: choose("en"))
    btn_en.pack(side="left", padx=(10, 20))

    btn_vi = tk.Button(frame, text="Tiếng Việt 🇻🇳", font=("Arial", 10, "bold"), width=16, height=2, command=lambda: choose("vi"))
    btn_vi.pack(side="left")

    root.mainloop()
    return selected_lang["lang"]

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

def run_setup_wizard_step2(lang: str) -> str:
    """Wizard Step 2: Configure keybinds."""
    import tkinter as tk

    hotkey_holder = {"hotkey": DEFAULT_HOTKEY}
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

    def on_save():
        val = hotkey_entry.get().strip()
        if not val or val == DEFAULT_HOTKEY:
            val = DEFAULT_HOTKEY
        hotkey_holder["hotkey"] = val
        root.destroy()

    btn = tk.Button(root, text=get_text("btn_next", lang), command=on_save, bg="#0078D7", fg="white", width=16)
    btn.pack(anchor="e")

    root.mainloop()
    return hotkey_holder["hotkey"]

def run_setup_wizard_step3(lang: str) -> str:
    """Wizard Step 3: Configure custom AI behavior/personality (starts blank)."""
    import tkinter as tk

    personality_holder = {"personality": ""}
    root = tk.Tk()
    root.title(get_text("wizard_step3_title", lang))
    root.geometry("460x250")
    root.resizable(False, False)
    root.configure(padx=20, pady=20)

    tk.Label(root, text=get_text("wizard_step3_heading", lang), font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 5))
    tk.Label(root, text=get_text("wizard_step3_sub", lang), font=("Arial", 9), justify="left").pack(anchor="w", pady=(0, 15))

    tk.Label(root, text=get_text("personality_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
    personality_entry = tk.Entry(root, width=52)
    personality_entry.pack(anchor="w", pady=(5, 20))
    personality_entry.focus_set()

    def on_save():
        personality_holder["personality"] = personality_entry.get().strip()
        root.destroy()

    btn = tk.Button(root, text=get_text("btn_finish", lang), command=on_save, bg="#0078D7", fg="white", width=16)
    btn.pack(anchor="e")

    root.mainloop()
    return personality_holder["personality"]

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
    return result

def send_message_with_tools(client: Any, model: str, config: Any, history: list[Any]) -> str:
    from google.genai import types

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        response = client.models.generate_content(model=model, contents=history, config=config)
        function_calls = getattr(response, "function_calls", None) or []

        if not function_calls:
            history.append(response.candidates[0].content)
            return get_response_text(response)

        history.append(response.candidates[0].content)
        result_parts = []
        for tool_call in function_calls:
            arguments = dict(tool_call.args or {})
            result = execute_tool_call(tool_call.name, arguments)
            result_parts.append(
                types.Part.from_function_response(name=tool_call.name, response={"result": result})
            )
            if tool_call.name == "take_screenshot" and result.get("status") == "SUCCESS":
                image_path = result.get("path")
                if image_path and os.path.exists(image_path):
                    with open(image_path, "rb") as image_file:
                        result_parts.append(types.Part.from_bytes(data=image_file.read(), mime_type="image/png"))

        history.append(types.Content(role="user", parts=result_parts))

    raise RuntimeError("The assistant requested too many consecutive tool calls.")

class AssistantSession:
    def __init__(self, client: Any, model: str = DEFAULT_MODEL) -> None:
        from google.genai import types
        self.client = client
        self.model = model
        self.types = types
        self.history_manager = HistoryManager()
        self.config = types.GenerateContentConfig(
            system_instruction=build_system_instruction(),
            tools=[types.Tool(function_declarations=TOOL_DECLARATIONS)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        self.history: list[Any] = []

    def ask(self, message: str) -> str:
        self.history.append(self.types.Content(role="user", parts=[self.types.Part(text=message)]))
        response_text = send_message_with_tools(self.client, self.model, self.config, self.history)
        try:
            serialized_history = [
                {"role": item.role, "parts": [p.text for p in item.parts if hasattr(p, "text") and p.text]}
                for item in self.history if hasattr(item, "role")
            ]
            self.history_manager.save_session(serialized_history)
        except Exception as e:
            log_debug(f"[HISTORY ERROR] {e}")
        return response_text

def bring_to_foreground(hwnd: int) -> None:
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
    except Exception as e:
        log_debug(f"[FOCUS ERROR] {e}")

def launch_chat_ui(client: Any, model: str = DEFAULT_MODEL) -> None:
    global _active_root, _active_hwnd
    import tkinter as tk
    from tkinter import scrolledtext, messagebox

    app_cfg = load_app_config()
    lang = app_cfg.get("language", "en")

    session = AssistantSession(client, model)

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
        settings_win.geometry("460x460")
        settings_win.resizable(False, False)
        settings_win.configure(padx=20, pady=20)
        settings_win.transient(root)
        settings_win.grab_set()

        tk.Label(settings_win, text=get_text("settings_title", lang), font=("Arial", 14, "bold")).pack(anchor="w", pady=(0, 10))

        current_key = get_api_key()
        cfg = load_app_config()

        tk.Label(settings_win, text=get_text("language_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        lang_var = tk.StringVar(value=cfg.get("language", "en"))
        lang_menu = tk.OptionMenu(settings_win, lang_var, "en", "vi")
        lang_menu.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("api_key_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        key_entry = tk.Entry(settings_win, width=52, show="*")
        key_entry.insert(0, current_key)
        key_entry.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("model_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        model_entry = tk.Entry(settings_win, width=52)
        model_entry.insert(0, cfg.get("model", DEFAULT_MODEL))
        model_entry.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("hotkey_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        hotkey_entry = tk.Entry(settings_win, width=52)
        hotkey_entry.insert(0, cfg.get("hotkey", DEFAULT_HOTKEY))
        hotkey_entry.pack(anchor="w", pady=(3, 10))

        tk.Label(settings_win, text=get_text("personality_label", lang), font=("Arial", 9, "bold")).pack(anchor="w")
        personality_entry = tk.Entry(settings_win, width=52)
        personality_entry.insert(0, cfg.get("personality", ""))
        personality_entry.pack(anchor="w", pady=(3, 15))

        def save_settings():
            new_key = key_entry.get().strip()
            new_model = model_entry.get().strip() or DEFAULT_MODEL
            new_hotkey = hotkey_entry.get().strip() or DEFAULT_HOTKEY
            new_personality = personality_entry.get().strip()
            new_lang = lang_var.get()

            if not new_key:
                messagebox.showerror("Error", get_text("err_empty_key", lang), parent=settings_win)
                return

            save_api_key(new_key)
            save_app_config({
                "language": new_lang,
                "model": new_model,
                "hotkey": new_hotkey,
                "personality": new_personality,
            })

            session.config.system_instruction = build_system_instruction()
            messagebox.showinfo("Success", get_text("settings_saved_msg", lang), parent=settings_win)
            settings_win.destroy()

        save_btn = tk.Button(settings_win, text=get_text("btn_save", lang), command=save_settings, bg="#0078D7", fg="white", width=16)
        save_btn.pack(anchor="e")

    file_menu.add_command(label=get_text("menu_settings", lang), command=open_settings_dialog)
    file_menu.add_separator()
    file_menu.add_command(label=get_text("menu_exit", lang), command=lambda: os._exit(0))
    menubar.add_cascade(label=get_text("menu_file", lang), menu=file_menu)
    root.config(menu=menubar)

    root.update_idletasks()
    hwnd = root.winfo_id()
    _active_hwnd = ctypes.windll.user32.GetParent(hwnd) or hwnd

    root.protocol("WM_DELETE_WINDOW", lambda: root.withdraw())
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
    tk.Label(root, textvariable=status, anchor="w").grid(
        row=2, column=0, columnspan=3, sticky="ew", pady=(6, 0)
    )
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
            reply = f"Error: {error}"

        def finish() -> None:
            add_message("GD", reply)
            status.set(get_text("status_ready", lang))
            set_inputs_enabled(True)
            message_box.focus_set()

        root.after(0, finish)

    def submit_message(_event: Any = None) -> None:
        message = message_box.get().strip()
        if not message:
            return
        message_box.delete(0, tk.END)
        add_message("You", message)
        status.set(get_text("status_thinking", lang))
        set_inputs_enabled(False)
        threading.Thread(target=perform_text_request, args=(message,), daemon=True).start()

    send_button.configure(command=submit_message)
    message_box.bind("<Return>", submit_message)

    add_message("GD", get_text("welcome_msg", lang))
    message_box.focus_set()
    root.mainloop()

def cleanup_temp_files() -> None:
    app_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "GD Assistant")
    for pattern in ["current_screen.png", "*.mp3", "*.wav"]:
        for file_path in glob.glob(os.path.join(app_dir, pattern)):
            try:
                os.remove(file_path)
            except Exception:
                pass

atexit.register(cleanup_temp_files)

def main() -> int:
    global DEBUG_CONSOLE
    if not check_single_instance():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning("GD Assistant", TRANSLATIONS["en"]["already_running"])
            root.destroy()
        except Exception:
            pass
        return 0

    parser = argparse.ArgumentParser(description="GD Assistant")
    parser.add_argument("--console", action="store_true", dest="console")
    parser.add_argument("--firstboot", action="store_true")
    arguments = parser.parse_args()

    DEBUG_CONSOLE = bool(arguments.console)
    if not arguments.console:
        hide_console_window()

    api_key = get_api_key()
    app_config = load_app_config()
    lang = app_config.get("language", "en")
    model = app_config.get("model", DEFAULT_MODEL)
    hotkey = app_config.get("hotkey", DEFAULT_HOTKEY)

    if not api_key or arguments.firstboot:
        lang = run_setup_wizard_lang()
        step1_res = run_setup_wizard_step1(lang)
        if not step1_res:
            return 2
        api_key, model = step1_res
        save_api_key(api_key)

        hotkey = run_setup_wizard_step2(lang)
        personality = run_setup_wizard_step3(lang)

        save_app_config({
            "language": lang,
            "model": model,
            "hotkey": hotkey,
            "personality": personality,
        })

    try:
        client = load_client(api_key)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 2

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
        threading.Thread(target=lambda: launch_chat_ui(client, model), daemon=True).start()

    tray_daemon = TrayDaemon(on_open_chat=open_gui_safely, on_quit=lambda: os._exit(0))
    threading.Thread(target=tray_daemon.run_tray, daemon=True).start()

    try:
        import keyboard
        keyboard.add_hotkey(hotkey, open_gui_safely)
    except Exception:
        pass

    launch_chat_ui(client, model)
    return 0

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())