"""Chip strip showing the files queued as message attachments."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

MAX_VISIBLE_CHIPS = 5
MAX_NAME_CHARS = 26


def _shorten(name: str) -> str:
    if len(name) <= MAX_NAME_CHARS:
        return name
    return name[: MAX_NAME_CHARS - 9] + "…" + name[-8:]


class AttachStrip(tk.Frame):
    """One pill per queued file; each pill removes its own file on ✕."""

    def __init__(
        self,
        parent: tk.Misc,
        colors: dict[str, str],
        clear_text: str,
        on_remove,
        on_clear,
    ) -> None:
        super().__init__(parent, bg=colors["background"])
        self._colors = colors
        self._clear_text = clear_text
        self._on_remove = on_remove
        self._on_clear = on_clear
        self._paths: list[Path] = []

    def update_palette(self, colors: dict[str, str]) -> None:
        self._colors = colors
        self.configure(bg=colors["background"])
        self.refresh(self._paths)

    def refresh(self, paths: list[Path]) -> None:
        self._paths = list(paths)
        for child in self.winfo_children():
            child.destroy()
        visible = paths[:MAX_VISIBLE_CHIPS]
        hidden = len(paths) - len(visible)
        for index, path in enumerate(visible):
            self._add_chip(index, path)
        if hidden:
            tk.Label(
                self,
                text=f"+{hidden}",
                bg=self._colors["background"],
                fg=self._colors["muted"],
                font=("Segoe UI", 8),
            ).pack(side=tk.LEFT, padx=(0, 6))
        clear = tk.Label(
            self,
            text=self._clear_text,
            bg=self._colors["background"],
            fg=self._colors["muted"],
            font=("Segoe UI", 8),
            cursor="hand2",
        )
        clear.bind("<Button-1>", lambda _event: self._on_clear())
        clear.bind("<Enter>", lambda _event: clear.configure(fg=self._colors["foreground"]))
        clear.bind("<Leave>", lambda _event: clear.configure(fg=self._colors["muted"]))
        clear.pack(side=tk.LEFT)

    def _add_chip(self, index: int, path: Path) -> None:
        colors = self._colors
        chip = tk.Frame(
            self,
            bg=colors["input"],
            highlightbackground=colors["border"],
            highlightcolor=colors["accent"],
            highlightthickness=1,
            padx=6,
            pady=2,
        )
        tk.Label(
            chip,
            text=_shorten(path.name),
            bg=colors["input"],
            fg=colors["foreground"],
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)
        close = tk.Label(
            chip,
            text="✕",
            bg=colors["input"],
            fg=colors["muted"],
            font=("Segoe UI", 8),
            cursor="hand2",
        )
        close.bind("<Button-1>", lambda _event: self._on_remove(index))
        close.bind("<Enter>", lambda _event: close.configure(fg=colors["error"]))
        close.bind("<Leave>", lambda _event: close.configure(fg=colors["muted"]))
        close.pack(side=tk.LEFT, padx=(6, 0))
        chip.pack(side=tk.LEFT, padx=(0, 6))
