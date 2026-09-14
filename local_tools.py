"""Explicit, local-only tools available to GD Assistant.

Every tool in this module must validate its own input. Gemini may suggest a tool
call, but it never receives unrestricted command execution on this computer.
Every tool returns a ToolResult whose ``status`` reflects whether the *local
action itself* succeeded — a clean "no results" from search_files is still
SUCCESS, because the search ran correctly.
"""

from __future__ import annotations

import time
import os
import subprocess
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import TypedDict
import json
import os
from pathlib import Path
from typing import Any
from PIL import ImageGrab
import pyautogui
import psutil
from PIL import Image, ImageDraw, ImageFont

# Every key is a user-friendly name. Values are fixed executables, never
# model-provided paths, arguments, or commands.
SAFE_APPS = {
    "notepad": ("Notepad", "notepad.exe"),
    "calculator": ("Calculator", "calc.exe"),
    "paint": ("Paint", "mspaint.exe"),
    "file explorer": ("File Explorer", "explorer.exe"),
    "snipping tool": ("Snipping Tool", "SnippingTool.exe"),
    "task manager": ("Task Manager", "taskmgr.exe"),
    "control panel": ("Control Panel", "control.exe"),
    "character map": ("Character Map", "charmap.exe"),
    "magnifier": ("Magnifier", "magnify.exe"),
    "on-screen keyboard": ("On-Screen Keyboard", "osk.exe"),
}

# Only these two URL schemes may be handed to the OS browser launcher.
ALLOWED_URL_SCHEMES = {"http", "https"}

# search_files stays inside the user's home folder and never walks these.
EXCLUDED_DIR_NAMES = {
    ".git",
    "__pycache__",
    "node_modules",
    "$Recycle.Bin",
    "System Volume Information",
    "AppData",
}
MAX_SEARCH_RESULTS = 20
MAX_SEARCH_SECONDS = 8.0

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.5

BLOCKED_HOTKEYS = {"ctrl+alt+del", "win+l", "alt+f4"}

SENSITIVE_APPS = {"cmd", "powershell", "taskmgr", "regedit"}

class ToolResult(TypedDict):
    """The local execution outcome sent to Gemini after a tool call."""

    status: str
    message: str


def _resolve_app(app_name: object) -> tuple[str, str] | None:
    """Look up an allowlisted app by its user-friendly name, case/space-insensitive."""
    if not isinstance(app_name, str):
        return None
    normalized_name = " ".join(app_name.casefold().split())
    return SAFE_APPS.get(normalized_name)


def _not_approved_result(_app_name: object) -> ToolResult:
    allowed_names = ", ".join(item[0] for item in SAFE_APPS.values())
    return {
        "status": "FAILURE",
        "message": f"That app is not approved. For now I can only open: {allowed_names}.",
    }


def _format_bytes(num_bytes: float) -> str:
    """Render a byte count as a short human-readable size, e.g. '3.2 GB'."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


import subprocess

def open_app(app_name: str) -> dict[str, str]:
    """Launch an approved Windows app or a custom executable path saved in memory."""
    if not app_name:
        return {"status": "FAILURE", "message": "App name cannot be empty."}

    clean_name = app_name.strip().lower()

    # 1. Check local memory for a custom path (e.g. key: "geometry_dash_path")
    memory = load_memory()
    path_key = f"{clean_name.replace(' ', '_')}_path"

    if path_key in memory and os.path.exists(memory[path_key]):
        try:
            subprocess.Popen([memory[path_key]])
            return {
                "status": "SUCCESS",
                "message": f"Opened custom app '{app_name}' from path: {memory[path_key]}",
            }
        except Exception as error:
            return {
                "status": "FAILURE",
                "message": f"Failed to launch custom path for '{app_name}': {error}",
            }

    # 2. Approved Windows Built-ins
    APPROVED_APPS = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
        "cmd": "cmd.exe",
        "explorer": "explorer.exe",
        "paint": "mspaint.exe",
    }

    executable = APPROVED_APPS.get(clean_name)
    if not executable:
        return {
            "status": "FAILURE",
            "message": f"App '{app_name}' is not in approved list. Save its location first using: 'Remember {clean_name}_path is C:\\path\\to\\app.exe'.",
        }

    try:
        subprocess.Popen([executable])
        return {"status": "SUCCESS", "message": f"Opened '{app_name}' successfully."}
    except Exception as error:
        return {"status": "FAILURE", "message": f"Failed to launch '{app_name}': {error}"}


def close_app(app_name: object) -> ToolResult:
    """Close one running app from the same allowlist used by open_app.

    Args:
        app_name: The name of one app in the explicit local allowlist.

    Returns:
        An authoritative SUCCESS or FAILURE status and a user-safe message.
    """
    app = _resolve_app(app_name)
    if app is None:
        return _not_approved_result(app_name)

    display_name, executable = app
    try:
        # /IM matches by fixed image name, never a model-provided path.
        # /F forces the close; taskkill exits non-zero if it wasn't running.
        completed = subprocess.run(
            ["taskkill", "/IM", executable, "/F"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "status": "FAILURE",
            "message": f"I couldn't close {display_name} on this PC.",
        }

    if completed.returncode == 0:
        return {"status": "SUCCESS", "message": f"Closed {display_name}."}
    return {
        "status": "FAILURE",
        "message": f"{display_name} does not appear to be running.",
    }


def get_system_stats() -> ToolResult:
    """Report current CPU, memory, and disk usage for the user's PC.

    Returns:
        An authoritative SUCCESS or FAILURE status and a user-safe message.
    """
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or "/"))
    except (OSError, psutil.Error):
        return {"status": "FAILURE", "message": "I couldn't read system stats right now."}

    message = (
        f"CPU: {cpu_percent:.0f}% used. "
        f"Memory: {memory.percent:.0f}% used "
        f"({_format_bytes(memory.used)} of {_format_bytes(memory.total)}). "
        f"Disk: {disk.percent:.0f}% used "
        f"({_format_bytes(disk.used)} of {_format_bytes(disk.total)})."
    )
    return {"status": "SUCCESS", "message": message}


def search_files(query: object) -> ToolResult:
    """Search file names within the user's home folder for a text query.

    Args:
        query: A non-empty search term matched as a case-insensitive substring
            against file names.

    Returns:
        An authoritative SUCCESS or FAILURE status. SUCCESS covers a clean
        zero-result search; FAILURE means the search itself could not run.
    """
    if not isinstance(query, str) or not query.strip():
        return {"status": "FAILURE", "message": "A search term is required."}

    needle = query.strip().casefold()
    root = Path.home()
    matches: list[str] = []
    deadline = time.monotonic() + MAX_SEARCH_SECONDS
    timed_out = False

    try:
        for current_dir, dir_names, file_names in os.walk(root):
            dir_names[:] = [
                name
                for name in dir_names
                if name not in EXCLUDED_DIR_NAMES and not name.startswith(".")
            ]
            for file_name in file_names:
                if needle in file_name.casefold():
                    matches.append(str(Path(current_dir) / file_name))
                    if len(matches) >= MAX_SEARCH_RESULTS:
                        break
            if len(matches) >= MAX_SEARCH_RESULTS:
                break
            if time.monotonic() >= deadline:
                timed_out = True
                break
    except OSError:
        return {"status": "FAILURE", "message": "I couldn't search your files right now."}

    if not matches:
        note = " (search timed out before finishing)" if timed_out else ""
        return {
            "status": "SUCCESS",
            "message": f"No files matching '{query.strip()}' were found in your user folder{note}.",
        }

    listing = "\n".join(matches)
    suffix = " (showing the first matches; search timed out)" if timed_out else ""
    return {
        "status": "SUCCESS",
        "message": f"Found {len(matches)} match(es){suffix}:\n{listing}",
    }


def open_url(url: object) -> ToolResult:
    """Open an http or https URL in the user's default browser.

    Args:
        url: An absolute URL beginning with http:// or https://. Other
            schemes (file://, javascript:, etc.) are rejected before anything
            is launched.

    Returns:
        An authoritative SUCCESS or FAILURE status and a user-safe message.
    """
    if not isinstance(url, str) or not url.strip():
        return {"status": "FAILURE", "message": "A URL is required."}

    candidate = url.strip()
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        return {
            "status": "FAILURE",
            "message": "Only http:// or https:// URLs are allowed, for example 'https://example.com'.",
        }

    try:
        opened = webbrowser.open(candidate)
    except OSError:
        opened = False

    if not opened:
        return {"status": "FAILURE", "message": "I couldn't open that URL in your browser."}
    return {"status": "SUCCESS", "message": f"Opened {candidate} in your browser."}


def get_current_time() -> ToolResult:
    """Return the current local date and time.

    Returns:
        A SUCCESS status with a friendly formatted timestamp.
    """
    now = datetime.now().strftime("%A, %B %d, %Y at %I:%M %p")
    return {"status": "SUCCESS", "message": f"It's currently {now}."}

def get_memory_file_path() -> Path:
    """Return path to memory.json inside %APPDATA%/GD Assistant/."""
    appdata = os.getenv("APPDATA")
    if appdata:
        base_dir = Path(appdata) / "GD Assistant"
    else:
        base_dir = Path.home() / ".gd_assistant"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / "memory.json"


def load_memory() -> dict[str, Any]:
    """Read saved memory dictionary from disk."""
    path = get_memory_file_path()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return {}
    return {}


def save_memory(data: dict[str, Any]) -> None:
    """Write memory dictionary to disk."""
    path = get_memory_file_path()
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def remember_info(key: str, value: str) -> dict[str, str]:
    """Store or update a persistent key-value pair in local memory."""
    if not key or not value:
        return {"status": "FAILURE", "message": "Key and value must both be non-empty strings."}
    memory = load_memory()
    memory[key.strip().lower()] = value.strip()
    save_memory(memory)
    return {"status": "SUCCESS", "message": f"Saved to local memory: '{key}' = '{value}'."}


def forget_info(key: str) -> dict[str, str]:
    """Remove a key from local memory."""
    if not key:
        return {"status": "FAILURE", "message": "Key must be provided."}
    memory = load_memory()
    clean_key = key.strip().lower()
    if clean_key in memory:
        del memory[clean_key]
        save_memory(memory)
        return {"status": "SUCCESS", "message": f"Removed '{key}' from local memory."}
    return {"status": "FAILURE", "message": f"Key '{key}' was not found in local memory."}


def get_all_memory() -> dict[str, Any]:
    """Return all stored local memory."""
    memory = load_memory()
    return {
        "status": "SUCCESS",
        "message": f"Retrieved {len(memory)} stored item(s).",
        "data": memory,
    }

def open_file(file_path: str) -> dict[str, str]:
    """Opens a local file or folder using its default Windows application association."""
    if not file_path:
        return {"status": "FAILURE", "message": "File path cannot be empty."}

    clean_path = os.path.abspath(file_path.strip().strip('"'))
    if not os.path.exists(clean_path):
        return {"status": "FAILURE", "message": f"File or path does not exist: {clean_path}"}

    try:
        os.startfile(clean_path)
        return {"status": "SUCCESS", "message": f"Opened '{clean_path}' using default application."}
    except Exception as error:
        return {"status": "FAILURE", "message": f"Failed to open '{clean_path}': {error}"}

def take_screenshot() -> dict[str, str]:
    """Captures primary screen and overlays a 0-1000 coordinate grid."""
    app_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "GD Assistant")
    os.makedirs(app_dir, exist_ok=True)
    screenshot_path = os.path.join(app_dir, "current_screen.png")

    try:
        # Capture screenshot as RGB
        base_img = pyautogui.screenshot().convert("RGB")
        w, h = base_img.size

        # Pass mode="RGBA" to blend transparent lines directly over the RGB image
        draw = ImageDraw.Draw(base_img, mode="RGBA")

        # Draw a 10x10 coordinate grid (steps of 100 on a 0-1000 scale)
        for i in range(1, 10):
            x_pixel = int(w * (i / 10.0))
            y_pixel = int(h * (i / 10.0))

            # Red grid lines (120 alpha for subtle overlay)
            draw.line([(x_pixel, 0), (x_pixel, h)], fill=(255, 0, 0, 150), width=2)
            draw.line([(0, y_pixel), (w, y_pixel)], fill=(255, 0, 0, 150), width=2)

            # Red labels
            draw.text((x_pixel + 3, 5), f"X:{i*100}", fill=(255, 0, 0, 255))
            draw.text((5, y_pixel + 3), f"Y:{i*100}", fill=(255, 0, 0, 255))

        base_img.save(screenshot_path, format="PNG")
        return {
            "status": "SUCCESS",
            "message": f"Screenshot saved with grid overlay to {screenshot_path}.",
        }
    except Exception as error:
        return {"status": "FAILURE", "message": f"Failed to take screenshot: {error}"}

def click_at(x: int, y: int, button: str = "left", clicks: int = 1) -> dict[str, str]:
    """Clicks the mouse at target coordinates (normalized 0-1000 scale)."""
    screen_w, screen_h = pyautogui.size()

    # Convert 0-1000 normalized scale to real display pixels
    real_x = int((x / 1000.0) * screen_w)
    real_y = int((y / 1000.0) * screen_h)

    if not (0 <= real_x <= screen_w and 0 <= real_y <= screen_h):
        return {
            "status": "FAILURE",
            "message": f"Coordinates ({real_x}, {real_y}) are out of screen bounds ({screen_w}x{screen_h}).",
        }

    try:
        pyautogui.click(x=real_x, y=real_y, clicks=clicks, button=button)
        return {
            "status": "SUCCESS",
            "message": f"Clicked '{button}' at screen position ({real_x}, {real_y}) [Normalized: {x}, {y}].",
        }
    except Exception as error:
        return {"status": "FAILURE", "message": f"Click action failed: {error}"}

    try:
        pyautogui.click(x=x, y=y, clicks=clicks, button=button)
        return {
            "status": "SUCCESS",
            "message": f"Clicked {button} button {clicks} time(s) at position ({x}, {y}).",
        }
    except Exception as error:
        return {"status": "FAILURE", "message": f"Click action failed: {error}"}


def type_text(text: str, interval: float = 0.05) -> dict[str, str]:
    """Type string text character-by-character."""
    if not text:
        return {"status": "FAILURE", "message": "No text provided to type."}

    try:
        pyautogui.write(text, interval=interval)
        return {"status": "SUCCESS", "message": f"Successfully typed: '{text}'."}
    except Exception as error:
        return {"status": "FAILURE", "message": f"Typing failed: {error}"}


def press_key(key: str) -> dict[str, str]:
    """Press a single key or key combination (e.g., 'enter', 'tab', 'ctrl+c')."""
    normalized_key = key.lower().replace(" ", "")
    if normalized_key in BLOCKED_HOTKEYS:
        return {
            "status": "FAILURE",
            "message": f"Key combination '{key}' is blocked by guardrails.",
        }

    try:
        if "+" in key:
            keys = [k.strip() for k in key.split("+")]
            pyautogui.hotkey(*keys)
        else:
            pyautogui.press(key)
        return {"status": "SUCCESS", "message": f"Pressed key combination: '{key}'."}
    except Exception as error:
        return {"status": "FAILURE", "message": f"Key press failed: {error}"}


def scroll_screen(amount: int) -> dict[str, str]:
    """Scroll vertical direction (positive value scrolls up, negative scrolls down)."""
    try:
        pyautogui.scroll(amount)
        direction = "up" if amount > 0 else "down"
        return {
            "status": "SUCCESS",
            "message": f"Scrolled {direction} by {abs(amount)} units.",
        }
    except Exception as error:
        return {"status": "FAILURE", "message": f"Scroll failed: {error}"}

def confirm_action(action_description: str) -> bool:
    """Displays a native popup window requiring user permission."""
    response = pyautogui.confirm(
        text=f"GD Assistant requests permission to:\n\n'{action_description}'\n\nAllow this action?",
        title="GD Assistant Guardrail",
        buttons=["Allow", "Block"]
    )
    return response == "Allow"