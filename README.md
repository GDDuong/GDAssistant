# GD Assistant v0.1.1-BETA

A small Windows personal assistant: terminal or GUI text chat backed by Gemini, with a tightly controlled set of local actions.

The current text model is `gemini-3.5-flash-lite`. It is configured for the available 500 requests/day and 250K tokens/minute quota shown in the project's Google AI Studio account. A future voice phase will use the Live API separately; Live models cannot replace this text endpoint directly.

## Setup

Requires Python 3.10+ and a Gemini API key you create for yourself.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python gd_assistant.py
```

Open `api.json` and replace the empty value with your Gemini API key. The file is ignored by Git and is never printed by the application. You may alternatively set `GEMINI_API_KEY` for the current PowerShell session; that takes precedence over `api.json`. Type `/quit` to leave the chat.

## Starting it on Windows

After adding your key, double-click [Start GD Assistant.bat](<Start GD Assistant.bat>) to open the clean chat UI. Use [Start GD Assistant Console.bat](<Start GD Assistant Console.bat>) for the UI plus a separate debug console. The console records local tool requests and their authoritative `SUCCESS`/`FAILURE` outcome, while the chat window stays uncluttered. You can also run `python gd_assistant.py -console` from PowerShell. Use `--terminal` to return to the original terminal-only chat.

If a request says `ServerError`, the application is working but Gemini's service was temporarily unavailable. Wait a few seconds and send the message again; no local data or settings were changed.

## Local tools (Phase 2)

Gemini never gets unrestricted access to the PC. It can only *request* one of six approved tools; `gd_assistant.py` validates and executes the request, then reports the exact `SUCCESS`/`FAILURE` outcome back to Gemini before it replies to you.

| Tool | What it does | Guardrails |
| --- | --- | --- |
| `open_app(app_name)` | Launches one allowlisted app | Fixed executable list, no shell, no arbitrary paths |
| `close_app(app_name)` | Closes one allowlisted app via `taskkill /IM` | Same allowlist as `open_app`; matches by fixed image name only |
| `get_system_stats()` | Reports CPU, memory, and disk usage | Read-only, no arguments |
| `search_files(query)` | Finds files by name under the user's home folder | Confined to `%USERPROFILE%`; skips hidden/system/git folders; capped at 20 results and 20,000 entries scanned |
| `open_url(url)` | Opens a link in the default browser | Only `http://`/`https://` accepted — `file://`, `javascript:`, etc. are rejected before anything runs |
| `get_current_time()` | Returns the current local date/time | Read-only, no arguments |

Both `open_app` and `close_app` accept only an allowlisted app — Notepad, Calculator, Paint, File Explorer, Snipping Tool, Task Manager, Control Panel, Character Map, Magnifier, or On-Screen Keyboard. App names, file paths, commands, and all other requests are rejected locally, before any process is touched.

Adding a new tool later means three small, localized edits: implement it in `local_tools.py`, add its declaration to `TOOL_DECLARATIONS`, and add one line to `TOOL_REGISTRY` in `gd_assistant.py` — the dispatch loop itself doesn't change.

## Design choices

- `google-genai` is Google's current Python SDK; `psutil` backs `get_system_stats`.
- One Gemini chat object preserves context during the current session.
- Errors are shown as safe, actionable messages rather than raw API output.
- `execute_tool_call` looks up the requested tool in `TOOL_REGISTRY` and also catches unexpected exceptions from a tool itself, so a bug in one tool can't crash the assistant — it just reports that tool as failed.
- When a tool runs, the console (if enabled) first prints `LOCAL TOOL SUCCESS: ...` or `LOCAL TOOL FAILURE: ...`. This local confirmation is authoritative; Gemini receives the same exact result before it replies.
- `search_files` treats a clean zero-result search as `SUCCESS` (the search ran fine) rather than `FAILURE` (which is reserved for the search itself not being able to run).
- No arbitrary commands, file *modification*, mouse/keyboard control, screenshots, or persistent memory are included yet — those are later phases, and the plan calls for user confirmation before anything destructive is added.
