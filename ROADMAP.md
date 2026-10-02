# GD Assistant — Roadmap: v0.4.x-BETA → v1.0

> Written for a coding agent (Qoder) and the project owner (Dương).
> Some details below are **assumptions made without reading the full source** and are marked ⚠️ *verify*. Check them against the real code before acting.

---

## 1. Product vision

GD Assistant started as a **Siri-style AI assistant for PC** (Windows first). Over v0.3–v0.4 it also grew into a Gemini-style chat app with a Code Mode. For v1.0 the product is refocused:

- **Primary identity: a voice-first desktop assistant** that wakes instantly, reacts visually to the user's voice, and reliably *does things* on the PC.
- **Secondary: Chat window** (history, long conversations) and **Code Mode** (workspace coding agent). These stay, but must not slow down or distract from the assistant experience.
- **v1.0 is also the big UI overhaul**: migrate the UI from Tk to **Qt (PySide6)**.

**Architecture principle (keep!):** Gemini is the *brain*; the local app is the *hands*. Gemini only requests registered tools; the app validates, confirms risky actions, executes, and reports the real SUCCESS/FAILURE back before Gemini replies.

## 2. Current state (v0.4-BETA)

- Windows only, Python 3.10+, Tk UI everywhere (Chat, Code GUI, Settings, setup wizard, tray). ⚠️ *verify*
- Gemini default model: `gemini-3.5-flash-lite`; separate Chat/Code model option.
- Voice in: Faster-Whisper `base.en` (English only, local CPU). Voice out: Edge TTS → SAPI5 (`pyttsx3`) fallback.
- Local tools: `open_app`, `close_app`, `open_file`, `get_system_stats`, `search_files`, `open_url`, `get_current_time`, `remember_info`/`forget_info`/`get_all_memory`, `take_screenshot`, `click_at`, `type_text`, `press_key`, `scroll_screen`.
- Features: chat history sidebar, token streaming + Stop, markdown renderer (`mdrender.py`), `[TEXT]`/`[VOICE]` source tags, Chat→Code project conversion, Vietnamese + English UI.
- Local data in `%APPDATA%\GD Assistant\` (`api.json` key, `config.json`, `memory.json`, `history\`).
- Release artifact: one-file PyInstaller `.exe`, ~**125 MB**.
- Repo files (flat): `main.py`, `code_agent.py`, `code_cli.py`, `code_gui.py`, `coding_tools.py`, `conversations.py`, `local_tools.py`, `mdrender.py`, `sidebar.py`, `themes.py`, `translations.py`, `tray.py`, `voice.py`, `CHANGELOG.md`, `GD_Assistant-v0.4-BETA.spec`.

## 3. Rules for the coding agent

1. **Never weaken the security model.** Tools stay explicitly registered; risky tools (`close_app`, `click_at`, `type_text`, `press_key`, shell commands in Code Mode) keep or gain confirmation.
2. **Never commit secrets** (`api.json`, API keys). Keep `.gitignore` correct.
3. **Work on branches.** Small, reviewable commits. Qt migration lives on a `qt` branch; Tk fixes continue on `main`.
4. **Don't touch the Gemini default model** or prompts unless the task says so.
5. **Keep the core UI-free**: agent, tools, memory, conversations, voice engine must not import Tk or Qt.
6. **Add/keep tests** for tools and core logic. Don't remove existing tests.
7. **Update `CHANGELOG.md`** with every release, in the existing style (Highlights / Fixes / Other).
8. **Keep every user-facing string in `translations.py`** (English + Vietnamese).
9. **Prefer PySide6 (LGPL), not PyQt6.** Import only `QtCore`, `QtGui`, `QtWidgets` (+ `QtMultimedia` only if needed). Never ship QtWebEngine.
10. **When unsure about intent, ask the owner** instead of guessing.

---

## 4. Milestones

### v0.4.x-BETA — Stabilize & housekeeping (on `main`, Tk)

Goal: small, safe releases; clean repo; no new big features.

- [ ] Mark the newest release as **Latest** on GitHub (untick pre-release if desired).
- [ ] Fix release metadata: `v0.1.1-BETA` tag points at the same commit as `v0.1-BETA`; title date says 2026-06-14 (should be Sep 14). Retag or annotate.
- [ ] Reconcile `CHANGELOG.md` with GitHub release notes (v0.3.1 setup wizard step order differs).
- [ ] README: add a "Download" section linking to Releases; add description + topics on the repo; add screenshots/GIF.
- [ ] Add `.idea/` to `.gitignore` and remove it from the repo.
- [ ] **Move the API key to Windows Credential Manager** via `keyring` (service `"GD Assistant"`, user `"gemini_api_key"`). Keep `GEMINI_API_KEY` env var as top priority. On startup, if `api.json` has a key: migrate it to the vault, then delete the file. Add `keyring.backends.Windows` as a PyInstaller hidden import and test the built `.exe`.
- [ ] Use `platformdirs` instead of hard-coded `%APPDATA%` paths (keep the same folder on Windows so existing users aren't broken).
- [ ] Audit `.exe` size (see §6) and record what is large.
- [ ] Hotfix any bugs found in v0.4 (voice has needed the most patches: v0.1.1, v0.2.1, v0.3.1).

**Done when:** v0.4.x tagged, release marked Latest, key no longer stored in plaintext, size audit written down.

### v0.5-BETA — Foundations for the rewrite (on `main` where possible)

Goal: make the Qt migration and cross-platform support cheap.

- [ ] **Separate brains from looks.** Move UI-free logic into a package (suggested: `gd_core/` with agent, tools, memory, conversations, voice engine, config). UI modules (`ui_tk/` for now) only import from core, never the reverse. ⚠️ *verify how tangled the current modules are first; report findings before large moves.*
- [ ] **Event/callback interface** between core and UI (state changes, streamed tokens, tool results, audio level). This same interface will feed the Qt UI and the overlay.
- [ ] **Platform adapter layer:** `platform/windows.py` (app launch/close, hotkey, volume, notifications, etc.) behind a common interface; stubs for `macos.py`/`linux.py` later.
- [ ] Voice engine exposes a **live mic level** (RMS, ~30–60 Hz) and discrete states: `idle / listening / thinking / speaking`.
- [ ] Test suite runs in CI (GitHub Actions) on every push; tools and core covered.
- [ ] Create the `qt` branch.

**Done when:** core runs headless (CLI/terminal mode works with zero UI imports), tests pass in CI.

### v0.6-BETA — Qt overlay prototype (on `qt` branch)

Goal: prove the Siri-style experience before porting everything.

- [ ] PySide6 setup; PyInstaller `.spec` excludes unused Qt modules.
- [ ] **Overlay window:** frameless, transparent, always-on-top, top-center, does **not** steal focus (`WS_EX_NOACTIVATE`/tool-window), click-through when idle.
- [ ] Summoned by the existing **global hotkey**; dismissed on Esc / timeout / after result.
- [ ] Visual states: `idle` (hidden) → `listening` (pill expands, orb/glow reacts to mic level) → `thinking` (slow swirl) → `speaking` (pulses) → `result` (short text/card, fades out).
- [ ] Mic level smoothing: fast attack, slow release; optional 3–5 frequency bands (FFT).
- [ ] "Open in chat" button on the result opens the full chat window with that exchange.
- [ ] Respect Light/Dark theme and a "reduce motion" setting.
- [ ] Target: smooth ~60 fps, low CPU when idle.

Visual reference (reported, not a spec): iOS 27 Siri — pill-shaped animation with a thin edge glow, "Search or Ask" bar with glowing cursor, small context cards, colorful reflective orb while listening, swipe-down to chat.

**Done when:** pressing the hotkey shows a transparent overlay whose orb visibly follows the user's voice, and the answer appears and fades without stealing focus from the foreground app.

### v0.7-BETA — Port Chat to Qt

- [ ] Qt main window: conversation view, input, voice button, Mode menu, tray icon (`QSystemTrayIcon`).
- [ ] Port the chat history sidebar (new / rename / archive / unarchive / delete, collapsible).
- [ ] Port streaming + Stop button; markdown rendering (evaluate `QTextBrowser`/`QTextDocument` markdown support vs keeping `mdrender.py` logic).
- [ ] Port `themes.py` to Qt stylesheets (QSS), keep Light/Dark and live switching.
- [ ] Keep `[TEXT]` / `[VOICE]` behavior (markdown for typed, plain for voice).

**Done when:** Chat Mode is feature-equal with v0.4 on Qt.

### v0.8-BETA — Port Settings, wizard & Code Mode; harden Code Mode

- [ ] Port Settings and the first-time setup wizard (theme, API key, models, microphone, hotkey, language, personality).
- [ ] Port Code Mode GUI (workspace picker, reference dirs, chat→project conversion).
- [ ] Code Mode safety upgrades:
  - [ ] **Diff preview with approve/reject** before file edits, plus **undo** of the last change set.
  - [ ] **Permission levels:** read-only / ask-before-running / auto-approve, with a command **denylist**.
  - [ ] Show command output in the UI with a **kill** button.
  - [ ] Optional project instructions file (e.g. `AGENTS.md`) read at session start.
  - [ ] Git-aware: show status; optional auto-branch for agent work.
- [ ] Remove the old Tk UI from the `qt` branch once parity is reached.

**Done when:** every v0.4 feature exists in Qt and Tk code is gone.

### v0.9-BETA — Make it a real assistant

- [ ] **Wake word** ("Hey GD", configurable) using an offline engine (e.g. openWakeWord or Porcupine — check licensing); hotkey remains as fallback; clear on/off privacy indicator.
- [ ] **System-control tools** (each registered, with confirmation where disruptive): volume, mute, brightness, media play/pause/next, lock screen, dark-mode toggle, Wi-Fi/Bluetooth toggles where feasible.
- [ ] **Timers, alarms, reminders** that fire as Windows notifications even if the window is closed.
- [ ] **Clipboard actions** ("summarize what I copied", "translate this").
- [ ] **"What's on my screen?"** as a one-step voice command using the existing screenshot tool.
- [ ] **Routines / voice macros** (e.g. "gaming mode" = open apps, set volume, mute notifications), user-defined.
- [ ] **Result cards** in the overlay (weather, time, system stats, timers, search answers with sources).
- [ ] **Vietnamese voice:** multilingual Whisper model (download on first run, don't bundle) + Vietnamese-capable TTS voice; auto/choose language.
- [ ] **Speaking-reactive animation** (derive an amplitude envelope from TTS audio, synced to playback).
- [ ] Tools-activity log: "what did the assistant just do?" viewable in UI.
- [ ] Optional opt-in morning briefing.

**Done when:** a user can say "Hey GD, set a 10 minute timer and lower the volume" with no clicks and see/hear correct results.

### v1.0-RC → v1.0

- [ ] **Performance:** hotkey → listening < ~300 ms; speech end → first spoken word target ≈ 2 s on a typical PC; idle CPU/RAM budget documented.
- [ ] **Security review:** all desktop-control tools (`click_at`, `type_text`, `press_key`) require confirmation or an explicit allowlist; treat screenshot/web content as untrusted (prompt-injection awareness); document the threat model in the README.
- [ ] **Installer:** switch from one-file `.exe` to a folder build + installer (e.g. Inno Setup) to cut startup time and antivirus false positives; consider code signing.
- [ ] **Auto-update check** against GitHub Releases.
- [ ] **Crash/log export** button for bug reports.
- [ ] Accessibility pass (keyboard navigation, contrast, reduce motion).
- [ ] Docs: README rewrite for the assistant-first identity, screenshots/GIFs, install guide, FAQ, privacy notes (what goes to Gemini / Edge TTS, what stays local).
- [ ] Full Vietnamese/English string audit.
- [ ] Remove the "BETA" label; tag **v1.0**; mark as Latest.

---

## 5. Post-1.0 ideas (not in scope now)

- **macOS / Linux:** add `platform/macos.py` and `platform/linux.py`; `keyring` and `platformdirs` already work cross-platform. macOS needs Accessibility + Screen Recording permissions and signing/notarization. Linux Wayland restricts global hotkeys, input synthesis and overlays (X11 is easier).
- **Mobile:** realistically a *separate* chat/voice client (Flutter/Kotlin/React Native), possibly remote-controlling the PC; desktop-style tools aren't available on phones.
- Local models (Ollama) for offline/private mode.
- Optional connectors (Google Calendar, Gmail, Drive).
- Plugin/tool SDK for community tools.

## 5a. Post-1.0 — Code Mode ideas

Code Mode is the riskiest feature (it edits files and runs commands) and the one that pulled the project away from the assistant-first goal. Everything here is **after v1.0**, apart from the items already listed in v0.8 (diff preview, undo, permission levels, command output + kill, project instructions file, Git awareness).

**Rule:** don't start a Code Mode feature until the assistant feature it competes with has shipped. Alternate: one block of work on Code Mode, then one block on the overlay/wake word/assistant tools.

**Suggested order**

1. **Safety & trust**
   - [ ] **Checkpoints:** snapshot the workspace before large agent runs; one-click rollback.
   - [ ] **Secret scanner:** block the agent from reading/writing `.env`, `api.json`, and key-like strings; warn before commits that contain them.
   - [ ] **Audit log:** replayable list of every file touched and every command run.
   - [ ] **Sandboxed command execution** (temp copy or container) for risky commands.
2. **Smarter agent**
   - [ ] **Plan mode:** agent proposes a step list; user approves/edits; then it executes.
   - [ ] **Auto-test loop:** run tests after edits, read failures, retry with a hard max-attempts limit.
   - [ ] **Context controls:** pin/exclude files; show context-window usage; auto-summarize long sessions.
   - [ ] **Per-task model choice** (fast model for edits, stronger model for planning).
3. **Git & dev workflow**
   - [ ] **Git panel:** stage, commit with a generated message, auto-branch per task, draft a PR description.
   - [ ] Integrated terminal / test runner panel.
   - [ ] Code search and symbol navigation so the agent doesn't have to read whole files.
4. **Voice crossover** (fits the assistant identity — prioritize if only one more is added)
   - [ ] Voice commands in Code Mode ("run the tests", "commit that", "undo the last change"), always routed through the same confirmation rules.
5. **Extensibility**
   - [ ] **MCP support** so Code Mode can use external tools.
   - [ ] Project templates / quick starts (e.g. "new Python CLI", "new Qt app").

**Constraints for any of the above:** keep the permission levels and command denylist from v0.8; never auto-approve anything that deletes files, touches secrets, or runs network/installer commands; every new capability needs tests and a CHANGELOG entry.

---

## 6. Build-size notes (v0.4 `.exe` ≈ 125 MB)

Don't assume Tk is the cause. Likely contributors (⚠️ *verify with an actual analysis*): CTranslate2/Faster-Whisper runtime, numpy, audio libraries, bundled models. Qt will *add* roughly tens of MB.

- Run a size analysis (e.g. inspect the PyInstaller `build/` output) before and after the Qt migration and record the numbers.
- Exclude unused Qt modules and unused stdlib/third-party packages in the `.spec`.
- **Don't bundle Whisper models**; download on first run into the data folder.
- Prefer a folder build + installer for v1.0.

## 7. Risks & decisions to revisit

| Risk | Mitigation |
|------|-----------|
| Qt rewrite drags on and blocks fixes | Keep `main` (Tk) releasable; separate `qt` branch; merge `main` into `qt` regularly |
| Scope creep (Code Mode vs assistant) | Assistant features take priority from v0.6 onward; Code Mode hardening only what's listed |
| Overlay focus-stealing / input issues on Windows | Prototype early (v0.6); test with games and fullscreen apps |
| Wake word false triggers / privacy worries | Offline engine, visible indicator, adjustable sensitivity, easy off switch |
| Larger exe / antivirus flags | Folder build + installer, optional signing |
| Desktop-control tools abused via prompt injection | Confirmation + allowlist, untrusted-content handling |

## 8. Suggested first tasks for Qoder

1. Read the repo and report: module dependency map, which modules import Tk, and how coupled core logic is to the UI.
2. Run a PyInstaller size analysis of the v0.4 build and summarize the biggest contributors.
3. Implement the `keyring` migration for the API key (v0.4.x).
4. Propose the `gd_core/` package structure and the core↔UI event interface (v0.5) **as a plan for review before moving files.**
