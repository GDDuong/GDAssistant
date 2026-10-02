"""code_gui.py: Modern graphical interface for GD Assistant's Coding Agent Mode."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any
import tkinter as tk
from tkinter import scrolledtext, filedialog

from gd_core.coding_tools import set_workspace, get_workspace, set_extra_dirs
from gd_core.code_agent import CodeAgentSession
from gd_core.conversations import ConversationStore
from gd_core.translations import get_text
from ui_tk.mdrender import configure_tags, insert_markdown
from ui_tk.sidebar import ConversationSidebar
from ui_tk.themes import get_theme

class CodeAgentPanel(tk.Frame):
    """Embeddable Coding Agent interface for GD Assistant's main window."""

    def __init__(
        self,
        parent: tk.Misc,
        client: Any,
        model: str = "gemini-3.5-flash-lite",
        start_dir: str = ".",
        theme: str = "dark",
        debug: bool = False,
        lang: str = "en",
        conversation_id: str | None = None,
        store: ConversationStore | None = None,
    ) -> None:
        self.colors = get_theme(theme)
        super().__init__(parent, bg=self.colors["background"])
        self.client = client
        self.model = model
        self.debug = debug
        self.lang = lang
        self.store = store or ConversationStore()
        self.conv: dict[str, Any] | None = None
        self.extra_dirs: list[str] = []
        set_workspace(start_dir)
        self.session = CodeAgentSession(
            self.client, model=self.model, on_status=self.on_agent_status, debug=self.debug
        )
        self.is_busy = False
        self.stop_event: threading.Event | None = None
        self.stream_pieces: list[str] = []
        self._stream_render_job: str | None = None
        self._build_ui()
        self._init_conversation(conversation_id)

    def _build_ui(self) -> None:
        color = self.colors

        # ---- LEFT SIDEBAR: saved code projects ----
        self.sidebar = ConversationSidebar(
            self,
            self.store,
            "code",
            color,
            self.lang,
            on_open=self.on_open_project,
            on_new=self.on_new_project,
        )
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)

        # ---- TOP CONTROL BAR ----
        top_bar = tk.Frame(self, bg=color["panel"], padx=10, pady=8)
        top_bar.pack(fill=tk.X, side=tk.TOP)

        tk.Label(top_bar, text=self._text("code_workspace"), bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        self.ws_var = tk.StringVar(value=str(get_workspace()))
        self.ws_entry = tk.Entry(top_bar, textvariable=self.ws_var, bg=color["input"], fg=color["foreground"], insertbackground=color["foreground"], width=42, font=("Consolas", 9))
        self.ws_entry.pack(side=tk.LEFT, padx=(0, 6))

        browse_btn = tk.Button(top_bar, text=self._text("code_browse"), command=self.on_browse_workspace, bg=color["button"], fg=color["foreground"], activebackground=color["button_active"], activeforeground=color["foreground"], relief=tk.FLAT, padx=8)
        browse_btn.pack(side=tk.LEFT, padx=(0, 6))

        ref_btn = tk.Button(top_bar, text=self._text("code_add_ref"), command=self.on_add_ref_dir, bg=color["button"], fg=color["foreground"], activebackground=color["button_active"], activeforeground=color["foreground"], relief=tk.FLAT, padx=8)
        ref_btn.pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(top_bar, text=f"{self._text('code_model')} {self.model}", bg=color["panel"], fg=color["muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 8))

        # ---- REFERENCE DIRECTORIES ROW ----
        self.refs_row = tk.Frame(self, bg=color["panel"])

        # ---- MAIN SPLIT VIEW ----
        self.paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=color["background"], bd=0, sashwidth=5)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 0))

        # LEFT PANE: Chat & Code Transcript
        left_frame = tk.Frame(self.paned, bg=color["background"])
        self.paned.add(left_frame, minsize=580)

        self.transcript = scrolledtext.ScrolledText(
            left_frame,
            wrap=tk.WORD,
            bg=color["background"],
            fg=color["foreground"],
            insertbackground=color["foreground"],
            font=("Consolas", 10),
            padx=12,
            pady=12,
            bd=0,
            highlightthickness=1,
            highlightbackground=color["border"],
            highlightcolor=color["accent"]
        )
        self.transcript.pack(fill=tk.BOTH, expand=True)

        self.transcript.tag_configure("user", foreground=color["user"], font=("Consolas", 10, "bold"))
        self.transcript.tag_configure("agent", foreground=color["foreground"])
        self.transcript.tag_configure("system", foreground=color["muted"], font=("Consolas", 9, "italic"))
        self.transcript.tag_configure("error", foreground=color["error"], font=("Consolas", 10, "bold"))
        configure_tags(self.transcript, color, family="Consolas", size=10)

        # RIGHT PANE: Action Activity Log & Shortcuts
        right_frame = tk.Frame(self.paned, bg=color["panel"], padx=8, pady=8)
        self.paned.add(right_frame, minsize=240)

        tk.Label(right_frame, text=self._text("code_activity_log"), bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 4))

        self.action_log = scrolledtext.ScrolledText(
            right_frame,
            wrap=tk.WORD,
            bg=color["background"],
            fg=color["muted"],
            font=("Consolas", 9),
            height=14,
            bd=0,
            highlightthickness=1,
            highlightbackground=color["border"]
        )
        self.action_log.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        tk.Label(right_frame, text=self._text("code_quick_actions"), bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))

        btn_opts = {"bg": color["button"], "fg": color["foreground"], "activebackground": color["button_active"], "activeforeground": color["foreground"], "relief": tk.FLAT, "pady": 4}
        tk.Button(right_frame, text=self._text("code_run_tests"), command=lambda: self.submit_quick(self._text("code_quick_run_tests_prompt")), **btn_opts).pack(fill=tk.X, pady=2)
        tk.Button(right_frame, text=self._text("code_git_status"), command=lambda: self.submit_quick(self._text("code_quick_git_status_prompt")), **btn_opts).pack(fill=tk.X, pady=2)
        tk.Button(right_frame, text=self._text("code_list_files"), command=lambda: self.submit_quick(self._text("code_quick_list_files_prompt")), **btn_opts).pack(fill=tk.X, pady=2)
        tk.Button(right_frame, text=self._text("code_clear_transcript"), command=self.clear_transcript, **btn_opts).pack(fill=tk.X, pady=2)

        # ---- BOTTOM INPUT BAR ----
        bottom_frame = tk.Frame(self, bg=color["panel"], padx=10, pady=8)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.input_box = tk.Text(
            bottom_frame,
            height=3,
            bg=color["input"],
            fg=color["foreground"],
            insertbackground=color["foreground"],
            font=("Segoe UI", 10),
            padx=8,
            pady=6,
            bd=0,
            highlightthickness=1,
            highlightbackground=color["border"],
            highlightcolor=color["accent"]
        )
        self.input_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self.input_box.bind("<Return>", self.on_return_pressed)

        btn_container = tk.Frame(bottom_frame, bg=color["panel"])
        btn_container.pack(side=tk.RIGHT, fill=tk.Y)

        self.send_btn = tk.Button(
            btn_container,
            text=self._text("code_send"),
            command=self.submit_prompt,
            bg=color["accent"],
            fg="#ffffff",
            activebackground=color["accent_active"],
            activeforeground="#ffffff",
            font=("Segoe UI", 10, "bold"),
            relief=tk.FLAT,
            padx=20,
        )
        self.send_btn.pack(fill=tk.BOTH, expand=True)

        # Status Bar
        self.status_var = tk.StringVar(value=self._text("code_ready"))
        self.status_label = tk.Label(self, textvariable=self.status_var, bg=color["accent"], fg="#ffffff", anchor="w", font=("Segoe UI", 8), padx=8, pady=2)
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM)

    def _text(self, key: str) -> str:
        return get_text(key, self.lang)

    # --------------------------------------------------- conversation flow

    def _init_conversation(self, conversation_id: str | None) -> None:
        if conversation_id:
            conv = self.store.load_conversation(conversation_id)
            if conv is not None:
                self._apply_conversation(conv)
                return
        recent = self.store.list_conversations("code")
        if recent:
            self._apply_conversation(recent[0])
        else:
            self.on_new_project()

    def load_conversation(self, conversation_id: str) -> None:
        if self.is_busy:
            self.status_var.set(self._text("code_busy_wait"))
            return
        conv = self.store.load_conversation(conversation_id)
        if conv is not None and conv.get("type") == "code":
            self._apply_conversation(conv)

    def on_new_project(self) -> None:
        if self.is_busy:
            self.status_var.set(self._text("code_busy_wait"))
            return
        conv = self.store.create_conversation(
            "code",
            title=self._text("sidebar_new_project"),
            workspace=str(get_workspace()),
        )
        self._apply_conversation(conv)

    def on_open_project(self, conversation_id: str | None) -> None:
        if conversation_id is None:
            self.on_new_project()
            return
        self.load_conversation(conversation_id)

    def _apply_conversation(self, conv: dict[str, Any]) -> None:
        self.conv = conv
        self.extra_dirs = [str(path) for path in conv.get("extra_dirs") or []]

        workspace = conv.get("workspace")
        if workspace and Path(workspace).is_dir():
            set_workspace(workspace)
        set_extra_dirs(self.extra_dirs)

        messages = conv.get("messages") or []
        self.session = CodeAgentSession(
            self.client,
            model=self.model,
            on_status=self.on_agent_status,
            debug=self.debug,
            extra_dirs=self.extra_dirs,
            seed_messages=messages,
        )
        self.ws_var.set(str(get_workspace()))
        self._render_refs()

        self.transcript.configure(state=tk.NORMAL)
        self.transcript.delete("1.0", tk.END)
        self.transcript.configure(state=tk.DISABLED)
        for message in messages:
            if message.get("role") == "user":
                self._append_message(self._text("code_you"), str(message.get("content", "")), "user")
            else:
                self._append_markdown_message(self._text("code_agent_name"), str(message.get("content", "")), "agent")
        if not messages:
            self._append_message(
                self._text("code_system"),
                self._text("code_welcome").format(workspace=get_workspace(), model=self.model),
                "system",
            )
        self.sidebar.set_current(conv["id"])

    def _persist_message(self, role: str, content: str) -> None:
        if self.conv is None:
            return
        self.store.append_message(self.conv["id"], role, content)
        if role == "user":
            self.sidebar.set_current(self.conv["id"])

    # ------------------------------------------------------ reference dirs

    def on_add_ref_dir(self) -> None:
        if self.is_busy:
            self.status_var.set(self._text("code_busy_wait"))
            return
        chosen = filedialog.askdirectory(
            initialdir=str(get_workspace()), title=self._text("code_select_workspace")
        )
        if not chosen:
            return
        resolved = str(Path(chosen).resolve())
        if resolved in self.extra_dirs:
            return
        self.extra_dirs.append(resolved)
        self._commit_refs()

    def _remove_ref_dir(self, path: str) -> None:
        if self.is_busy:
            self.status_var.set(self._text("code_busy_wait"))
            return
        if path in self.extra_dirs:
            self.extra_dirs.remove(path)
            self._commit_refs()

    def _commit_refs(self) -> None:
        set_extra_dirs(self.extra_dirs)
        self.session.rebuild_config()
        if self.conv is not None:
            self.conv["extra_dirs"] = list(self.extra_dirs)
            self.store.save_conversation(self.conv)
        self._render_refs()
        self._append_log(f"{self._text('code_refs_label')} {self.extra_dirs}")

    def _render_refs(self) -> None:
        for child in self.refs_row.winfo_children():
            child.destroy()
        if not self.extra_dirs:
            self.refs_row.pack_forget()
            return
        tk.Label(
            self.refs_row,
            text=self._text("code_refs_label"),
            bg=self.colors["panel"],
            fg=self.colors["muted"],
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT, padx=(10, 6), pady=2)
        for path in self.extra_dirs:
            chip = tk.Frame(self.refs_row, bg=self.colors["input"])
            chip.pack(side=tk.LEFT, padx=(0, 4), pady=2)
            tk.Label(
                chip,
                text=path,
                bg=self.colors["input"],
                fg=self.colors["muted"],
                font=("Consolas", 8),
            ).pack(side=tk.LEFT, padx=(6, 2), pady=1)
            tk.Button(
                chip,
                text="×",
                command=lambda p=path: self._remove_ref_dir(p),
                relief=tk.FLAT,
                bd=0,
                bg=self.colors["input"],
                fg=self.colors["foreground"],
                activebackground=self.colors["button_active"],
                font=("Segoe UI", 8),
            ).pack(side=tk.LEFT, padx=(0, 4))
        self.refs_row.pack(fill=tk.X, side=tk.TOP, before=self.paned)

    # --------------------------------------------------------- transcript

    def _append_message(self, speaker: str, text: str, tag: str = "agent") -> None:
        self.transcript.configure(state=tk.NORMAL)
        if speaker:
            self.transcript.insert(tk.END, f"{speaker}:\n", tag)
        self.transcript.insert(tk.END, f"{text}\n\n", tag)
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _append_markdown_message(self, speaker: str, text: str, tag: str = "agent") -> None:
        self.transcript.configure(state=tk.NORMAL)
        if speaker:
            self.transcript.insert(tk.END, f"{speaker}:\n", tag)
        insert_markdown(self.transcript, text, base_tag=tag)
        self.transcript.insert(tk.END, "\n\n")
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _begin_stream_block(self) -> None:
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.insert(tk.END, f"{self._text('code_agent_name')}:\n", "agent")
        self.transcript.mark_set("stream_start", "end-1c")
        self.transcript.mark_gravity("stream_start", tk.LEFT)
        self.transcript.configure(state=tk.DISABLED)

    def _end_stream_block(self) -> None:
        if "stream_start" in self.transcript.mark_names():
            self.transcript.mark_unset("stream_start")

    def _render_stream_text(self) -> None:
        self._stream_render_job = None
        if "stream_start" not in self.transcript.mark_names():
            return
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.delete("stream_start", "end-1c")
        insert_markdown(self.transcript, "".join(self.stream_pieces), base_tag="agent")
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _schedule_stream_render(self) -> None:
        if self._stream_render_job is None:
            self._stream_render_job = self.after(50, self._render_stream_text)

    def _append_log(self, text: str) -> None:
        self.action_log.configure(state=tk.NORMAL)
        self.action_log.insert(tk.END, f"{text}\n")
        self.action_log.configure(state=tk.DISABLED)
        self.action_log.see(tk.END)

    def on_agent_status(self, message: str) -> None:
        self.after(0, lambda: self._append_log(message))
        self.after(0, lambda: self.status_var.set(message))

    def on_browse_workspace(self) -> None:
        if self.is_busy:
            self.status_var.set(self._text("code_busy_wait"))
            return
        chosen = filedialog.askdirectory(initialdir=str(get_workspace()), title=self._text("code_select_workspace"))
        if chosen and set_workspace(chosen):
            self.ws_var.set(str(get_workspace()))
            if self.conv is not None:
                self.conv["workspace"] = str(get_workspace())
                self.store.save_conversation(self.conv)
            self.session.rebuild_config()
            self._append_message(self._text("code_system"), self._text("code_workspace_changed").format(workspace=get_workspace()), "system")

    def on_return_pressed(self, event: Any) -> str | None:
        if not (event.state & 0x0001):  # Shift key is not pressed
            self.submit_prompt()
            return "break"
        return None

    def submit_quick(self, prompt: str) -> None:
        if self.is_busy:
            return
        self.input_box.delete("1.0", tk.END)
        self.input_box.insert("1.0", prompt)
        self.submit_prompt()

    def stop_agent(self) -> None:
        if self.stop_event is not None:
            self.stop_event.set()
        self.status_var.set(self._text("status_stopping"))

    def submit_prompt(self) -> None:
        if self.is_busy:
            return
        prompt = self.input_box.get("1.0", tk.END).strip()
        if not prompt:
            return

        self.input_box.delete("1.0", tk.END)
        self._append_message(self._text("code_you"), prompt, "user")
        self._persist_message("user", prompt)

        self.is_busy = True
        self.stop_event = threading.Event()
        self.stream_pieces.clear()
        self.send_btn.configure(
            text=self._text("btn_stop"),
            command=self.stop_agent,
            bg=self.colors["error"],
            activebackground=self.colors["error"],
        )
        self.status_var.set(self._text("code_agent_working"))
        self.status_label.configure(bg=self.colors["working"])
        self._begin_stream_block()

        streamed = False

        def on_text(piece: str) -> None:
            nonlocal streamed
            streamed = True
            self.stream_pieces.append(piece)
            self.after(0, self._schedule_stream_render)

        def run_thread():
            nonlocal streamed
            had_error = False
            try:
                response = self.session.execute_turn(
                    prompt, on_text=on_text, stop_event=self.stop_event
                )
            except Exception as e:
                response = self._text("code_execution_error").format(error=e)
                had_error = True

            def finish():
                self.stop_event = None
                if self._stream_render_job is not None:
                    self.after_cancel(self._stream_render_job)
                self._render_stream_text()
                self.transcript.configure(state=tk.NORMAL)
                if not streamed or had_error:
                    if had_error:
                        self.transcript.insert(tk.END, response, "agent")
                    else:
                        insert_markdown(self.transcript, response, base_tag="agent")
                self.transcript.insert(tk.END, "\n\n")
                self.transcript.configure(state=tk.DISABLED)
                self.transcript.see(tk.END)
                self._end_stream_block()
                if response:
                    self._persist_message("assistant", response)
                self.is_busy = False
                self.send_btn.configure(
                    text=self._text("code_send"),
                    command=self.submit_prompt,
                    bg=self.colors["accent"],
                    activebackground=self.colors["accent_active"],
                )
                self.status_var.set(self._text("code_ready"))
                self.status_label.configure(bg=self.colors["accent"])
                self.input_box.focus_set()

            self.after(0, finish)

        threading.Thread(target=run_thread, daemon=True).start()

    def clear_transcript(self) -> None:
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.delete("1.0", tk.END)
        self.transcript.configure(state=tk.DISABLED)


class CodeAgentGUI:
    """Standalone wrapper retained for the --codegui command-line mode."""

    def __init__(
        self,
        client: Any,
        model: str = "gemini-3.5-flash-lite",
        start_dir: str = ".",
        theme: str = "dark",
        debug: bool = False,
        lang: str = "en",
    ) -> None:
        self.root = tk.Tk()
        self.root.title(f"GD Assistant :: {get_text('mode_code', lang)}")
        self.root.geometry("1080x700")
        self.root.minsize(880, 520)
        self.root.configure(bg=get_theme(theme)["background"])
        self.panel = CodeAgentPanel(self.root, client, model=model, start_dir=start_dir, theme=theme, debug=debug, lang=lang)
        self.panel.pack(fill=tk.BOTH, expand=True)

    def run(self) -> None:
        self.root.mainloop()

def launch_coding_gui(
    client: Any,
    model: str = "gemini-3.5-flash-lite",
    start_dir: str = ".",
    theme: str = "dark",
    debug: bool = False,
    lang: str = "en",
) -> None:
    app = CodeAgentGUI(client, model=model, start_dir=start_dir, theme=theme, debug=debug, lang=lang)
    app.run()
