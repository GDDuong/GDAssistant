# GD Assistant

> A Windows desktop assistant powered by Google Gemini — currently in **v0.3.1-BETA**.

GD Assistant combines Gemini's reasoning with carefully scoped local tools. Use it for conversation, voice interaction, limited desktop assistance, persistent local memory, and workspace-focused coding help.

Gemini is the **brain**; GD Assistant is the **local hands**. The application keeps control of which local actions are available and reports their actual success or failure before Gemini responds.

## Highlights

- **Chat Mode** — a desktop chat interface with optional voice input and spoken replies.
- **Code Mode** — an integrated Coding Agent interface, plus a terminal-first CLI for project work.
- **Light and Dark themes** — choose the appearance you prefer in Settings.
- **Flexible Gemini models** — let Chat and Code Mode share one model, or configure a different model for each.
- **Local memory** — save and retrieve preferences or facts between sessions.
- **Controlled desktop tools** — approved app launching, system information, screenshots, file search, and more.

## Interface & Modes

### Chat Mode

The default Windows interface includes a conversation view, text input, a voice button, Settings, and a Mode menu for switching to Code Mode. It can remain available from the Windows system tray.

### Code Mode

Code Mode is a workspace-focused coding assistant. In the GUI, select **Mode → Code**. The agent can inspect project files, make precise edits, create files, search code, and run development commands from the selected workspace.

For a terminal-oriented workflow, start Code CLI:

```powershell
python main.py --code
```

Useful Code CLI commands:

```text
/cd <path>                   Change the active workspace
/status                      Show the current workspace and model
/model <Gemini model name>   Change the active model for this CLI session
/exit                        Leave Code CLI
```

> **Important:** Code Mode can edit files and run development commands inside its chosen workspace. Only use it with projects and folders you trust.

### Other launch options

```powershell
# Normal desktop app
python main.py

# Desktop app with debug output in the launching console
python main.py --console

# Terminal-only chat
python main.py --terminal

# Voice-only terminal session
python main.py --voice

# Open the standalone Code Mode GUI
python main.py --code --gui

# Re-run first-time setup
python main.py --firstboot
```

`--debug` is an alias for `--console`.

## Gemini Models & Settings

The default Chat and Code model is `gemini-3.5-flash-lite`.

In **File → Settings**, you can:

- Select a common Gemini model or type a custom model name.
- Choose whether Chat and Code Mode use the same model.
- Set a separate Code model when shared models are turned off.
- Choose **Dark** or **Light** appearance.
- Set the global hotkey, language, and assistant personality.

The Code CLI can also temporarily switch models with `/model <name>` without changing your saved settings.

## Local Tools

Chat Mode exposes a controlled list of local tools rather than unrestricted PC access.

| Tool | Purpose |
| --- | --- |
| `open_app` | Opens an approved Windows app or configured custom app. |
| `close_app` | Closes an approved app after confirmation. |
| `open_file` | Opens a local file or folder with Windows. |
| `get_system_stats` | Reports CPU, memory, and disk usage. |
| `search_files` | Searches file names in the user folder. |
| `open_url` | Opens an `http` or `https` link in the default browser. |
| `get_current_time` | Returns the local date and time. |
| `remember_info` / `forget_info` / `get_all_memory` | Manage local persistent memory. |
| `take_screenshot` | Captures the primary display for on-request analysis. |
| `click_at` / `type_text` / `press_key` / `scroll_screen` | Provides limited desktop interaction. |

### Security

GD Assistant does not grant Chat Mode unrestricted access to Windows. Local tools are explicitly registered, apps must be approved, browser links are limited to web URLs, and potentially disruptive actions such as closing applications and selected shortcuts require confirmation.

Tool results are logged in Console/Debug mode. The assistant uses those real results to distinguish successful actions from failed ones.

## Voice System

Voice input uses **Faster-Whisper** (`base.en`) locally on the CPU. The model warms in the background while the app opens, so Chat and Code Mode stay usable. Recording stops after a short period of silence, then sends the transcription to Gemini.

Voice replies use **Microsoft Edge TTS** with `en-US-AvaNeural`. If that is unavailable, GD Assistant falls back to Windows SAPI5 through `pyttsx3`.

## Local Data & API Key

GD Assistant stores its configuration locally under:

```text
%APPDATA%\GD Assistant\
```

This includes:

```text
api.json       Gemini API key
config.json    Models, theme, language, hotkey, microphone, and personality
memory.json    Persistent assistant memory
```

You can alternatively provide the key through an environment variable:

```powershell
$env:GEMINI_API_KEY = "YOUR_API_KEY"
```

The environment variable takes priority. Never commit `api.json` or share your API key.

## Installation

### Requirements

- Windows
- Python 3.10 or later
- A Gemini API key

Install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Start the app:

```powershell
python main.py
```

The first launch opens the setup wizard for your Gemini API key, Chat and Code models, theme, microphone, hotkey, and personality.

## Building the executable

Install PyInstaller, then build the windowed one-file release:

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean GD_Assistant-v0.3.1-BETA.spec
```

The finished build is created at:

```text
dist\GD_Assistant-v0.3.1-BETA.exe
```

## Project Status

**Current version:** `v0.3.1-BETA`

GD Assistant is an active beta project on the road to v1.0. Features, supported Gemini models, local tools, and safety rules may evolve as the project is tested and improved.

See [CHANGELOG.md](CHANGELOG.md) for v0.3.1-BETA release notes.
