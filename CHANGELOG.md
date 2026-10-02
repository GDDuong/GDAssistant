# Changelog

All notable changes to GD Assistant are documented here.

## v0.4-BETA

### Highlights

- **Chat history** — a collapsible sidebar in Chat Mode and Code Mode lists your saved conversations, with New Chat / New Project at the top, right-click options (open, rename, archive, unarchive, delete), and JSON files stored in `%APPDATA%\GD Assistant\history`.
- **Live token streaming** — replies appear as they are generated in Chat and Code Mode, with a red **Stop** button that interrupts mid-stream without corrupting the conversation.
- **Markdown replies** — typed requests now get formatted answers (headings, bold, italics, inline and fenced code, lists, links), while voice requests stay plain text so they sound natural spoken aloud.

### Chat & Projects

- Conversations persist across restarts and reopen with their full transcript.
- Code Mode conversations can have their own project workspace plus additional read-only reference directories, injected into the agent's instructions.
- A Chat conversation can be converted into a Code Mode project (one-way), importing the whole transcript as context.
- Code Mode chats can no longer be turned back into normal chats, keeping agent history trustworthy.

### Streaming & Control

- Chat and Code agents stream tokens through the Gemini API with an automatic fallback to blocking requests, so what you see is exactly what gets saved.
- The Send button becomes Stop while the agent works; stopping mid-tool skips pending tool calls safely and keeps model history valid.
- Streamed markdown is re-rendered at most every 50 ms, keeping long replies smooth.

### Markdown & Voice

- New lightweight markdown renderer (`mdrender.py`) shared by both modes, theme-aware and refreshable on appearance changes.
- Every user message carries a source tag for the model: `[TEXT]` (typed) enables markdown; `[VOICE]` (microphone) produces plain conversational text.
- Voice replies are stripped of markdown before display, text-to-speech, and saving, so the transcript matches what you heard.
- Vietnamese translations cover the sidebar, context menus, streaming controls, and all new status messages.

---

**GD Assistant v0.4-BETA** is an in-progress beta release. Feedback and bug reports are welcome as development continues toward v1.0.

## v0.3.1-BETA

### Highlights

- **Fixed the "Speaking..." freeze** — voice replies no longer hang the app when the speech service stalls.
- **Microphone selection** — pick your preferred microphone in Settings or during first-time setup.
- **Revamped first-time setup** — a themed, streamlined wizard now covers models, theme, microphone, and hotkey.

### Fixes

- Voice replies no longer freeze at "Speaking..." forever: Edge-TTS synthesis now times out after 20 seconds and falls back to the offline Windows (SAPI5) voice. Empty audio is rejected and temporary files are always cleaned up.
- The system tray tooltip shows the real app name and version from the app constants instead of a hardcoded "GD Assistant v0.1".

### Voice & Performance

- New **Microphone** dropdown in Settings and in setup: lists each physical microphone once (WASAPI only, fixing the duplicated entries Windows created per audio host API) and switches live without reloading the speech model.
- The Edge-TTS network path is warmed in the background at launch so the first spoken reply starts faster.
- The heavy Faster-Whisper import is deferred until a microphone is actually used, speeding up startup.
- More of the voice flow is localized (loading status, "no speech", and request-failure messages).

### First-Time Setup Wizard

- All wizard windows now use the app's Light/Dark palette, and Light plus English lead the choices as the defaults.
- Step 1 selects the theme with large Dark/Light buttons, matching the language picker — it comes right after the language choice and before the API key.
- Step 2 combines the API key with Chat and Code model dropdowns (including the "use the same model" option).
- Step 3 combines microphone choice with the global hotkey.
- Setup now also saves the code model, model sharing, theme, and microphone preference — previously it only saved the chat model, hotkey, language, and personality.

### Other

- All Code Mode CLI commands now require a leading slash (`/cd`, `/status`, `/model`, `/exit`); anything else is sent to the agent as a prompt.
- `requirements.txt` now lists `faster-whisper` and `edge-tts`, which were missing.
- Code Mode's screenshot tool reports the saved file path back to the agent.

---

**GD Assistant v0.3.1-BETA** is an in-progress beta release. Feedback and bug reports are welcome as development continues toward v1.0.

## v0.3-BETA

### Highlights

- **Light and Dark appearance modes** — choose the look that is easiest on your eyes from Settings.
- **Code Mode** — work with the Coding Agent in the integrated graphical interface or the focused terminal-based CLI.
- **Flexible Gemini models** — Chat and Code Mode can share one Gemini model, or each can use its own model selected in Settings.

### Code Mode

- Switch between **Chat** and **Code** from the main app window.
- Launch Code Mode directly in a terminal when you want a CLI-focused workflow.
- Change the active CLI model during a session with `/model <Gemini model name>`.

### Settings & Interface

- Appearance is now selected with clear Light/Dark radio buttons beside the language choice.
- Model pickers include common Gemini models while still allowing a custom model name.

### Performance & Localization

- Added Vietnamese translations for the new Chat/Code model settings, appearance options, Mode menu, Code GUI, and Code CLI.
- Voice recognition now warms its local Faster-Whisper model in the background and uses the faster `base.en` model by default.
- Reduced the end-of-speech silence delay so requests are sent sooner after speaking.

---

**GD Assistant v0.3-BETA** is an in-progress beta release. Feedback and bug reports are welcome as development continues toward v1.0.
