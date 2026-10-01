"""code_gui.py: Modern graphical interface for GD Assistant's Coding Agent Mode."""

from __future__ import annotations

import os
import threading
from typing import Any
import tkinter as tk
from tkinter import scrolledtext, filedialog

from coding_tools import set_workspace, get_workspace
from code_agent import CodeAgentSession
from themes import get_theme
from translations import get_text

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
    ) -> None:
        self.colors = get_theme(theme)
        super().__init__(parent, bg=self.colors["background"])
        self.client = client
        self.model = model
        self.debug = debug
        self.lang = lang
        set_workspace(start_dir)
        self.session = CodeAgentSession(
            self.client, model=self.model, on_status=self.on_agent_status, debug=self.debug
        )
        self.is_busy = False
        self._build_ui()

    def _build_ui(self) -> None:
        color = self.colors
        # ---- TOP CONTROL BAR ----
        top_bar = tk.Frame(self, bg=color["panel"], padx=10, pady=8)
        top_bar.pack(fill=tk.X, side=tk.TOP)

        tk.Label(top_bar, text=self._text("code_workspace"), bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 6))

        self.ws_var = tk.StringVar(value=str(get_workspace()))
        self.ws_entry = tk.Entry(top_bar, textvariable=self.ws_var, bg=color["input"], fg=color["foreground"], insertbackground=color["foreground"], width=42, font=("Consolas", 9))
        self.ws_entry.pack(side=tk.LEFT, padx=(0, 6))

        browse_btn = tk.Button(top_bar, text=self._text("code_browse"), command=self.on_browse_workspace, bg=color["button"], fg=color["foreground"], activebackground=color["button_active"], activeforeground=color["foreground"], relief=tk.FLAT, padx=8)
        browse_btn.pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(top_bar, text=f"{self._text('code_model')} {self.model}", bg=color["panel"], fg=color["muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(0, 8))

        # ---- MAIN SPLIT VIEW ----
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=color["background"], bd=0, sashwidth=5)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 0))

        # LEFT PANE: Chat & Code Transcript
        left_frame = tk.Frame(paned, bg=color["background"])
        paned.add(left_frame, minsize=580)

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

        # RIGHT PANE: Action Activity Log & Shortcuts
        right_frame = tk.Frame(paned, bg=color["panel"], padx=8, pady=8)
        paned.add(right_frame, minsize=240)

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

        self._append_message(self._text("code_system"), self._text("code_welcome").format(workspace=get_workspace(), model=self.model), "system")

    def _text(self, key: str) -> str:
        return get_text(key, self.lang)

    def _append_message(self, speaker: str, text: str, tag: str = "agent") -> None:
        self.transcript.configure(state=tk.NORMAL)
        if speaker:
            self.transcript.insert(tk.END, f"{speaker}:\n", tag)
        self.transcript.insert(tk.END, f"{text}\n\n", tag)
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _append_log(self, text: str) -> None:
        self.action_log.configure(state=tk.NORMAL)
        self.action_log.insert(tk.END, f"{text}\n")
        self.action_log.configure(state=tk.DISABLED)
        self.action_log.see(tk.END)

    def on_agent_status(self, message: str) -> None:
        self.after(0, lambda: self._append_log(message))
        self.after(0, lambda: self.status_var.set(message))

    def on_browse_workspace(self) -> None:
        chosen = filedialog.askdirectory(initialdir=str(get_workspace()), title=self._text("code_select_workspace"))
        if chosen and set_workspace(chosen):
            self.ws_var.set(str(get_workspace()))
            self._append_message(self._text("code_system"), self._text("code_workspace_changed").format(workspace=get_workspace()), "system")
            self.session = CodeAgentSession(self.client, model=self.model, on_status=self.on_agent_status, debug=self.debug)

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

    def submit_prompt(self) -> None:
        if self.is_busy:
            return
        prompt = self.input_box.get("1.0", tk.END).strip()
        if not prompt:
            return

        self.input_box.delete("1.0", tk.END)
        self._append_message(self._text("code_you"), prompt, "user")

        self.is_busy = True
        self.send_btn.configure(state=tk.DISABLED, text=self._text("code_working"))
        self.status_var.set(self._text("code_agent_working"))
        self.status_label.configure(bg=self.colors["working"])

        def run_thread():
            try:
                response = self.session.execute_turn(prompt)
            except Exception as e:
                response = self._text("code_execution_error").format(error=e)

            def finish():
                self._append_message(self._text("code_agent_name"), response, "agent")
                self.is_busy = False
                self.send_btn.configure(state=tk.NORMAL, text=self._text("code_send"))
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
        self.root.geometry("1040x700")
        self.root.minsize(850, 520)
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
