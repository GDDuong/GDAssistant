# GD Assistant (currently in beta v0.2-BETA)

**GD Assistant** is a Windows personal desktop assistant powered by Google's Gemini API. It can chat with you, provide useful system information, remember information, open apps and files, and perform limited desktop actions.

The assistant is designed with security restrictions so Gemini does not have unrestricted control over your computer.

## ✨ Features

### Core Overview

- Powered by the **Gemini API** using Google's `google-genai` library.
- Uses `gemini-3.5-flash-lite` by default.
- Includes a simple **first-time setup wizard** for:
  - Gemini API key
  - AI model selection
  - Global keyboard shortcut
- Settings are stored locally in:

```text
%APPDATA%\GD Assistant\
```

### 🖥️ Interface & Modes

GD Assistant can be used in several ways:

**GUI Mode**  
A normal Windows application with a chat window, message box, and voice controls.

**System Tray**  
GD Assistant can stay running in the background from the Windows system tray. From there you can reopen the assistant or exit it.

**Command-Line Modes**

```powershell
gd_assistant.exe --console
```

Shows debugging information while the assistant runs.

```powershell
gd_assistant.exe --terminal
```

Runs GD Assistant entirely in the terminal.

```powershell
gd_assistant.exe --voice
```

Starts voice-only mode.

```powershell
gd_assistant.exe --firstboot
```

Runs the first-time setup wizard again.

## 🛠️ Local Tools

Gemini can request a limited set of tools to interact with your computer. These tools are controlled locally by GD Assistant rather than giving Gemini unrestricted PC access.

| Tool | What it does |
|---|---|
| `open_app` | Opens approved Windows applications or configured custom programs. |
| `close_app` | Closes approved applications after asking for confirmation. |
| `open_file` | Opens files or folders using their normal Windows applications. |
| `get_system_stats` | Shows CPU, memory, and disk usage. |
| `search_files` | Searches for files by name inside your user folder. |
| `open_url` | Opens safe `HTTP` or `HTTPS` links in your browser. |
| `remember_info` | Saves information for GD Assistant to remember later. |
| `forget_info` | Removes previously saved information. |
| `get_all_memory` | Shows the information currently stored in memory. |
| `take_screenshot` | Takes a screenshot with a coordinate grid to help with desktop actions. |
| `click_at` | Clicks a specific location on the screen. |
| `type_text` | Types text into the active application. |
| `press_key` | Presses a keyboard key or shortcut. |
| `scroll_screen` | Scrolls the screen up or down. |

(This list is subject to change in the future.)

### 🔒 Security

Desktop-control tools are protected by safety checks and restrictions. GD Assistant does **not** simply give Gemini full control of Windows.

For example, applications that can be launched are restricted, URLs are limited to web protocols, and potentially disruptive actions such as closing applications require user confirmation.

## 🧠 Persistent Memory

GD Assistant can remember information between sessions.

Memory is stored locally in:

```text
%AppData%\GD Assistant\memory.json
```

You can add, remove, or view saved information using the memory tools.

This allows the assistant to remember useful preferences or details without relying entirely on the current conversation.

## 🎙️ Voice System

GD Assistant supports both **voice input** and **voice responses**.

### Speech-to-Text

Voice input uses **faster-whisper** with the `small.en` model running on the CPU.

It automatically:

- Calibrates for the room's background noise.
- Detects when you start and stop speaking.
- Converts your speech into text for Gemini.

### Text-to-Speech

Voice responses use **Microsoft Edge TTS** with the `en-US-AvaNeural` voice.

Audio is played through Windows' native audio system, with `pyttsx3` used as a fallback if Edge TTS is unavailable.

## 📦 Installation

### Requirements

- Windows
- Python 3.10+
- A Gemini API key

Create a virtual environment and install the required packages:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Then start GD Assistant:

```powershell
python gd_assistant.py
```

On the first launch, the setup wizard will guide you through the required configuration.

## 🔑 Gemini API Key

Your Gemini API key is stored locally as part of GD Assistant's configuration.

You can also use the `GEMINI_API_KEY` environment variable instead:

```powershell
$env:GEMINI_API_KEY="YOUR_API_KEY"
```

The environment variable takes priority over the locally stored API key.

## 🚀 Project Status

**Version:** `v0.2-BETA`

GD Assistant is currently a beta project. Features, supported tools, and security restrictions may change as development continues.

This project is vibe-coded using the use of Gemini with the help of me, a real developer.
