# Changelog

All notable changes to GD Assistant are documented here.

## v0.5.1-BETA

### Highlights

- **File attachments in Chat and Code Mode** — a **+** button now sits left of the text box in both modes. Pick one or more files; they are shown as a pending list you can clear before sending, and go with your next message.

### File Attachments

- Readable text files (code, logs, markdown, config...) are inlined straight into the message in a fenced block, capped at 50k characters per file, so the assistant quotes and edits the real content — and attachments stay visible when the conversation is reloaded later.
- Images (PNG/JPG/GIF/WebP), PDFs, and other binary files are sent to Gemini as native attachments on the same turn, so the model can actually see them.
- Clicking the pending-files note clears the whole queue before sending; sending a message auto-clears it.
- You can now send a message with only attachments and no text.
- New shared helper (`gd_core/attachments.py`) keeps the core UI-free: both modes build the same request text and inline-data parts through it, and the Coding Agent's turn runner accepts extra attachment parts.

---

## v0.5-BETA

### Highlights

- **Wake word ("summoning sentence")** — an optional always-listening mode hears a phrase like "hey assistant" and starts a voice conversation hands-free, no button or hotkey needed.

### Voice & Wake Word

- New always-on listener (`wakeword.py`): continuous microphone monitoring gated by an energy voice-activity detector, so the shared `base.en` speech model only transcribes short speech clips and stays easy on the CPU — no second model is loaded.
- Tolerant phrase matching forgives common mishearings like "Pay Assistant" — exact phrase, most words heard, or a fuzzy keyword match in short clips — and the decoder is primed with your phrase so it hears it correctly. Only short clips can trigger on the keyword alone, so ordinary sentences that merely mention "assistant" stay asleep. A short cooldown prevents double triggers.
- The listener pauses while the assistant records or speaks a reply — it never hears its own voice — and resumes automatically, recalibrating the room noise level afterward.
- New Settings controls: an **Enable wake word (always listening)** checkbox and a **Summoning sentence** field (default `hey assistant`); saving restarts the listener with the new settings.
- Waking brings the chat window forward (even from the system tray) and starts the same voice flow as the mic button. Wake word applies to Chat Mode; Code Mode ignores wake events.
- Vietnamese translations cover the new Settings controls.

### Fixes

- The wake listener reacts noticeably faster: a more sensitive voice-activity threshold catches soft speech sooner, and a 0.5 s end-of-speech window replaces the old 0.8 s one, so a summoning phrase is no longer split into two detections before it triggers.
- The listener logs only meaningful events (startup, calibration, detection, errors) instead of echoing every sound bite it hears to the console.
- Settings: fixed the Save button being squished to a thin line at the bottom of the dialog — the window now sizes itself to its content instead of using a hardcoded height.

### Other

- Added `ROADMAP.md` — the public development roadmap, from v0.4.x housekeeping through the v1.0 Qt migration.

---

**GD Assistant v0.5-BETA** is an in-progress beta release. Feedback and bug reports are welcome as development continues toward v1.0.

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
