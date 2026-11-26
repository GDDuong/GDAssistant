# GD Assistant

> A Windows desktop assistant powered by Google Gemini — currently in **v0.6-BETA**.

GD Assistant combines Gemini's reasoning with carefully scoped local tools. Use it for conversation, voice interaction, limited desktop assistance, persistent local memory, and workspace-focused coding help.

Gemini is the **brain**; GD Assistant is the **local hands**. The application keeps control of which local actions are available and reports their actual success or failure before Gemini responds.

## Highlights

- **Chat Mode** — a desktop chat interface with optional voice input and spoken replies.
- **Wake word** — say your summoning sentence (default "hey assistant") to start a hands-free voice conversation.
- **Code Mode** — a project-aware coding workspace: the agent reads the project, keeps a visible plan, proposes diffs you accept or reject, runs terminals you can watch, and checkpoints its work; a terminal-first CLI drives the same agent.
- **Skills** — portable `SKILL.md` instruction packs: create them, allow them per chat, or invoke one for a single message with `@skill-name`.
- **Chat history** — saved conversations in a collapsible sidebar for both modes, grouped under their project in Code Mode.
- **Live streaming** — replies appear token-by-token with a Stop button; typed replies render markdown while voice replies stay plain.
- **File attachments** — a **+** button next to the text box inserts one or more files into your next message in both Chat and Code Mode; text and Office documents (Word/Excel/PowerPoint) are quoted in full while images/PDFs are sent for the model to see.
- **Themes & accent color** — Light or Dark appearance with a customizable accent from presets, the color picker, or a hex value.
- **Flexible Gemini models** — let Chat and Code Mode share one model, or configure a different model for each.
- **Local memory** — save and retrieve preferences or facts between sessions.
- **Controlled desktop tools** — approved app launching, window and clipboard control, timers, media and volume, web search, screenshots, and more.

## Interface & Modes

### Chat Mode

The default Windows interface includes a conversation view, text input, a voice button, Settings, and a Mode menu for switching to Code Mode. It can remain available from the Windows system tray. Use **Skills** beside the input to allow portable `SKILL.md` instruction packs or create your own; allowed skills persist per chat and never expand tool permissions, and typing `@` in the input lists them.

### Code Mode

Code Mode is a lightweight project-aware coding environment. Select **Mode → Code**, create a project by choosing any file inside its folder, and describe a task in natural language. The agent can inspect the project, create a visible plan, edit multiple files, run builds/tests, investigate real failures, and verify its changes. Each project keeps its own permission mode, so changing it in one project does not affect the others.

The history sidebar groups multiple chats under each project, with rename/archive/delete controls and shared workspace/reference folders. You can also start a standalone Code chat without a project; it uses the configurable default workspace (Documents by default).

The interface includes:

- **Project Explorer** with folder tree, filename search, recent files, and project switching.
- **Editor** with line numbers, lightweight syntax highlighting, safe save, and revert.
- **Changes** with unified diffs, per-change accept/reject, and undo that refuses to overwrite external edits.
- **Terminal dock** with live stdout/stderr, exit status, Stop, multiple sessions, timeouts, permission checks, and a collapse control; workspace and terminal tabs include hover descriptions.
- **Plan / Overview / Agent Activity** showing progress, detected tooling, commands, files, and errors.
- **Skills** for allowing project/user `SKILL.md` packs, creating new ones without leaving Code Mode, and invoking one with `@skill-name` for a single message.
- **Checkpoints** so `/continue` can resume interrupted work.

Code Mode is language-agnostic. It detects common Python, Node, Java/Gradle/Maven, Rust, Go, .NET, C/C++, CMake, Flutter, PHP, Ruby, and other projects from their real manifests and files.

#### Minecraft mod development

Opening a Fabric, Forge, NeoForge, or Quilt project produces a verified profile with Minecraft version, loader, Java toolchain, mappings, mod ID, dependencies, entrypoints, and source/resource directories. These commands perform real actions:

```text
/mod-info       Show the detected mod profile
/mod-build      Run the detected Gradle build task
/mod-test       Run the detected Gradle test task
/mod-run        Run the detected development client
/mod-debug      Investigate a mod error and rebuild
/mod-deps       Inspect declared dependencies
/mod-mappings   Inspect mappings and versions
/mod-audit      Check metadata and compatibility
```

#### Slash commands

```text
/plan <request>   Create a visible implementation plan
/status           Show workspace, plan, modified files, and terminals
/context          Show project detection and index summary
/continue         Resume the latest interrupted checkpoint
/explain <scope>  Explain code read-only
/review <scope>   Review code read-only
/audit <scope>    Audit the project read-only
/refactor <scope> Refactor and verify
/debug <scope>    Investigate, fix, and verify errors
/stop             Stop the agent and running terminal processes
```

For a terminal-oriented workflow:

```powershell
python main.py --code --workspace "C:\path\to\project"
```

> **Safety:** model tools are restricted to the selected workspace and optional read-only reference directories. Sensitive files such as `.env`, private keys, and credential files are blocked from model tools. File changes are snapshotted before overwriting. Supervised mode asks before every write/command; Project Autonomous allows routine project work but asks for destructive or privileged operations. GD Assistant never commits, pushes, or elevates privileges without explicit authorization.

### Other launch options

```powershell
# Normal desktop app
python main.py

# Desktop app with debug output in the launching console
python main.py --debug

# Terminal-only chat
python main.py --terminal

# Voice-only terminal session
python main.py --voice

# Open the standalone Code Mode GUI
python main.py --code --gui

# Re-run first-time setup
python main.py --firstboot
```

## Gemini Models & Settings

The default Chat and Code model is `gemini-3.5-flash-lite`.

In **File → Settings**, you can:

- Select a common Gemini model or type a custom model name.
- Choose whether Chat and Code Mode use the same model.
- Set a separate Code model when shared models are turned off.
- Choose **Dark** or **Light** appearance and an accent color.
- Set the global hotkey, language, and assistant personality.
- Configure **Code Mode** project defaults, permission mode, iteration/time limits, ignored directories, indexing, checkpoint retention, dependency installation, terminal behavior, and editor preferences.

The Code CLI can also temporarily switch models with `/model <name>` without changing your saved settings.

## Local Tools

Chat Mode exposes a controlled list of local tools rather than unrestricted PC access.

| Tool | Purpose |
| --- | --- |
| `open_app` / `close_app` | Opens an approved Windows or configured custom app; closes an approved app after confirmation. |
| `open_file` | Opens a local file or folder with Windows. |
| `read_local_file` / `write_local_file` | Reads or writes text files inside your user folder. |
| `search_files` | Searches file names in the user folder. |
| `get_system_stats` / `get_battery_status` | Reports CPU, memory, disk, and battery level. |
| `list_windows` / `focus_window` / `get_active_window` / `minimize_all` | Lists, focuses, and identifies open windows. |
| `set_timer` / `cancel_timer` | Starts and cancels local countdowns. |
| `get_clipboard` / `set_clipboard` | Reads and writes clipboard text. |
| `media_control` | Plays/pauses and skips music and adjusts system volume. |
| `search_web` | Searches the web and reads back the top result. |
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

**Wake word (optional):** enable *always listening* in Settings and GD Assistant waits in the background for your summoning sentence, then starts a voice conversation hands-free. Detection stays lightweight — the same speech model (`base.en`) already loaded for voice input runs only on short speech clips, so nothing extra sits in memory — and the listener pauses while the assistant listens or replies so it never hears its own voice. Wake word works in Chat Mode.

## Local Data & API Key

GD Assistant stores its configuration locally under:

```text
%APPDATA%\GD Assistant\
```

This includes:

```text
api.json       Gemini API key
config.json    Models, theme, accent color, language, hotkey, microphone, and personality
memory.json    Persistent assistant memory
history\       Saved chat and code conversations (one JSON file each)
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

The first launch opens the setup wizard to pick your theme, enter your Gemini API key with Chat and Code models, then choose your microphone, hotkey, and personality.

## Building the releases

Every release ships in three formats: a **portable** one-file exe, an **offline installer**, and a small **web installer** that downloads the portable exe from GitHub Releases. PyInstaller builds the app; [Inno Setup](https://jrsoftware.org/isinfo.php) builds both installers.

### 1. Portable exe

```powershell
python -m PyInstaller --noconfirm --clean GD_Assistant-v0.6-BETA.spec
```

The finished build is created at:

```text
dist\GD_Assistant-v0.6-BETA.exe
```

### 2. Offline installer

Build the folder package first, then wrap it with Inno Setup (`iscc` is installed with Inno Setup, add it to `PATH` or use its full path):

```powershell
python -m PyInstaller --noconfirm --clean GD_Assistant-v0.6-BETA-Setup.spec
iscc installer\GD_Assistant-v0.6-BETA.iss
```

The finished installer is created at:

```text
installer\Output\GD_Assistant-v0.6-BETA-Setup.exe
```

### 3. Web installer

A small downloader that fetches the portable exe from the GitHub Release at install time, so upload `dist\GD_Assistant-v0.6-BETA.exe` to the release first, then build with its SHA-256 baked in for integrity checking:

```powershell
powershell -Command "(Get-FileHash 'dist\GD_Assistant-v0.6-BETA.exe' -Algorithm SHA256).Hash"
iscc /DPortableSHA256=<hash-from-above> installer\GD_Assistant-v0.6-BETA-Web.iss
```

The finished installer is created at:

```text
installer\Output\GD_Assistant-v0.6-BETA-WebSetup.exe
```

## Tests

Run the headless compatibility and Code Mode suites:

```powershell
python test_config_smoke.py
python test_code_mode.py
python test_skills.py
```

The Code Mode suite uses temporary projects for workspace-boundary, snapshot/undo, terminal, project-detection, Minecraft-profile, agent-loop, checkpoint, and IDE smoke checks. The skill suite covers portable skill discovery, creation, agent injection, project chat grouping, and default workspace/permission labels.

## Project Status

**Current version:** `v0.6-BETA`

GD Assistant is an active beta project on the road to v1.0. Features, supported Gemini models, local tools, and safety rules may evolve as the project is tested and improved.

See [CHANGELOG.md](CHANGELOG.md) for v0.6-BETA release notes.
