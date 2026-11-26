"""Small stdlib tooltips for Tk widgets and notebook tabs."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable


class Tooltip:
    def __init__(self, widget: tk.Widget, text: Callable[[], str] | str, delay: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self.job: str | None = None
        self.window: tk.Toplevel | None = None
        self._pointer: tuple[int, int] | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None) -> None:
        self._hide()
        self.job = self.widget.after(self.delay, self._show)

    def _show(self) -> None:
        self.job = None
        text = self.text() if callable(self.text) else self.text
        if not text:
            return
        try:
            if self._pointer is not None:
                x, y = self._pointer
                x += 12
                y += 18
            else:
                x = self.widget.winfo_rootx() + 12
                y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.geometry(f"+{x}+{y}")
        tk.Label(
            self.window, text=text, justify=tk.LEFT, bg="#1f1f1f", fg="#ffffff",
            font=("Segoe UI", 9), padx=8, pady=5, wraplength=360,
        ).pack()

    def _hide(self, _event=None) -> None:
        if self.job is not None:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


class NotebookTooltips:
    def __init__(self, notebook: ttk.Notebook, descriptions: list[str]) -> None:
        self.notebook = notebook
        self.descriptions = descriptions
        self.tooltip = Tooltip(notebook, self._text)
        notebook.bind("<Motion>", self._motion, add="+")

    def _motion(self, event: tk.Event) -> None:
        try:
            index = int(self.notebook.identify(event.x, event.y))
        except (TypeError, ValueError, tk.TclError):
            index = -1
        if index < 0 or index >= len(self.descriptions):
            self.tooltip._hide()
            return
        self._index = index
        self.tooltip._pointer = (event.x_root, event.y_root)
        self.tooltip._schedule()

    def _text(self) -> str:
        index = getattr(self, "_index", self.notebook.index(self.notebook.select()))
        return self.descriptions[index] if 0 <= index < len(self.descriptions) else ""
