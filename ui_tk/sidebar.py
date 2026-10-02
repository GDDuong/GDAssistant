"""sidebar.py: Collapsible saved-conversation sidebar for Chat and Code modes."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import Any, Callable

from gd_core.conversations import ConversationStore
from gd_core.translations import get_text


class ConversationSidebar(tk.Frame):
    """Left panel listing saved conversations with a collapsible layout.

    Layout: a thin always-visible strip holds the expand/collapse toggle;
    the content column holds the New button on top, a separator, the saved
    list, and an archived-visibility toggle at the bottom.
    """

    def __init__(
        self,
        master: tk.Misc,
        store: ConversationStore,
        kind: str,
        palette: dict[str, str],
        lang: str,
        on_open: Callable[[str | None], None] | None = None,
        on_new: Callable[[], None] | None = None,
        on_convert: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, bg=palette["panel"], width=216, bd=0)
        self.pack_propagate(False)
        self.store = store
        self.kind = kind  # "chat" or "code"
        self.lang = lang
        self.palette = palette
        self.on_open = on_open
        self.on_new = on_new
        self.on_convert = on_convert
        self.current_id: str | None = None
        self.expanded = True
        self.ids: list[str] = []
        self._loading = False
        self.show_archived_var = tk.BooleanVar(value=False)
        self._build(palette)
        self.refresh()

    # ------------------------------------------------------------------ UI

    def _build(self, palette: dict[str, str]) -> None:
        self.strip = tk.Frame(self, bg=palette["panel"], width=34)
        self.strip.pack(side=tk.LEFT, fill=tk.Y)
        self.strip.pack_propagate(False)

        self.toggle_btn = tk.Button(
            self.strip,
            text="«",
            command=self.toggle,
            relief=tk.FLAT,
            bd=0,
            bg=palette["button"],
            fg=palette["foreground"],
            activebackground=palette["button_active"],
            activeforeground=palette["foreground"],
            font=("Segoe UI", 9),
        )
        self.toggle_btn.place(x=3, y=6)

        self.content = tk.Frame(self, bg=palette["panel"], width=182)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.content.pack_propagate(False)

        top_row = tk.Frame(self.content, bg=palette["panel"])
        top_row.pack(fill=tk.X, padx=6, pady=6)
        self.new_btn = tk.Button(
            top_row,
            text=self._text("sidebar_new_project" if self.kind == "code" else "sidebar_new_chat"),
            command=self._handle_new,
            relief=tk.FLAT,
            bg=palette["accent"],
            fg="#ffffff",
            activebackground=palette["accent_active"],
            activeforeground="#ffffff",
            font=("Segoe UI", 9, "bold"),
            pady=4,
        )
        self.new_btn.pack(fill=tk.X)

        tk.Frame(self.content, bg=palette["border"], height=1).pack(fill=tk.X, padx=6)

        self.section_label = tk.Label(
            self.content,
            text=self._text("sidebar_projects" if self.kind == "code" else "sidebar_chats"),
            bg=palette["panel"],
            fg=palette["muted"],
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.section_label.pack(fill=tk.X, padx=8, pady=(6, 2))

        self.listbox = tk.Listbox(
            self.content,
            bd=0,
            highlightthickness=0,
            relief=tk.FLAT,
            activestyle="none",
            exportselection=False,
            bg=palette["input"],
            fg=palette["foreground"],
            selectbackground=palette["accent"],
            selectforeground="#ffffff",
            font=("Segoe UI", 9),
        )
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Double-Button-1>", lambda _e: self._open_selected())
        self.listbox.bind("<Button-3>", self._show_context_menu)

        self.archived_check = tk.Checkbutton(
            self.content,
            text=self._text("sidebar_show_archived"),
            variable=self.show_archived_var,
            command=self.refresh,
            relief=tk.FLAT,
            bg=palette["panel"],
            fg=palette["muted"],
            activebackground=palette["panel"],
            activeforeground=palette["foreground"],
            selectcolor=palette["input"],
            font=("Segoe UI", 8),
            anchor="w",
        )
        self.archived_check.pack(fill=tk.X, padx=6, pady=(0, 6))

    def _text(self, key: str) -> str:
        return get_text(key, self.lang)

    # -------------------------------------------------------------- public

    def toggle(self) -> None:
        self.expanded = not self.expanded
        if self.expanded:
            self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.configure(width=216)
            self.toggle_btn.configure(text="«")
        else:
            self.content.pack_forget()
            self.configure(width=34)
            self.toggle_btn.configure(text="»")

    def refresh(self) -> None:
        self._loading = True
        conversations = self.store.list_conversations(
            self.kind, include_archived=self.show_archived_var.get()
        )
        self.ids = [conv["id"] for conv in conversations]
        suffix = self._text("sidebar_archived_suffix")
        self.listbox.delete(0, tk.END)
        for conv in conversations:
            label = str(conv.get("title") or "...")
            if conv.get("status") == "archived":
                label += suffix
            self.listbox.insert(tk.END, label)
        if self.current_id in self.ids:
            self.listbox.selection_set(self.ids.index(self.current_id))
        self._loading = False

    def set_current(self, conv_id: str | None) -> None:
        self.current_id = conv_id
        self.refresh()

    # ------------------------------------------------------------ handlers

    def _handle_new(self) -> None:
        if self.on_new:
            self.on_new()

    def _on_select(self, _event: Any = None) -> None:
        if self._loading:
            return
        selection = self.listbox.curselection()
        if not selection:
            return
        conv_id = self.ids[selection[0]]
        if conv_id == self.current_id:
            return
        self._open(conv_id)

    def _open_selected(self) -> None:
        selection = self.listbox.curselection()
        if selection:
            self._open(self.ids[selection[0]])

    def _open(self, conv_id: str) -> None:
        self.current_id = conv_id
        if self.on_open:
            self.on_open(conv_id)

    def _context_for(self, conv_id: str) -> dict[str, Any] | None:
        return self.store.load_conversation(conv_id)

    def _show_context_menu(self, event: Any) -> None:
        index = self.listbox.nearest(event.y)
        if index < 0 or index >= len(self.ids):
            return
        self._loading = True
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self._loading = False
        conv_id = self.ids[index]
        conv = self._context_for(conv_id)
        if conv is None:
            return

        menu = tk.Menu(
            self,
            tearoff=0,
            bg=self.palette["panel"],
            fg=self.palette["foreground"],
            activebackground=self.palette["accent"],
            activeforeground="#ffffff",
            bd=0,
        )
        menu.add_command(label=self._text("ctx_open"), command=lambda: self._open(conv_id))
        menu.add_command(
            label=self._text("ctx_rename"),
            command=lambda: self._rename(conv_id, str(conv.get("title", ""))),
        )
        if conv.get("status") == "archived":
            menu.add_command(label=self._text("ctx_unarchive"), command=lambda: self._set_status(conv_id, "active"))
        else:
            menu.add_command(label=self._text("ctx_archive"), command=lambda: self._set_status(conv_id, "archived"))
        if self.kind == "chat" and self.on_convert and conv.get("status") == "active":
            menu.add_separator()
            menu.add_command(label=self._text("ctx_to_code"), command=lambda: self._convert(conv_id))
        menu.add_separator()
        menu.add_command(label=self._text("ctx_delete"), command=lambda: self._delete(conv_id))
        menu.tk_popup(event.x_root, event.y_root)

    def update_palette(self, palette: dict[str, str]) -> None:
        self.palette = palette
        for widget in (self, self.strip, self.content):
            widget.configure(bg=palette["panel"])
        self.toggle_btn.configure(
            bg=palette["button"],
            fg=palette["foreground"],
            activebackground=palette["button_active"],
            activeforeground=palette["foreground"],
        )
        self.new_btn.configure(
            bg=palette["accent"],
            activebackground=palette["accent_active"],
        )
        self.section_label.configure(bg=palette["panel"], fg=palette["muted"])
        self.listbox.configure(
            bg=palette["input"],
            fg=palette["foreground"],
            selectbackground=palette["accent"],
        )
        self.archived_check.configure(
            bg=palette["panel"],
            fg=palette["muted"],
            activebackground=palette["panel"],
            selectcolor=palette["input"],
        )

    def _rename(self, conv_id: str, current_title: str) -> None:
        title_key = "rename_project_title" if self.kind == "code" else "rename_chat_title"
        new_title = simpledialog.askstring(
            self._text(title_key),
            current_title,
            initialvalue=current_title,
            parent=self.winfo_toplevel(),
        )
        if new_title is None:
            return
        self.store.rename_conversation(conv_id, new_title.strip())
        self.refresh()

    def _set_status(self, conv_id: str, status: str) -> None:
        self.store.set_status(conv_id, status)
        if conv_id == self.current_id and status == "archived":
            self.current_id = None
            self.refresh()
            if self.on_open:
                self.on_open(None)
            return
        self.refresh()

    def _delete(self, conv_id: str) -> None:
        confirm_key = "delete_project_confirm" if self.kind == "code" else "delete_chat_confirm"
        confirmed = messagebox.askyesno(
            self._text("ctx_delete"),
            self._text(confirm_key),
            parent=self.winfo_toplevel(),
        )
        if not confirmed:
            return
        self.store.delete_conversation(conv_id)
        if conv_id == self.current_id:
            self.current_id = None
            self.refresh()
            if self.on_open:
                self.on_open(None)
            return
        self.refresh()

    def _convert(self, conv_id: str) -> None:
        if self.on_convert:
            self.on_convert(conv_id)
