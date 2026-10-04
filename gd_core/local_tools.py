"""Explicit, local-only tools available to GD Assistant.

Every tool in this module must validate its own input. Gemini may suggest a tool
call, but it never receives unrestricted command execution on this computer.
Every tool returns a ToolResult whose ``status`` reflects whether the *local
action itself* succeeded — a clean "no results" from search_files is still
SUCCESS, because the search ran correctly.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
import urllib.parse
import webbrowser
import winsound
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import TypedDict
import json
from typing import Any
from PIL import ImageGrab
import pyautogui
import psutil
from PIL import Image, ImageDraw, ImageFont
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
import pyperclip

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
            "path": screenshot_path,
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

def search_and_read_webpage(query: str) -> dict[str, str]:
    """Search the web for any query, pick the top result URL, and scrape its main text content."""
    if not isinstance(query, str) or not query.strip():
        return {"status": "FAILURE", "message": "Search query cannot be empty."}

    try:
        # 1. Perform the text search to find the most relevant URL
        with DDGS() as ddgs:
            results = list(ddgs.text(query.strip(), max_results=3))
            if not results:
                return {"status": "SUCCESS", "message": f"No web search results found for '{query}'."}

            target_url = results[0].get('href')
            target_title = results[0].get('title')

        if not target_url:
            return {"status": "FAILURE", "message": "Could not extract a valid URL from search results."}

        # 2. Fetch the target web page
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        response = requests.get(target_url, headers=headers, timeout=10)
        response.raise_for_status()

        # 3. Parse HTML and strip irrelevant boilerplate
        soup = BeautifulSoup(response.text, "html.parser")
        for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
            element.decompose()

        page_text = soup.get_text(separator="\n", strip=True)

        # Limit content length to prevent token overflow
        max_chars = 7000
        if len(page_text) > max_chars:
            page_text = page_text[:max_chars] + "\n\n[Content truncated due to length...]"

        return {
            "status": "SUCCESS",
            "message": (
                f"Successfully read page content from search result:\n"
                f"**Title**: {target_title}\n"
                f"**URL**: {target_url}\n\n"
                f"--- Page Content Start ---\n{page_text}\n--- Page Content End ---"
            )
        }
    except Exception as error:
        return {"status": "FAILURE", "message": f"Failed to search and read webpage: {error}"}

def read_clipboard() -> dict[str, str]:
    """Read text currently stored in the system clipboard."""
    try:
        content = pyperclip.paste()
        if not content:
            return {"status": "SUCCESS", "message": "The clipboard is currently empty."}
        return {"status": "SUCCESS", "message": f"Clipboard content:\n\n{content}"}
    except Exception as e:
        return {"status": "FAILURE", "message": f"Failed to read clipboard: {e}"}


def write_clipboard(text: str) -> dict[str, str]:
    """Write text to the system clipboard."""
    try:
        pyperclip.copy(text)
        return {"status": "SUCCESS", "message": "Successfully copied text to clipboard."}
    except Exception as e:
        return {"status": "FAILURE", "message": f"Failed to write to clipboard: {e}"}


def read_local_file(file_path: str) -> dict[str, str]:
    """Read the text content of a local file safely (under 500KB)."""
    if not isinstance(file_path, str) or not file_path.strip():
        return {"status": "FAILURE", "message": "File path cannot be empty."}

    clean_path = file_path.strip('"').strip("'")
    if not os.path.exists(clean_path):
        return {"status": "FAILURE", "message": f"File not found: {clean_path}"}

    try:
        if os.path.getsize(clean_path) > 500 * 1024:
            return {"status": "FAILURE", "message": "File is too large to read safely (>500KB)."}

        with open(clean_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        return {
            "status": "SUCCESS",
            "message": f"Content of {os.path.basename(clean_path)}:\n\n{content}"
        }
    except Exception as e:
        return {"status": "FAILURE", "message": f"Failed to read file: {e}"}


# ---------------------------------------------------------------- timers ----

MAX_TIMER_SECONDS = 24 * 60 * 60
_active_timers: dict[str, threading.Timer] = {}


def _format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} second(s)"
    minutes, rest = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} minute(s)" if not rest else f"{minutes} min {rest} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} hour(s) {minutes} min" if minutes else f"{hours} hour(s)"


def set_timer(seconds: float, label: str = "") -> ToolResult:
    """Start a countdown timer that alerts with a beep and a popup when done.

    Args:
        seconds: Countdown length, between 1 second and 24 hours.
        label: Optional name for the timer, e.g. 'tea'.
    """
    try:
        duration = float(seconds)
    except (TypeError, ValueError):
        return {"status": "FAILURE", "message": "Timer length must be a number of seconds."}
    if not 1 <= duration <= MAX_TIMER_SECONDS:
        return {"status": "FAILURE", "message": "Timers must be between 1 second and 24 hours."}

    name = (label or "Timer").strip()[:80]

    def ring() -> None:
        _active_timers.pop(name, None)
        try:
            for _ in range(3):
                winsound.Beep(1200, 350)
                time.sleep(0.15)
            ctypes.windll.user32.MessageBoxW(0, f"'{name}' is done.", "GD Assistant Timer", 0x40)
        except Exception:
            pass

    timer = threading.Timer(duration, ring)
    timer.daemon = True
    timer.start()
    _active_timers[name] = timer
    return {
        "status": "SUCCESS",
        "message": f"Timer '{name}' set for {_format_duration(duration)}. I will alert you when it is done.",
    }


def cancel_timer(label: str) -> ToolResult:
    """Stop a running timer by its label."""
    name = (label or "").strip()[:80]
    timer = _active_timers.pop(name, None)
    if timer is None:
        running = ", ".join(_active_timers) or "none"
        return {"status": "FAILURE", "message": f"No running timer named '{name}'. Currently running: {running}."}
    timer.cancel()
    return {"status": "SUCCESS", "message": f"Timer '{name}' cancelled."}


# --------------------------------------------------------------- windows ----

_user32 = ctypes.windll.user32
_SW_RESTORE = 9
_SW_MINIMIZE = 6


def _window_title(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if not length:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value or ""


def _is_visible_window(hwnd: int) -> bool:
    return bool(_user32.IsWindowVisible(hwnd))


def list_windows() -> ToolResult:
    """List the titles of all open, visible top-level windows."""
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collector(hwnd, _lparam):
        if _is_visible_window(hwnd):
            title = _window_title(hwnd)
            if title and title != "Program Manager":
                titles.append(title)
        return True

    try:
        _user32.EnumWindows(collector, 0)
    except OSError:
        return {"status": "FAILURE", "message": "I couldn't read the window list right now."}

    if not titles:
        return {"status": "SUCCESS", "message": "No open windows found."}
    listing = "\n".join(f"- {title}" for title in titles[:30])
    extra = f"\n(+{len(titles) - 30} more)" if len(titles) > 30 else ""
    return {"status": "SUCCESS", "message": f"{len(titles)} open window(s):\n{listing}{extra}"}


def focus_window(title_match: str) -> ToolResult:
    """Bring the first window whose title contains the given text to the front.

    Args:
        title_match: Case-insensitive snippet of the window title, e.g. 'Notepad'.
    """
    if not isinstance(title_match, str) or not title_match.strip():
        return {"status": "FAILURE", "message": "A window title snippet is required."}
    needle = title_match.strip().casefold()
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collector(hwnd, _lparam):
        if _is_visible_window(hwnd) and needle in _window_title(hwnd).casefold():
            found.append(hwnd)
            return False
        return True

    _user32.EnumWindows(collector, 0)
    if not found:
        return {"status": "FAILURE", "message": f"No open window matches '{title_match.strip()}'."}

    hwnd = found[0]
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)
    _user32.SetForegroundWindow(hwnd)
    return {"status": "SUCCESS", "message": f"Brought '{_window_title(hwnd)}' to the front."}


def minimize_all() -> ToolResult:
    """Minimize every visible window except GD Assistant itself."""
    my_pid = wintypes.DWORD()
    minimized: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collector(hwnd, _lparam):
        if not _is_visible_window(hwnd) or _user32.IsIconic(hwnd):
            return True
        title = _window_title(hwnd)
        if not title or title == "Program Manager":
            return True
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(my_pid))
        if my_pid.value == os.getpid():
            return True
        _user32.ShowWindow(hwnd, _SW_MINIMIZE)
        minimized.append(title)
        return True

    _user32.EnumWindows(collector, 0)
    if not minimized:
        return {"status": "SUCCESS", "message": "There was nothing to minimize."}
    return {"status": "SUCCESS", "message": f"Minimized {len(minimized)} window(s): {', '.join(minimized[:10])}."}


# ---------------------------------------------------------------- files -----

MAX_WRITE_CHARS = 200_000


def write_local_file(file_path: str, content: str, append: bool = False) -> ToolResult:
    """Save text to a file inside the user's home folder (creates parents).

    Args:
        file_path: Absolute path under the user's home directory.
        content: Text to write.
        append: When true, adds to the end of the file instead of replacing it.
    """
    if not isinstance(file_path, str) or not file_path.strip():
        return {"status": "FAILURE", "message": "File path cannot be empty."}
    if not isinstance(content, str):
        return {"status": "FAILURE", "message": "Content must be text."}
    if len(content) > MAX_WRITE_CHARS:
        return {"status": "FAILURE", "message": f"Content is too large to write safely (>{MAX_WRITE_CHARS} characters)."}

    target = Path(os.path.abspath(file_path.strip().strip('"')))
    home = Path.home().resolve()
    if target != home and home not in target.parents:
        return {
            "status": "FAILURE",
            "message": f"I can only save files inside your user folder ({home}), not '{target}'.",
        }
    if home / "AppData" in target.parents:
        return {
            "status": "FAILURE",
            "message": "I can't write inside AppData — that folder holds application settings and secrets.",
        }

    existed = target.exists()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if (append and existed) else "w"
        with target.open(mode, encoding="utf-8") as file:
            file.write(content)
    except OSError as error:
        return {"status": "FAILURE", "message": f"Failed to write '{target}': {error}"}

    verb = "Appended to" if mode == "a" else ("Overwrote" if existed else "Created")
    return {"status": "SUCCESS", "message": f"{verb} '{target}' ({len(content)} characters)."}

# ------------------------------------------- media, clipboard, quick info -----

MAX_CLIPBOARD_CHARS = 10_000
MAX_READ_CHARS = 100_000

# Virtual-key codes for hardware media keys; validated against this map so the
# model can only ever pick one of these fixed actions.
_MEDIA_KEY_VK = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "previous": 0xB1,
    "volume_up": 0xAF,
    "volume_down": 0xAE,
    "mute": 0xAD,
}


def _log(debug: bool, message: str) -> None:
    """Print a debug line when the host app passes its debug flag down."""
    if debug:
        print(f"[TOOLS] {message}")


def media_control(action: str, debug: bool = False) -> ToolResult:
    """Send one hardware media key: play_pause, next, previous, volume_up, volume_down, or mute.

    Args:
        action: One of the fixed action names in _MEDIA_KEY_VK.
    """
    if not isinstance(action, str) or not action.strip():
        return {"status": "FAILURE", "message": "An action name is required."}
    vk = _MEDIA_KEY_VK.get(action.strip().lower())
    if vk is None:
        allowed = ", ".join(sorted(_MEDIA_KEY_VK))
        return {"status": "FAILURE", "message": f"Unknown action '{action}'. Use one of: {allowed}."}
    try:
        _user32.keybd_event(vk, 0, 0, 0)
        _user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
    except OSError as error:
        return {"status": "FAILURE", "message": f"Couldn't send media command '{action}': {error}"}
    _log(debug, f"media_control sent '{action.strip().lower()}'")
    return {"status": "SUCCESS", "message": f"Sent media command '{action.strip().lower()}'."}


def get_clipboard() -> ToolResult:
    """Return the current clipboard text (empty message when it holds no text)."""
    try:
        text = pyperclip.paste()
    except Exception:
        return {"status": "FAILURE", "message": "I couldn't read the clipboard right now."}
    if not text:
        return {"status": "SUCCESS", "message": "The clipboard is empty (or holds non-text content)."}
    clipped = ""
    if len(text) > MAX_CLIPBOARD_CHARS:
        clipped = "\n[...clipboard text truncated...]"
        text = text[:MAX_CLIPBOARD_CHARS]
    return {"status": "SUCCESS", "message": f"Clipboard text:\n{text}{clipped}"}


def set_clipboard(text: str, debug: bool = False) -> ToolResult:
    """Copy text onto the clipboard, replacing its current content."""
    if not isinstance(text, str) or not text:
        return {"status": "FAILURE", "message": "Text to copy cannot be empty."}
    if len(text) > MAX_CLIPBOARD_CHARS:
        return {
            "status": "FAILURE",
            "message": f"That text is too large to copy (>{MAX_CLIPBOARD_CHARS} characters).",
        }
    try:
        pyperclip.copy(text)
    except Exception:
        return {"status": "FAILURE", "message": "I couldn't write to the clipboard."}
    _log(debug, f"set_clipboard copied {len(text)} characters")
    return {"status": "SUCCESS", "message": f"Copied {len(text)} characters to the clipboard."}


def get_battery_status() -> ToolResult:
    """Report battery percentage and charging state (desktops get a clear note)."""
    try:
        battery = psutil.sensors_battery()
    except (OSError, psutil.Error):
        battery = None
    if battery is None:
        return {
            "status": "SUCCESS",
            "message": "This PC doesn't have a battery (it's a desktop or a plugged-in workstation).",
        }
    percent = round(battery.percent)
    if battery.power_plugged:
        state = "plugged in and fully charged" if percent >= 99 else "plugged in and charging"
    else:
        state = "running on battery"
    message = f"Battery is at {percent}% ({state})."
    if (
        not battery.power_plugged
        and battery.secsleft not in (psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN)
        and battery.secsleft > 0
    ):
        minutes = battery.secsleft // 60
        message += f" Roughly {minutes // 60} h {minutes % 60} min of charge left."
    return {"status": "SUCCESS", "message": message}


def get_active_window() -> ToolResult:
    """Return the title of the window that currently has focus."""
    try:
        hwnd = _user32.GetForegroundWindow()
        title = _window_title(hwnd) if hwnd else ""
    except OSError:
        return {"status": "FAILURE", "message": "I couldn't read the active window."}
    if not title:
        return {"status": "SUCCESS", "message": "The active window has no title (likely the desktop)."}
    return {"status": "SUCCESS", "message": f"The active window is '{title}'."}


def read_local_file(file_path: str, debug: bool = False) -> ToolResult:
    """Read a text file from the user's home folder and return its contents.

    AppData is excluded: it holds application secrets (including this app's
    api.json), so those files are never readable through this tool.
    """
    if not isinstance(file_path, str) or not file_path.strip():
        return {"status": "FAILURE", "message": "File path cannot be empty."}

    target = Path(os.path.abspath(file_path.strip().strip('"')))
    home = Path.home().resolve()
    if target != home and home not in target.parents:
        _log(debug, f"read_local_file rejected '{target}' (outside home)")
        return {
            "status": "FAILURE",
            "message": f"I can only read files inside your user folder ({home}), not '{target}'.",
        }
    if home / "AppData" in target.parents:
        _log(debug, f"read_local_file rejected '{target}' (inside AppData)")
        return {
            "status": "FAILURE",
            "message": "I can't read files inside AppData — that folder holds application secrets like API keys.",
        }
    if not target.is_file():
        _log(debug, f"read_local_file: '{target}' is not a file")
        return {"status": "FAILURE", "message": f"'{target}' is not a file."}
    if target.stat().st_size > MAX_READ_CHARS * 4:
        _log(debug, f"read_local_file: '{target}' too large ({target.stat().st_size} bytes)")
        return {
            "status": "FAILURE",
            "message": f"'{target.name}' is too large to read safely (>{MAX_READ_CHARS * 4} bytes).",
        }

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return {"status": "FAILURE", "message": f"Failed to read '{target}': {error}"}

    clipped = ""
    if len(content) > MAX_READ_CHARS:
        clipped = "\n[...file truncated...]"
        content = content[:MAX_READ_CHARS]
    _log(debug, f"read_local_file read '{target.name}' ({len(content)} characters)")
    return {"status": "SUCCESS", "message": f"'{target.name}' ({len(content)} characters):\n{content}{clipped}"}
