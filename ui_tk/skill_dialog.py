"""Shared themed skill picker and creator for Chat and Code Mode."""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

from gd_core.skills import Skill, SkillManager
from gd_core.translations import get_text
from ui_tk.themes import get_theme


def _button(parent: tk.Widget, text: str, command: Callable[[], None], colors: dict[str, str], accent: bool = False) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=colors["accent"] if accent else colors["button"],
        fg="#ffffff" if accent else colors["foreground"],
        activebackground=colors["accent_active"] if accent else colors["button_active"],
        activeforeground="#ffffff" if accent else colors["foreground"],
        relief=tk.FLAT,
        bd=0,
        padx=10,
        pady=5,
    )


def _style(root: tk.Widget, colors: dict[str, str]) -> None:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Skills.Treeview",
        background=colors["input"],
        foreground=colors["foreground"],
        fieldbackground=colors["input"],
        bordercolor=colors["border"],
        rowheight=24,
    )
    style.map("Skills.Treeview", background=[("selected", colors["accent"])], foreground=[("selected", "#ffffff")])
    style.configure("Skills.THeading", background=colors["panel"], foreground=colors["foreground"], relief=tk.FLAT)
    style.map("Skills.THeading", background=[("active", colors["button_active"])])


class SkillAutocomplete:
    def __init__(self, widget: tk.Widget, skills_provider: Callable[[], list[Skill]], colors: dict[str, str]) -> None:
        self.widget = widget
        self.skills_provider = skills_provider
        self.colors = colors
        self.window: tk.Toplevel | None = None
        self.listbox: tk.Listbox | None = None
        self.skills: list[Skill] = []
        self.start = 0
        widget.bind("<KeyRelease>", self._refresh, add="+")
        widget.bind("<Down>", self._key, add="+")
        widget.bind("<Up>", self._key, add="+")
        widget.bind("<Return>", self._key, add="+")
        widget.bind("<Tab>", self._key, add="+")
        widget.bind("<Escape>", self._key, add="+")
        widget.bind("<FocusOut>", self.hide, add="+")

    def _before_cursor(self) -> str:
        if isinstance(self.widget, tk.Text):
            return self.widget.get("1.0", "insert-1c") if str(self.widget.index(tk.INSERT)) != "1.0" else ""
        return self.widget.get()[:self.widget.index(tk.INSERT)]

    def _refresh(self, _event=None) -> None:
        match = re.search(r"(?<!\S)@([A-Za-z0-9_.-]*)$", self._before_cursor())
        if not match:
            self.hide()
            return
        query = match.group(1).casefold()
        self.skills = [skill for skill in self.skills_provider() if query in skill.name.casefold() or query in skill.id.split(":", 1)[-1].casefold()][:8]
        if not self.skills:
            self.hide()
            return
        self.start = match.start()
        if self.window is None:
            self.window = tk.Toplevel(self.widget)
            self.window.wm_overrideredirect(True)
            self.window.wm_attributes("-topmost", True)
            self.listbox = tk.Listbox(
                self.window,
                bg=self.colors["input"],
                fg=self.colors["foreground"],
                selectbackground=self.colors["accent"],
                selectforeground="#ffffff",
                highlightbackground=self.colors["border"],
                highlightcolor=self.colors["accent"],
                relief=tk.FLAT,
                bd=0,
                activestyle="none",
                exportselection=False,
                font=("Segoe UI", 9),
            )
            self.listbox.pack(fill=tk.BOTH, expand=True)
            self.listbox.bind("<ButtonRelease-1>", self._choose)
        self.listbox.delete(0, tk.END)
        for skill in self.skills:
            label = f"@{skill.name}"
            if skill.description:
                label += f" — {skill.description}"
            self.listbox.insert(tk.END, label)
        self.listbox.selection_set(0)
        width = max(240, min(self.widget.winfo_width(), 420))
        height = min(8, len(self.skills))
        self.window.geometry(f"{width}x{height * 24 + 4}")
        if isinstance(self.widget, tk.Text):
            bbox = self.widget.bbox(tk.INSERT) or (0, 0, 0, 0)
            x = self.widget.winfo_rootx() + bbox[0]
            y = self.widget.winfo_rooty() + bbox[1] + bbox[3] + 4
        else:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.geometry(f"+{x}+{y}")

    def _key(self, event: tk.Event) -> str | None:
        if self.listbox is None or self.window is None:
            return None
        if event.keysym == "Escape":
            self.hide()
            return "break"
        if event.keysym in {"Down", "Up"}:
            current = self.listbox.curselection()
            index = current[0] if current else 0
            index = (index + (1 if event.keysym == "Down" else -1)) % len(self.skills)
            self.listbox.selection_set(index)
            return "break"
        if event.keysym in {"Return", "Tab"}:
            self._choose()
            return "break"
        return None

    def _choose(self, _event=None) -> None:
        if not self.skills or self.listbox is None:
            return
        selection = self.listbox.curselection()
        skill = self.skills[selection[0] if selection else 0]
        self.hide()
        if isinstance(self.widget, tk.Text):
            self.widget.delete(f"1.0+{self.start}c", tk.INSERT)
            self.widget.insert(tk.INSERT, f"@{skill.name} ")
        else:
            self.widget.delete(self.start, tk.INSERT)
            self.widget.insert(tk.INSERT, f"@{skill.name} ")

    def hide(self, _event=None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None
            self.listbox = None
        self.skills = []


class SkillDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Widget,
        workspace: str | Path | None,
        active_ids: list[str],
        lang: str,
        on_change: Callable[[list[str]], None],
        colors: dict[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.lang = lang
        self.colors = colors or get_theme("dark")
        self.manager = SkillManager(workspace)
        self.active_ids = list(active_ids)
        self.on_change = on_change
        self.title(self._t("skills_title"))
        self.geometry("680x560")
        self.minsize(560, 440)
        self.configure(bg=self.colors["background"])
        self.transient(parent.winfo_toplevel())
        _style(self, self.colors)

        bar = tk.Frame(self, bg=self.colors["panel"], padx=10, pady=8)
        bar.pack(fill=tk.X)
        _button(bar, self._t("skills_create"), self._show_create, self.colors, accent=True).pack(side=tk.LEFT)
        _button(bar, self._t("skills_toggle"), self._toggle_selected, self.colors).pack(side=tk.LEFT, padx=(6, 0))
        _button(bar, self._t("skills_done"), self.destroy, self.colors).pack(side=tk.RIGHT)

        hint = tk.Label(
            self,
            text=self._t("skills_hint"),
            bg=self.colors["background"],
            fg=self.colors["muted"],
            font=("Segoe UI", 9),
            wraplength=640,
            justify=tk.LEFT,
            anchor="w",
            padx=12,
            pady=8,
        )
        hint.pack(fill=tk.X)

        columns = ("active", "name", "description", "source")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse", style="Skills.Treeview")
        for key, width in (("active", 70), ("name", 150), ("description", 330), ("source", 110)):
            self.tree.heading(key, text=self._t(f"skills_{key}"))
            self.tree.column(key, width=width, stretch=key == "description")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        self.empty_label = tk.Label(self, text="", bg=self.colors["background"], fg=self.colors["muted"], anchor="w", padx=12)
        self.empty_label.pack(fill=tk.X)
        self.tree.bind("<Double-Button-1>", lambda _e: self._toggle_selected())
        self._refresh()

    def _t(self, key: str) -> str:
        return get_text(key, self.lang)

    def _refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.skills = self.manager.discover()
        self.empty_label.configure(text="" if self.skills else self._t("skills_empty"))
        for skill in self.skills:
            self.tree.insert("", "end", iid=skill.id, values=(
                "✓" if skill.id in self.active_ids else "",
                skill.name,
                skill.description,
                skill.source,
            ))

    def _toggle_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        skill_id = selection[0]
        if skill_id in self.active_ids:
            self.active_ids.remove(skill_id)
        else:
            self.active_ids.append(skill_id)
        self.on_change(list(self.active_ids))
        self._refresh()
        self.tree.selection_set(skill_id)

    def _show_create(self) -> None:
        self.create_dialog = SkillCreateDialog(self, self.manager, self.lang, self.colors, self._created)

    def _created(self, skill: Skill) -> None:
        if skill.id not in self.active_ids:
            self.active_ids.append(skill.id)
        self.on_change(list(self.active_ids))
        self._refresh()
        self.tree.selection_set(skill.id)


class SkillCreateDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Widget,
        manager: SkillManager,
        lang: str,
        colors: dict[str, str],
        on_created: Callable[[Skill], None],
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.lang = lang
        self.colors = colors
        self.on_created = on_created
        self.title(self._t("skills_create"))
        self.geometry("620x480")
        self.minsize(520, 400)
        self.configure(bg=self.colors["background"])
        self.transient(parent.winfo_toplevel())
        self.grab_set()

        form = tk.Frame(self, bg=self.colors["background"], padx=16, pady=16)
        form.pack(fill=tk.BOTH, expand=True)
        form.columnconfigure(1, weight=1)
        form.rowconfigure(2, weight=1)
        label_options = {"bg": self.colors["background"], "fg": self.colors["foreground"], "anchor": "w"}
        entry_options = {
            "bg": self.colors["input"],
            "fg": self.colors["foreground"],
            "insertbackground": self.colors["foreground"],
            "highlightbackground": self.colors["border"],
            "highlightcolor": self.colors["accent"],
            "relief": tk.FLAT,
        }
        self.name_var = tk.StringVar()
        self.description_var = tk.StringVar()
        tk.Label(form, text=self._t("skills_name"), **label_options).grid(row=0, column=0, sticky="w", pady=(0, 8))
        tk.Entry(form, textvariable=self.name_var, **entry_options).grid(row=0, column=1, sticky="ew", pady=(0, 8))
        tk.Label(form, text=self._t("skills_description"), **label_options).grid(row=1, column=0, sticky="w", pady=(0, 8))
        tk.Entry(form, textvariable=self.description_var, **entry_options).grid(row=1, column=1, sticky="ew", pady=(0, 8))
        tk.Label(form, text=self._t("skills_instructions"), **label_options).grid(row=2, column=0, sticky="nw", pady=(0, 8))
        self.instructions_text = tk.Text(form, wrap=tk.WORD, bg=self.colors["input"], fg=self.colors["foreground"], insertbackground=self.colors["foreground"], relief=tk.FLAT, highlightthickness=1, highlightbackground=self.colors["border"], highlightcolor=self.colors["accent"])
        self.instructions_text.grid(row=2, column=1, sticky="nsew", pady=(0, 8))
        buttons = tk.Frame(form, bg=self.colors["background"])
        buttons.grid(row=3, column=1, sticky="e", pady=(6, 0))
        _button(buttons, self._t("skills_cancel"), self.destroy, self.colors).pack(side=tk.LEFT, padx=(0, 6))
        _button(buttons, self._t("skills_save"), self._create, self.colors, accent=True).pack(side=tk.LEFT)
        form.grid_slaves(row=0, column=1)[0].focus_set()

    def _t(self, key: str) -> str:
        return get_text(key, self.lang)

    def _create(self) -> None:
        try:
            skill = self.manager.create(
                self.name_var.get(), self.description_var.get(), self.instructions_text.get("1.0", "end-1c")
            )
        except ValueError as error:
            messagebox.showerror(self._t("skills_title"), str(error), parent=self)
            return
        self.on_created(skill)
        self.destroy()
