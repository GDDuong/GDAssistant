"""Code Mode IDE: explorer, editor, diffs, terminal, plans, and agent chat."""

from __future__ import annotations

import hashlib
import os
import queue
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from gd_core.attachments import display_summary, load_binary_parts, prepare_message
from gd_core.code_agent import CodeAgentSession
from gd_core.code_commands import CodeCommandRouter
from gd_core.code_settings import normalize_code_settings
from gd_core.coding_tools import configure_code_mode, get_registry, get_terminal_manager, set_extra_dirs
from gd_core.conversations import ConversationStore
from gd_core.project import inspect_project
from gd_core.task_state import CheckpointStore, TaskPlan
from gd_core.translations import get_text
from ui_tk.attach_strip import AttachStrip
from ui_tk.mdrender import configure_tags, insert_markdown
from ui_tk.themes import get_theme


def _button(parent, text, command, colors, **kwargs):
    options = {
        "bg": colors["button"], "fg": colors["foreground"],
        "activebackground": colors["button_active"], "activeforeground": colors["foreground"],
        "relief": tk.FLAT, "bd": 0, "padx": 8, "pady": 4,
        "font": ("Segoe UI", 9),
    }
    options.update(kwargs)
    return tk.Button(parent, text=text, command=command, **options)


def _accent_button(parent, text, command, colors, **kwargs):
    return _button(parent, text, command, colors, bg=colors["accent"], fg="#ffffff", activebackground=colors["accent_active"], activeforeground="#ffffff", **kwargs)


class CodeEditor(tk.Frame):
    """Tk Text editor with line numbers, lightweight highlighting, and safe save."""

    KEYWORDS = {
        "python": "and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield",
        "javascript": "async await break case catch class const continue debugger default delete do else export extends false finally for function if import in instanceof let new null return static super switch this throw true try typeof var void while yield",
        "typescript": "abstract any as async await boolean break case catch class const constructor continue declare default delete do else enum export extends false finally for from function if implements import in infer interface keyof let namespace never new null number object private protected public readonly return static string super switch this throw true try type typeof undefined unknown var void while",
        "java": "abstract assert boolean break byte case catch char class const continue default do double else enum extends final finally float for if implements import instanceof int interface long native new null package private protected public return short static strictfp super switch synchronized this throw throws transient true try void volatile while false",
        "kotlin": "as break class continue do else false for fun if in interface is null object package return super this throw true try typealias typeof val var when while",
        "csharp": "abstract as base bool break byte case catch char checked class const continue decimal default delegate do double else enum event explicit extern false finally fixed float for foreach goto if implicit in int interface internal is lock long namespace new null object operator out override params private protected public readonly ref return sbyte sealed short sizeof stackalloc static string struct switch this throw true try typeof uint ulong unchecked unsafe ushort using virtual void volatile while var",
        "rust": "as async await break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut pub ref return self Self static struct super trait true type unsafe use where while",
        "go": "break default func interface select case defer go map struct chan else goto package switch const fallthrough if range type continue for import return var true false nil",
        "cpp": "alignas alignof and asm auto bool break case catch char class const constexpr continue default delete do double else enum explicit export extern false float for friend if inline int long mutable namespace new noexcept nullptr operator private protected public register reinterpret_cast return short signed sizeof static struct switch template this throw true try typedef typeid typename union unsigned using virtual void volatile while",
        "c": "auto break case char const continue default do double else enum extern float for goto if inline int long register restrict return short signed sizeof static struct switch typedef union unsigned void volatile while",
        "ruby": "alias and begin break case class def defined do else elsif end ensure false for if in module next nil not or redo rescue retry return self super then true undef unless until when while yield",
        "php": "abstract and array as break callable case catch class clone const continue declare default die do echo else elseif empty enddeclare endfor endforeach endif endswitch endwhile eval exit extends final finally fn for foreach function global goto if implements include include_once instanceof insteadof interface isset list match namespace new null or print private protected public readonly require require_once return static switch throw trait true try unset use var while xor yield",
        "swift": "associatedtype class deinit enum extension fileprivate func import init inout internal let open operator private protocol public rethrows static struct subscript typealias var break case continue default defer do else fallthrough for guard if in repeat return switch where while as Any catch false is nil super self Self throw throws true try",
        "dart": "abstract as assert async await break case catch class const continue covariant default deferred do dynamic else enum export extends extension external factory false final finally for Function get hide if implements import in interface is late library mixin new null of on operator part required rethrow return set show static super switch sync this throw true try typedef var void while with yield",
        "lua": "and break do else elseif end false for function goto if in local nil not or repeat return then true until while",
        "sql": "add all alter and any as asc backup between by case check column constraint create database default delete desc distinct drop exec exists foreign from full group having in index inner insert into is join key left like limit not null or order outer primary references right rollback row select set table top truncate union unique update values view where",
    }

    def __init__(self, parent, colors, on_save, on_modified=None, tab_size=4, lang="en"):
        super().__init__(parent, bg=colors["background"])
        self.lang = lang
        self.tab_size = tab_size
        self.colors = colors
        self.on_save = on_save
        self.on_modified = on_modified
        self.path: Path | None = None
        self.original_hash: str | None = None
        self._highlight_job = None
        toolbar = tk.Frame(self, bg=colors["panel"])
        toolbar.pack(fill=tk.X)
        self.file_label = tk.Label(toolbar, text="", bg=colors["panel"], fg=colors["muted"], anchor="w", font=("Consolas", 9))
        self.file_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        _button(toolbar, get_text("code_save_short", self.lang), self.save, colors).pack(side=tk.RIGHT, padx=2, pady=4)
        _button(toolbar, get_text("code_revert", self.lang), self.revert, colors).pack(side=tk.RIGHT, padx=2, pady=4)
        body = tk.Frame(self, bg=colors["background"])
        body.pack(fill=tk.BOTH, expand=True)
        self.line_numbers = tk.Canvas(body, width=52, bg=colors["panel"], highlightthickness=0, bd=0)
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)
        self.text = tk.Text(
            body, wrap=tk.NONE, undo=True, bg=colors["background"], fg=colors["foreground"],
            insertbackground=colors["foreground"], font=("Consolas", 11), padx=8, pady=8,
            bd=0, highlightthickness=0, tabs=("4",),
        )
        self.scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=lambda *args: (self.scroll.set(*args), self._draw_lines()))
        self.scroll.pack(side=tk.RIGHT, fill=tk.Y)
        hscroll = ttk.Scrollbar(self, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(xscrollcommand=hscroll.set)
        hscroll.pack(fill=tk.X, side=tk.BOTTOM)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text.bind("<KeyRelease>", self._on_key)
        self.text.bind("<Control-s>", lambda _e: self.save())
        self.text.bind("<Tab>", self._tab)
        self.text.tag_configure("keyword", foreground=colors["muted"])
        self.text.tag_configure("string", foreground=colors["user"])
        self.text.tag_configure("comment", foreground=colors["border"])
        self.text.tag_configure("number", foreground=colors["working"])

    def load(self, path: Path, content: str, content_hash: str | None = None) -> None:
        self.path = path
        self.original_hash = content_hash
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.text.edit_reset()
        self.file_label.configure(text=f"{path.name}  —  {path}")
        self._highlight()
        self._draw_lines()

    def _language(self) -> str:
        if self.path is None:
            return ""
        return {".py": "python", ".pyw": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".ts": "typescript", ".tsx": "typescript", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".cs": "csharp", ".rs": "rust", ".go": "go", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".h": "cpp", ".c": "c", ".rb": "ruby", ".php": "php", ".swift": "swift", ".dart": "dart", ".lua": "lua", ".sql": "sql"}.get(self.path.suffix.lower(), "")

    def _on_key(self, _event=None):
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(180, self._highlight)
        self._draw_lines()
        if self.on_modified:
            self.on_modified()

    def _highlight(self):
        self._highlight_job = None
        text = self.text.get("1.0", "end-1c")
        if len(text) > 300_000:
            return
        for tag in ("keyword", "string", "comment", "number"):
            self.text.tag_remove(tag, "1.0", tk.END)
        language = self._language()
        if not language:
            return
        patterns = [("keyword", r"\b(?:" + "|".join(re.escape(word) for word in self.KEYWORDS.get(language, "").split()) + r")\b")]
        patterns.append(("string", r"(?s)(?:\"\"\".*?\"\"\"|'''.*?'''|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)"))
        patterns.append(("comment", r"#.*$" if language == "python" else r"//.*$|/\*.*?\*/|--.*$" if language == "sql" else r"//.*$|/\*.*?\*/"))
        patterns.append(("number", r"\b(?:0x[0-9A-Fa-f]+|\d+(?:\.\d+)?)\b"))
        for tag, pattern in patterns:
            if tag == "keyword" and not self.KEYWORDS.get(language):
                continue
            for match in re.finditer(pattern, text, re.M):
                start = f"1.0+{match.start()}c"
                end = f"1.0+{match.end()}c"
                self.text.tag_add(tag, start, end)

    def _draw_lines(self):
        self.line_numbers.delete("all")
        first = int(self.text.index("@0,0").split(".")[0])
        last = int(self.text.index(f"@0,{self.text.winfo_height()}").split(".")[0])
        for line in range(first, last + 2):
            y = self.text.bbox(f"{line}.0")
            if y:
                self.line_numbers.create_text(46, y[1] + 2, text=str(line), anchor="ne", fill=self.colors["muted"], font=("Consolas", 9))

    def _tab(self, event):
        self.text.insert(tk.INSERT, " " * self.tab_size)
        return "break"

    def save(self):
        if self.path is None:
            return
        content = self.text.get("1.0", "end-1c")
        result = self.on_save(self.path, content, self.original_hash)
        if result.get("status") == "SUCCESS":
            self.original_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
            self.file_label.configure(text=f"{self.path.name}  —  {self.path}")

    def revert(self):
        if self.path is not None:
            self.on_modified(revert=True)


class TerminalPane(tk.Frame):
    def __init__(self, parent, notebook, manager, workspace, policy, colors, lang, timeout):
        super().__init__(parent, bg=colors["background"])
        self.manager = manager
        self.workspace = workspace
        self.policy = policy
        self.colors = colors
        self.lang = lang
        self.timeout = timeout
        self.session_id: str | None = None
        self._poll_job = None
        toolbar = tk.Frame(self, bg=colors["panel"])
        toolbar.pack(fill=tk.X)
        self.cwd_label = tk.Label(toolbar, text=str(workspace), bg=colors["panel"], fg=colors["muted"], anchor="w", font=("Consolas", 8))
        self.cwd_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.status_label = tk.Label(toolbar, text=get_text("code_ready", lang), bg=colors["panel"], fg=colors["foreground"], font=("Segoe UI", 8))
        self.status_label.pack(side=tk.RIGHT, padx=6)
        _button(toolbar, get_text("btn_stop", lang), self.stop, colors).pack(side=tk.RIGHT, padx=2, pady=4)
        self.output = tk.Text(self, bg=colors["background"], fg=colors["foreground"], insertbackground=colors["foreground"], font=("Consolas", 9), wrap=tk.WORD, state=tk.DISABLED, bd=0, padx=8, pady=8)
        self.output.pack(fill=tk.BOTH, expand=True)
        entry_row = tk.Frame(self, bg=colors["panel"], padx=6, pady=6)
        entry_row.pack(fill=tk.X)
        self.command = tk.Entry(entry_row, bg=colors["input"], fg=colors["foreground"], insertbackground=colors["foreground"], bd=0, font=("Consolas", 9))
        self.command.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.command.bind("<Return>", lambda _e: self.start_command())
        _accent_button(entry_row, get_text("code_run", lang), self.start_command, colors).pack(side=tk.RIGHT)
        notebook.add(self, text=get_text("code_terminal", lang))

    def append(self, text):
        def apply():
            self.output.configure(state=tk.NORMAL)
            self.output.insert(tk.END, text)
            self.output.see(tk.END)
            self.output.configure(state=tk.DISABLED)
        self.after(0, apply)

    def attach(self, session_id):
        self.session_id = session_id
        self.status_label.configure(text=get_text("code_running", self.lang))
        self._poll()

    def start_command(self):
        command = self.command.get().strip()
        if not command:
            return
        if self.session_id and self.manager.sessions.get(self.session_id) and self.manager.sessions[self.session_id].exit_code is None:
            self.append(get_text("code_terminal_busy", self.lang) + "\n")
            return
        self.command.delete(0, tk.END)
        self.append(f"\n$ {command}\n")
        self.status_label.configure(text=get_text("code_starting", self.lang))

        def run():
            result = self.manager.start(command, self.workspace, self.timeout, policy=self.policy, on_output=lambda _sid, text: self.after(0, lambda: self.append(text)))
            self.after(0, lambda: self._started(result))
        threading.Thread(target=run, daemon=True).start()

    def _started(self, result):
        if result.get("status") == "SUCCESS":
            self.attach(result["session_id"])
        else:
            self.status_label.configure(text=get_text("code_command_denied", self.lang))
            self.append(str(result.get("message", get_text("code_command_failed", self.lang))) + "\n")

    def _poll(self):
        if not self.session_id:
            return
        result = self.manager.read_output(self.session_id)
        if not result.get("running"):
            self.status_label.configure(text=f"{get_text('code_exit', self.lang)} {result.get('returncode')}")
            return
        self._poll_job = self.after(120, self._poll)

    def stop(self):
        if self.session_id:
            result = self.manager.stop(self.session_id)
            self.append(str(result.get("message", "")) + "\n")
            self.status_label.configure(text=get_text("status_stopping", self.lang))


class CodeAgentPanel(tk.Frame):
    def __init__(self, parent, client, model="gemini-3.5-flash-lite", start_dir=".", theme="dark", debug=False, lang="en", conversation_id=None, store=None, settings=None):
        self.colors = get_theme(theme)
        super().__init__(parent, bg=self.colors["background"])
        self.client = client
        self.model = model
        self.theme = theme
        self.debug = debug
        self.lang = lang
        self.store = store or ConversationStore()
        self.settings = normalize_code_settings(settings)
        self.conv: dict[str, Any] | None = None
        self.extra_dirs: list[str] = []
        self.pending_files: list[Path] = []
        self.is_busy = False
        self.stop_event: threading.Event | None = None
        self.stream_pieces: list[str] = []
        self._stream_render_job = None
        self.plan = TaskPlan()
        self.checkpoints: CheckpointStore | None = None
        self.session: CodeAgentSession | None = None
        self.context = None
        self.registry = None
        self.terminals = get_terminal_manager()
        self.terminal_panes: dict[str, TerminalPane] = {}
        self.editor_path: Path | None = None
        self._explorer_visible = True
        self._activity_visible = True
        self._init_conversation(conversation_id)
        self._build_ui()
        self._refresh_all()
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, event=None):
        if event is not None and event.widget is not self:
            return
        if getattr(self, "terminals", None):
            self.terminals.stop_all()

    def _text(self, key):
        return get_text(key, self.lang)

    def _configure_session(self):
        workspace = str(self.conv.get("workspace") or self.settings.get("default_project_dir") or os.getcwd()) if self.conv else os.getcwd()
        if not Path(workspace).is_dir():
            workspace = os.getcwd()
        self.checkpoints = CheckpointStore(workspace, self.settings.get("checkpoint_retention", 20))
        set_extra_dirs(self.extra_dirs)
        self.context = configure_code_mode(
            workspace, self.settings, approval_callback=self.request_approval,
            event_callback=self._queue_core_event, task_id=self.conv["id"] if self.conv else "project",
            checkpoints=self.checkpoints, plan=self.plan,
        )
        self.registry = get_registry()
        self.terminals = self.context.terminals
        self.session = CodeAgentSession(
            self.client, model=self.model, on_status=self.on_agent_status, debug=self.debug,
            extra_dirs=self.extra_dirs, settings=self.settings, registry=self.registry,
            context=self.context, on_event=self._queue_core_event, task_id=self.context.task_id,
            checkpoints=self.checkpoints, plan=self.plan, approval_callback=self.request_approval,
            seed_messages=(self.conv or {}).get("messages") or [],
        )
        self.router = CodeCommandRouter(self.session, self.lang)

    def _init_conversation(self, conversation_id):
        if conversation_id:
            conv = self.store.load_conversation(conversation_id)
            if conv is not None:
                self._set_conversation(conv)
                return
        recent = self.store.list_conversations("code")
        if recent:
            self._set_conversation(recent[0])
        else:
            conv = self.store.create_conversation("code", title=self._text("sidebar_new_project"), workspace=self.settings.get("default_project_dir") or os.getcwd())
            self._set_conversation(conv)

    def _set_conversation(self, conv):
        self.conv = conv
        self.extra_dirs = [str(path) for path in conv.get("extra_dirs") or []]
        self.plan = TaskPlan()
        self._configure_session()

    def _build_ui(self):
        color = self.colors
        self._build_topbar()
        body = tk.Frame(self, bg=color["background"])
        body.pack(fill=tk.BOTH, expand=True)
        self.explorer = self._build_explorer(body)
        self.explorer.pack(side=tk.LEFT, fill=tk.Y)
        self.explorer_toggle = _button(body, "»", self.toggle_explorer, color, width=3)
        self.explorer_toggle.pack(side=tk.LEFT, fill=tk.Y)
        center = tk.Frame(body, bg=color["background"])
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.center_dock = tk.PanedWindow(center, orient=tk.VERTICAL, bg=color["background"], bd=0, sashwidth=5, sashrelief=tk.FLAT)
        self.center_dock.pack(fill=tk.BOTH, expand=True)
        upper = tk.Frame(self.center_dock, bg=color["background"])
        self.center_dock.add(upper, minsize=300, height=520)
        self._build_workspace_tabs(upper)
        self._build_terminal_dock(self.center_dock)
        self._build_input(center)
        self.activity = self._build_activity(body)
        self.activity.pack(side=tk.RIGHT, fill=tk.Y)
        self.activity_toggle = _button(body, "«", self.toggle_activity, color, width=3)
        self.activity_toggle.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_var = tk.StringVar(value=self._text("code_ready"))
        tk.Label(self, textvariable=self.status_var, bg=color["accent"], fg="#ffffff", anchor="w", padx=8, pady=2, font=("Segoe UI", 8)).pack(fill=tk.X, side=tk.BOTTOM)
        self._apply_ttk_style()

    def _build_topbar(self):
        color = self.colors
        bar = tk.Frame(self, bg=color["panel"], padx=8, pady=6)
        bar.pack(fill=tk.X, side=tk.TOP)
        _accent_button(bar, self._text("code_browse"), self.on_browse_workspace, color).pack(side=tk.LEFT, padx=(0, 4))
        self.project_label = tk.Label(bar, text="", bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 10, "bold"), anchor="w")
        self.project_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        tk.Label(bar, text=f"{self._text('code_model')} {self.model}", bg=color["panel"], fg=color["muted"], font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=8)
        self.permission_var = tk.StringVar(value=self.settings.get("permission_mode", "project_autonomous"))
        ttk.Combobox(bar, textvariable=self.permission_var, state="readonly", width=20, values=("supervised", "project_autonomous", "advanced")).pack(side=tk.LEFT, padx=4)
        self.permission_var.trace_add("write", lambda *_: self._permission_changed())
        _button(bar, self._text("menu_settings"), self.on_open_settings, color).pack(side=tk.LEFT, padx=4)

    def _build_explorer(self, parent):
        color = self.colors
        frame = tk.Frame(parent, bg=color["panel"], width=248)
        frame.pack_propagate(False)
        tk.Label(frame, text=self._text("code_explorer"), bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 10, "bold"), anchor="w", padx=8, pady=8).pack(fill=tk.X)
        self.file_search = tk.Entry(frame, bg=color["input"], fg=color["foreground"], insertbackground=color["foreground"], bd=0, font=("Segoe UI", 9))
        self.file_search.pack(fill=tk.X, padx=8, pady=(0, 6))
        self.file_search.bind("<Return>", lambda _e: self.search_files())
        self.file_search.bind("<Escape>", lambda _e: (self.file_search.delete(0, tk.END), self.populate_tree()))
        row = tk.Frame(frame, bg=color["panel"])
        row.pack(fill=tk.X, padx=6, pady=2)
        _button(row, "+", self.new_file, color, width=3).pack(side=tk.LEFT, padx=1)
        _button(row, get_text("code_new_folder", self.lang), self.new_folder, color).pack(side=tk.LEFT, padx=1)
        _button(row, get_text("code_refresh", self.lang), self.populate_tree, color).pack(side=tk.LEFT, padx=1)
        _button(row, get_text("code_add_ref", self.lang), self.on_add_ref_dir, color).pack(side=tk.LEFT, padx=1)
        self.tree = ttk.Treeview(frame, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.tree.bind("<Double-Button-1>", self.on_tree_open)
        self.tree.bind("<<TreeviewOpen>>", self.on_tree_expand)
        self.search_results = tk.Listbox(frame, bg=color["input"], fg=color["foreground"], selectbackground=color["accent"], selectforeground="#ffffff", bd=0, font=("Consolas", 8))
        self.search_results.bind("<Double-Button-1>", self.on_search_open)
        tk.Label(frame, text=self._text("code_recent"), bg=color["panel"], fg=color["muted"], font=("Segoe UI", 8, "bold"), anchor="w", padx=8).pack(fill=tk.X)
        self.recent_list = tk.Listbox(frame, height=4, bg=color["input"], fg=color["foreground"], selectbackground=color["accent"], selectforeground="#ffffff", bd=0, font=("Segoe UI", 8))
        self.recent_list.pack(fill=tk.X, padx=6, pady=(0, 6))
        self.recent_list.bind("<Double-Button-1>", self.on_recent_open)
        return frame

    def _build_workspace_tabs(self, parent):
        color = self.colors
        self.tabs = ttk.Notebook(parent)
        self.tabs.pack(fill=tk.BOTH, expand=True)
        self.agent_tab = tk.Frame(self.tabs, bg=color["background"])
        self.tabs.add(self.agent_tab, text=self._text("code_agent_tab"))
        self.transcript = tk.Text(self.agent_tab, wrap=tk.WORD, bg=color["background"], fg=color["foreground"], insertbackground=color["foreground"], font=("Consolas", 10), padx=12, pady=12, bd=0, state=tk.DISABLED)
        self.transcript.pack(fill=tk.BOTH, expand=True)
        self.transcript.tag_configure("user", foreground=color["user"], font=("Consolas", 10, "bold"))
        self.transcript.tag_configure("agent", foreground=color["foreground"])
        self.transcript.tag_configure("system", foreground=color["muted"], font=("Consolas", 9, "italic"))
        self.transcript.tag_configure("error", foreground=color["error"], font=("Consolas", 10, "bold"))
        configure_tags(self.transcript, color, family="Consolas", size=10)
        self.editor = CodeEditor(self.tabs, color, self.save_editor_file, self.editor_modified, tab_size=int(self.settings.get("tab_size", 4)), lang=self.lang)
        self.editor.text.configure(font=("Consolas", int(self.settings.get("editor_font_size", 11))), tabs=(str(int(self.settings.get("tab_size", 4))),))
        self.tabs.add(self.editor, text=self._text("code_editor_tab"))
        self.diff_tab = tk.Frame(self.tabs, bg=color["background"])
        self.tabs.add(self.diff_tab, text=self._text("code_diff_tab"))
        self._build_diff_tab()
        self.plan_tab = tk.Frame(self.tabs, bg=color["background"])
        self.tabs.add(self.plan_tab, text=self._text("code_plan_tab"))
        self._build_plan_tab()
        self.overview_tab = tk.Frame(self.tabs, bg=color["background"])
        self.tabs.add(self.overview_tab, text=self._text("code_overview_tab"))
        self.overview_text = tk.Text(self.overview_tab, bg=color["background"], fg=color["foreground"], font=("Consolas", 10), wrap=tk.WORD, bd=0, padx=12, pady=12)
        self.overview_text.pack(fill=tk.BOTH, expand=True)

    def _build_diff_tab(self):
        color = self.colors
        bar = tk.Frame(self.diff_tab, bg=color["panel"])
        bar.pack(fill=tk.X)
        _button(bar, self._text("code_undo_last"), self.undo_last_change, color).pack(side=tk.LEFT, padx=2, pady=4)
        _button(bar, self._text("code_accept"), self.accept_selected_change, color).pack(side=tk.LEFT, padx=2, pady=4)
        _button(bar, self._text("code_reject"), self.reject_selected_change, color).pack(side=tk.LEFT, padx=2, pady=4)
        self.change_tree = ttk.Treeview(self.diff_tab, columns=("status", "operation", "path"), show="headings", height=5)
        self.change_tree.heading("status", text=get_text("code_status", self.lang))
        self.change_tree.heading("operation", text=get_text("code_operation", self.lang))
        self.change_tree.heading("path", text=get_text("code_file", self.lang))
        self.change_tree.column("status", width=80, stretch=False)
        self.change_tree.column("operation", width=100, stretch=False)
        self.change_tree.column("path", width=420)
        self.change_tree.pack(fill=tk.X, padx=6, pady=6)
        self.change_tree.bind("<<TreeviewSelect>>", self.show_selected_diff)
        self.diff_text = tk.Text(self.diff_tab, bg=color["background"], fg=color["foreground"], font=("Consolas", 9), wrap=tk.NONE, bd=0, padx=8, pady=8)
        self.diff_text.pack(fill=tk.BOTH, expand=True)
        self.diff_text.tag_configure("add", foreground=color["user"])
        self.diff_text.tag_configure("remove", foreground=color["error"])

    def _build_plan_tab(self):
        color = self.colors
        bar = tk.Frame(self.plan_tab, bg=color["panel"])
        bar.pack(fill=tk.X)
        self.plan_progress_label = tk.Label(bar, text="0 / 0", bg=color["panel"], fg=color["muted"], font=("Segoe UI", 9))
        self.plan_progress_label.pack(side=tk.RIGHT, padx=8)
        self.plan_tree = ttk.Treeview(self.plan_tab, columns=("status", "step"), show="headings")
        self.plan_tree.heading("status", text=get_text("code_status", self.lang))
        self.plan_tree.heading("step", text=get_text("code_step", self.lang))
        self.plan_tree.column("status", width=110, stretch=False)
        self.plan_tree.column("step", width=600)
        self.plan_tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.plan_progress = ttk.Progressbar(self.plan_tab, maximum=100)
        self.plan_progress.pack(fill=tk.X, padx=6, pady=(0, 6))

    def _build_terminal_dock(self, parent):
        color = self.colors
        dock = tk.Frame(parent, bg=color["panel"], height=210)
        parent.add(dock, minsize=120, height=210)
        header = tk.Frame(dock, bg=color["panel"])
        header.pack(fill=tk.X)
        tk.Label(header, text=self._text("code_terminal"), bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 9, "bold"), padx=8, pady=4).pack(side=tk.LEFT)
        _button(header, "+ " + get_text("code_terminal", self.lang), self.new_terminal, color).pack(side=tk.RIGHT, padx=2, pady=3)
        self.terminal_notebook = ttk.Notebook(dock)
        self.terminal_notebook.pack(fill=tk.BOTH, expand=True)
        self.new_terminal()

    def _build_input(self, parent):
        color = self.colors
        frame = tk.Frame(parent, bg=color["panel"], padx=8, pady=8)
        frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.attach_btn = _button(frame, "+", self.on_attach_files, color, width=3, font=("Segoe UI", 11, "bold"))
        self.attach_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.attach_strip = AttachStrip(frame, {**color, "background": color["panel"]}, clear_text=self._text("attach_clear"), on_remove=lambda index: self.remove_attachment(index), on_clear=self.clear_attachments)
        self.input_box = tk.Text(frame, height=3, bg=color["input"], fg=color["foreground"], insertbackground=color["foreground"], font=("Segoe UI", 10), padx=8, pady=6, bd=0, highlightthickness=1, highlightbackground=color["border"], highlightcolor=color["accent"])
        self.input_box.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 8))
        self.input_box.bind("<Return>", self.on_return_pressed)
        self.send_btn = _accent_button(frame, self._text("code_send"), self.submit_prompt, color, padx=18, pady=8, font=("Segoe UI", 10, "bold"))
        self.send_btn.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_activity(self, parent):
        color = self.colors
        frame = tk.Frame(parent, bg=color["panel"], width=260)
        frame.pack_propagate(False)
        tk.Label(frame, text=self._text("code_activity"), bg=color["panel"], fg=color["foreground"], font=("Segoe UI", 10, "bold"), anchor="w", padx=8, pady=8).pack(fill=tk.X)
        self.task_var = tk.StringVar(value=self._text("code_no_task"))
        tk.Label(frame, textvariable=self.task_var, bg=color["input"], fg=color["foreground"], wraplength=230, justify=tk.LEFT, anchor="w", padx=8, pady=8).pack(fill=tk.X, padx=8, pady=(0, 8))
        self.activity_progress = ttk.Progressbar(frame, maximum=100)
        self.activity_progress.pack(fill=tk.X, padx=8, pady=(0, 8))
        tk.Label(frame, text=self._text("code_activity_log"), bg=color["panel"], fg=color["muted"], font=("Segoe UI", 8, "bold"), anchor="w", padx=8).pack(fill=tk.X)
        self.action_log = tk.Text(frame, bg=color["background"], fg=color["foreground"], font=("Consolas", 8), wrap=tk.WORD, bd=0, padx=8, pady=8, state=tk.DISABLED)
        self.action_log.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.build_var = tk.StringVar(value=self._text("code_build_test") + ": —")
        tk.Label(frame, textvariable=self.build_var, bg=color["panel"], fg=color["muted"], font=("Segoe UI", 8), anchor="w", padx=8).pack(fill=tk.X)
        tk.Label(frame, text=self._text("code_errors"), bg=color["panel"], fg=color["muted"], font=("Segoe UI", 8, "bold"), anchor="w", padx=8).pack(fill=tk.X)
        self.error_text = tk.Text(frame, height=6, bg=color["background"], fg=color["error"], font=("Consolas", 8), wrap=tk.WORD, bd=0, padx=8, pady=6, state=tk.DISABLED)
        self.error_text.pack(fill=tk.X, padx=6, pady=6)
        return frame

    def _apply_ttk_style(self):
        color = self.colors
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=color["background"], bordercolor=color["border"], tabmargins=(2, 2, 2, 0))
        style.configure("TNotebook.Tab", background=color["panel"], foreground=color["foreground"], padding=(10, 5))
        style.map("TNotebook.Tab", background=[("selected", color["input"])], foreground=[("selected", color["foreground"])])
        style.configure("Treeview", background=color["input"], foreground=color["foreground"], fieldbackground=color["input"], bordercolor=color["border"], rowheight=22)
        style.map("Treeview", background=[("selected", color["accent"])], foreground=[("selected", "#ffffff")])
        style.configure("TCombobox", fieldbackground=color["input"], foreground=color["foreground"], background=color["button"], arrowcolor=color["foreground"])
        style.configure("TProgressbar", background=color["accent"], troughcolor=color["input"], bordercolor=color["input"])

    def _permission_changed(self):
        self.settings["permission_mode"] = self.permission_var.get()
        if self.context:
            self.context.policy.mode = self.permission_var.get()
        self._append_log(self._text("code_permission") + ": " + self.permission_var.get())

    def on_open_settings(self):
        self.event_generate("<<CodeSettings>>")

    def toggle_explorer(self):
        self._explorer_visible = not self._explorer_visible
        if self._explorer_visible:
            self.explorer.pack(side=tk.LEFT, fill=tk.Y, before=self.explorer_toggle)
            self.explorer_toggle.configure(text="»")
        else:
            self.explorer.pack_forget()
            self.explorer_toggle.configure(text="«")

    def toggle_activity(self):
        self._activity_visible = not self._activity_visible
        if self._activity_visible:
            self.activity.pack(side=tk.RIGHT, fill=tk.Y, before=self.activity_toggle)
            self.activity_toggle.configure(text="«")
        else:
            self.activity.pack_forget()
            self.activity_toggle.configure(text="»")

    def new_terminal(self, session_id=None):
        pane = TerminalPane(self.terminal_notebook, self.terminal_notebook, self.terminals, self.context.workspace.root, self.context.policy, self.colors, self.lang, int(self.settings.get("command_timeout", 120)))
        self.terminal_notebook.select(pane)
        if session_id:
            pane.attach(session_id)
            self.terminal_panes[session_id] = pane
        return pane

    # ---------------------------------------------------------------- project

    def _refresh_all(self):
        self.project_label.configure(text=self.context.workspace.root.name)
        self.populate_tree()
        self.refresh_overview()
        self.refresh_plan()
        self.refresh_changes()
        self.refresh_transcript()
        self.recent_list.delete(0, tk.END)
        for path in getattr(self, "recent_files", []):
            self.recent_list.insert(tk.END, path)

    def populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        self.search_results.pack_forget()
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        root = self.tree.insert("", "end", text=self.context.workspace.root.name, open=True, values=(str(self.context.workspace.root),))
        self._populate_children(root, self.context.workspace.root, 0)

    def _populate_children(self, parent_id, path: Path, depth):
        if depth >= 4:
            return
        try:
            children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        except OSError:
            return
        for child in children:
            if self.context.workspace.is_ignored(child) or self.context.workspace.is_sensitive(child):
                continue
            node = self.tree.insert(parent_id, "end", text=child.name, values=(str(child),))
            if child.is_dir():
                self.tree.insert(node, "end", text="")

    def on_tree_expand(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        node = selection[0]
        path = Path(self.tree.set(node, "0"))
        if path.is_dir() and len(self.tree.get_children(node)) == 1 and not self.tree.item(self.tree.get_children(node)[0], "text"):
            self.tree.delete(*self.tree.get_children(node))
            self._populate_children(node, path, 0)

    def on_tree_open(self, _event):
        selection = self.tree.selection()
        if not selection:
            return
        path = Path(self.tree.set(selection[0], "0"))
        if path.is_dir():
            self.on_tree_expand(None)
        else:
            self.open_file(path)

    def search_files(self):
        query = self.file_search.get().strip()
        if not query:
            self.populate_tree()
            return
        result = self.context.workspace.search_files(query, max_results=200)
        self.tree.pack_forget()
        self.search_results.delete(0, tk.END)
        for path in result.get("matches", []):
            self.search_results.insert(tk.END, path)
        self.search_results.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def on_search_open(self, _event):
        selection = self.search_results.curselection()
        if selection:
            self.open_file(Path(self.search_results.get(selection[0])))

    def on_recent_open(self, _event):
        selection = self.recent_list.curselection()
        if selection:
            self.open_file(Path(self.recent_list.get(selection[0])))

    def open_file(self, path: Path):
        try:
            content = self.context.workspace.read_text(str(path), allow_sensitive=True)
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        except (OSError, ValueError) as exc:
            messagebox.showerror(self._text("code_editor_tab"), str(exc), parent=self)
            return
        self.editor_path = path
        self.editor.load(path, content, digest)
        self.tabs.select(self.editor)
        if not hasattr(self, "recent_files"):
            self.recent_files = []
        self.recent_files = [str(path)] + [item for item in self.recent_files if item != str(path)][:9]
        self.recent_list.delete(0, tk.END)
        for item in self.recent_files:
            self.recent_list.insert(tk.END, item)

    def save_editor_file(self, path: Path, content: str, expected_hash: str | None):
        result = self.context.workspace.write_file(str(path), content, expected_hash)
        if result.get("status") == "SUCCESS":
            self._append_log(self._text("code_saved") + ": " + str(path))
            self.refresh_changes()
            self.populate_tree()
        else:
            messagebox.showerror(self._text("code_save"), result.get("message", "Save failed"), parent=self)
        return result

    def editor_modified(self, revert=False, _path=None):
        if revert and self.editor_path:
            self.open_file(self.editor_path)

    def new_file(self):
        name = simpledialog.askstring(self._text("code_new_file"), self._text("code_new_file"), parent=self)
        if name:
            result = self.context.workspace.create_file(name, "")
            if result.get("status") == "SUCCESS":
                self.open_file(self.context.workspace.safe_path(name, allow_sensitive=True))
                self.populate_tree()
            else:
                messagebox.showerror(self._text("code_new_file"), result.get("message", ""), parent=self)

    def new_folder(self):
        name = simpledialog.askstring(self._text("code_new_folder"), self._text("code_new_folder"), parent=self)
        if name:
            result = self.context.workspace.create_directory(name)
            if result.get("status") != "SUCCESS":
                messagebox.showerror(self._text("code_new_folder"), result.get("message", ""), parent=self)
            self.populate_tree()

    def on_browse_workspace(self):
        if self.is_busy:
            self.status_var.set(self._text("code_busy_wait"))
            return
        chosen = filedialog.askdirectory(initialdir=str(self.context.workspace.root), title=self._text("code_select_workspace"))
        if not chosen:
            return
        self.conv["workspace"] = chosen
        self.store.save_conversation(self.conv)
        self._set_conversation(self.conv)
        self._refresh_all()
        self._append_message(self._text("code_system"), self._text("code_workspace_changed").format(workspace=chosen), "system")

    def on_add_ref_dir(self):
        chosen = filedialog.askdirectory(initialdir=str(self.context.workspace.root), title=self._text("code_select_workspace"))
        if not chosen:
            return
        resolved = str(Path(chosen).resolve())
        if resolved not in self.extra_dirs:
            self.extra_dirs.append(resolved)
            self.conv["extra_dirs"] = list(self.extra_dirs)
            self.store.save_conversation(self.conv)
            from gd_core.coding_tools import set_extra_dirs
            set_extra_dirs(self.extra_dirs)
            self.session.rebuild_config()
            self._append_log(self._text("code_refs_label") + " " + resolved)

    # ---------------------------------------------------------------- changes

    def refresh_changes(self):
        self.change_tree.delete(*self.change_tree.get_children())
        for change in self.context.workspace.tracker.changes:
            self.change_tree.insert("", "end", iid=change.id, values=(change.status, change.operation, change.path))
        if not self.context.workspace.tracker.changes:
            self.diff_text.delete("1.0", tk.END)
            self.diff_text.insert(tk.END, self._text("code_no_changes"))

    def show_selected_diff(self, _event=None):
        selection = self.change_tree.selection()
        if not selection:
            return
        change = self.context.workspace.tracker.get(selection[0])
        if change is None:
            return
        self.diff_text.delete("1.0", tk.END)
        self.diff_text.insert(tk.END, change.diff or get_text("code_binary_change", self.lang))
        for tag, pattern in (("add", r"^\+[^+]"), ("remove", r"^-[^-]")):
            for match in re.finditer(pattern, change.diff, re.M):
                self.diff_text.tag_add(tag, f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def undo_last_change(self):
        changes = [change for change in self.context.workspace.tracker.changes if change.status not in {"rejected", "undone"}]
        if not changes:
            return
        result = self.context.workspace.tracker.undo(changes[-1].id)
        self._append_log(result.get("message", ""))
        self.refresh_changes()
        self.populate_tree()

    def accept_selected_change(self):
        selection = self.change_tree.selection()
        if selection:
            self.context.workspace.tracker.accept(selection[0])
            self.refresh_changes()

    def reject_selected_change(self):
        selection = self.change_tree.selection()
        if selection:
            result = self.context.workspace.tracker.undo(selection[0])
            self._append_log(result.get("message", ""))
            self.refresh_changes()
            self.populate_tree()

    def refresh_plan(self):
        self.plan_tree.delete(*self.plan_tree.get_children())
        data = self.plan.to_dict()
        for index, step in enumerate(data["steps"], 1):
            self.plan_tree.insert("", "end", values=(step["status"], f"{index}. {step['title']}" + (f" — {step['note']}" if step["note"] else "")))
        self.plan_progress["value"] = data["progress"] * 100
        self.activity_progress["value"] = data["progress"] * 100
        self.plan_progress_label.configure(text=f"{data['completed']} / {data['total']}")
        self.task_var.set(data["request"] or self._text("code_no_task"))

    def refresh_overview(self):
        try:
            project = inspect_project(self.context.workspace.root)
            index = getattr(self.context.workspace, "_project_index", None)
            index_text = ""
            if index:
                summary = index.summary()
                index_text = f"\nIndex: {summary['files']} files, {summary['symbols']} symbols"
            text = project["summary"] + index_text + "\n\nCommands:\n" + "\n".join(f"- {item['label']}: {item['command']}" for item in project["commands"])
            if project.get("instructions"):
                text += "\n\nProject instructions loaded from GD_ASSISTANT.md / AGENTS.md."
        except Exception as exc:
            text = str(exc)
        self.overview_text.delete("1.0", tk.END)
        self.overview_text.insert(tk.END, text)

    # ---------------------------------------------------------------- events

    def _queue_core_event(self, event):
        self.after(0, lambda: self._handle_core_event(event))

    def _handle_core_event(self, event):
        kind = event.get("type")
        if kind == "tool_start":
            self._append_log(f"→ {event.get('tool')} {event.get('arguments')}")
        elif kind == "tool_end":
            result = event.get("result") or {}
            self._append_log(f"← {event.get('tool')}: {result.get('status')} {str(result.get('message', ''))[:300]}")
            if result.get("status") == "FAILURE":
                self._append_error(str(result.get("message", "")))
            if event.get("tool") in {"create_file", "write_file", "edit_file", "delete_file", "move_file", "rename_file"}:
                self.refresh_changes()
                self.populate_tree()
                path = (event.get("arguments") or {}).get("file_path")
                if path and self.editor_path and self.editor_path.name == Path(path).name:
                    self.editor_modified(revert=True)
            if event.get("tool") in {"run_terminal_command", "start_terminal", "git_status"}:
                status = "passed" if result.get("status") == "SUCCESS" else "failed"
                self.build_var.set(self._text("code_build_test") + f": {status}")
        elif kind == "terminal_output":
            session_id = event.get("session_id")
            pane = self.terminal_panes.get(session_id)
            if pane is None:
                pane = self.new_terminal(session_id)
            pane.append(str(event.get("text", "")))
        elif kind == "plan":
            self.refresh_plan()
        elif kind == "checkpoint":
            self._append_log(f"Checkpoint: {event.get('status')}")

    def request_approval(self, title, details):
        result_queue: queue.Queue = queue.Queue()
        try:
            self.after(0, lambda: result_queue.put(messagebox.askyesno(title, details, parent=self)))
        except tk.TclError:
            return False
        try:
            return bool(result_queue.get(timeout=300))
        except queue.Empty:
            return False

    def on_agent_status(self, message):
        self.after(0, lambda: (self._append_log(message), self.status_var.set(message)))

    def _append_log(self, text):
        self.action_log.configure(state=tk.NORMAL)
        self.action_log.insert(tk.END, str(text) + "\n")
        self.action_log.see(tk.END)
        self.action_log.configure(state=tk.DISABLED)

    def _append_error(self, text):
        self.error_text.configure(state=tk.NORMAL)
        self.error_text.insert(tk.END, str(text) + "\n")
        self.error_text.see(tk.END)
        self.error_text.configure(state=tk.DISABLED)

    # ---------------------------------------------------------------- conversation

    def load_conversation(self, conversation_id):
        if self.is_busy:
            self.status_var.set(self._text("code_busy_wait"))
            return
        conv = self.store.load_conversation(conversation_id)
        if conv is not None and conv.get("type") == "code":
            self._set_conversation(conv)
            self._refresh_all()

    def on_new_project(self):
        if self.is_busy:
            return
        conv = self.store.create_conversation("code", title=self._text("sidebar_new_project"), workspace=str(self.context.workspace.root))
        self._set_conversation(conv)
        self._refresh_all()

    def on_open_project(self, conversation_id):
        if conversation_id:
            self.load_conversation(conversation_id)
        else:
            self.on_new_project()

    def _persist_message(self, role, content):
        if self.conv:
            self.store.append_message(self.conv["id"], role, content)

    def refresh_transcript(self):
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.delete("1.0", tk.END)
        self.transcript.configure(state=tk.DISABLED)
        for message in (self.conv or {}).get("messages") or []:
            if message.get("role") == "user":
                self._append_message(self._text("code_you"), str(message.get("content", "")), "user")
            else:
                self._append_markdown_message(self._text("code_agent_name"), str(message.get("content", "")), "agent")
        if not (self.conv or {}).get("messages"):
            self._append_message(self._text("code_system"), self._text("code_welcome").format(workspace=self.context.workspace.root, model=self.model), "system")

    def _append_message(self, speaker, text, tag="agent"):
        self.transcript.configure(state=tk.NORMAL)
        if speaker:
            self.transcript.insert(tk.END, f"{speaker}:\n", tag)
        self.transcript.insert(tk.END, f"{text}\n\n", tag)
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _append_markdown_message(self, speaker, text, tag="agent"):
        self.transcript.configure(state=tk.NORMAL)
        if speaker:
            self.transcript.insert(tk.END, f"{speaker}:\n", tag)
        insert_markdown(self.transcript, text, base_tag=tag)
        self.transcript.insert(tk.END, "\n\n")
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _begin_stream_block(self):
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.insert(tk.END, f"{self._text('code_agent_name')}:\n", "agent")
        self.transcript.mark_set("stream_start", "end-1c")
        self.transcript.mark_gravity("stream_start", tk.LEFT)
        self.transcript.configure(state=tk.DISABLED)

    def _render_stream_text(self):
        self._stream_render_job = None
        if "stream_start" not in self.transcript.mark_names():
            return
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.delete("stream_start", "end-1c")
        insert_markdown(self.transcript, "".join(self.stream_pieces), base_tag="agent")
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _schedule_stream_render(self):
        if self._stream_render_job is None:
            self._stream_render_job = self.after(50, self._render_stream_text)

    # ---------------------------------------------------------------- attachments/input

    def on_attach_files(self):
        chosen = filedialog.askopenfilenames(parent=self, initialdir=str(self.context.workspace.root), title=self._text("attach_files_title"))
        for item in chosen:
            path = Path(item)
            if path not in self.pending_files:
                self.pending_files.append(path)
        self._refresh_attachments()

    def clear_attachments(self):
        self.pending_files.clear()
        self._refresh_attachments()

    def remove_attachment(self, index):
        if 0 <= index < len(self.pending_files):
            self.pending_files.pop(index)
        self._refresh_attachments()

    def _refresh_attachments(self):
        if not self.pending_files:
            self.attach_strip.pack_forget()
            return
        self.attach_strip.refresh(self.pending_files)
        if not self.attach_strip.winfo_manager():
            self.attach_strip.pack(side=tk.TOP, fill=tk.X, pady=(0, 6), before=self.attach_btn)

    def on_return_pressed(self, event):
        if not (event.state & 0x0001):
            self.submit_prompt()
            return "break"
        return None

    def submit_prompt(self):
        if self.is_busy:
            return
        prompt = self.input_box.get("1.0", tk.END).strip()
        files = list(self.pending_files)
        if not prompt and not files:
            return
        self.input_box.delete("1.0", tk.END)
        self.clear_attachments()
        plan_only = False
        read_only = False
        if prompt.startswith("/"):
            result = self.router.route(prompt)
            if result.text:
                self._append_message(self._text("code_system"), result.text, "system")
            if result.action == "stop":
                self.stop_agent()
            elif result.action == "exit":
                self.winfo_toplevel().destroy()
            elif result.action == "workspace":
                if result.payload.get("path") and Path(result.payload["path"]).is_dir():
                    self.conv["workspace"] = result.payload["path"]
                    self.store.save_conversation(self.conv)
                    self._set_conversation(self.conv)
                    self._refresh_all()
                else:
                    self._append_message(self._text("code_system"), self._text("code_cli_cd_usage"), "system")
            elif result.action == "terminal":
                pane = self.new_terminal()
                pane.command.insert(0, result.command)
                pane.start_command()
            if not result.prompt:
                return
            prompt = result.prompt
            plan_only = result.plan_only
            read_only = result.read_only
        display = prompt
        if files:
            display += "\n" + display_summary(files)
        request_text, binary_paths = prepare_message(prompt, files, debug=self.debug)
        self._append_message(self._text("code_you"), display, "user")
        self._persist_message("user", request_text)
        self._start_agent(request_text, binary_paths, files, plan_only=plan_only, read_only=read_only)

    def _start_agent(self, request_text, binary_paths, files, plan_only=False, read_only=False):
        self.is_busy = True
        self.stop_event = threading.Event()
        self.stream_pieces.clear()
        self.send_btn.configure(text=self._text("btn_stop"), command=self.stop_agent, bg=self.colors["error"], activebackground=self.colors["error"])
        self.status_var.set(self._text("code_agent_working"))
        self.task_var.set(request_text[:240])
        self._begin_stream_block()
        streamed = False

        def on_text(piece):
            nonlocal streamed
            streamed = True
            self.stream_pieces.append(piece)
            self.after(0, self._schedule_stream_render)

        def run_thread():
            had_error = False
            try:
                extra_parts = load_binary_parts(binary_paths, debug=self.debug) if binary_paths else None
                response = self.session.execute_turn(request_text, on_text=on_text, stop_event=self.stop_event, extra_parts=extra_parts, plan_only=plan_only, read_only=read_only)
            except Exception as exc:
                response = self._text("code_execution_error").format(error=exc)
                had_error = True

            def finish():
                self.stop_event = None
                if self._stream_render_job is not None:
                    self.after_cancel(self._stream_render_job)
                self._render_stream_text()
                self.transcript.configure(state=tk.NORMAL)
                if not streamed or had_error:
                    if had_error:
                        self.transcript.insert(tk.END, response, "error")
                    else:
                        insert_markdown(self.transcript, response, base_tag="agent")
                self.transcript.insert(tk.END, "\n\n")
                self.transcript.configure(state=tk.DISABLED)
                self.transcript.see(tk.END)
                if "stream_start" in self.transcript.mark_names():
                    self.transcript.mark_unset("stream_start")
                if response:
                    self._persist_message("assistant", response)
                self.is_busy = False
                self.send_btn.configure(text=self._text("code_send"), command=self.submit_prompt, bg=self.colors["accent"], activebackground=self.colors["accent_active"])
                self.status_var.set(self._text("code_ready"))
                self.refresh_plan()
                self.refresh_changes()
                self.refresh_overview()
                self.input_box.focus_set()
            self.after(0, finish)
        threading.Thread(target=run_thread, daemon=True).start()

    def stop_agent(self):
        if self.stop_event is not None:
            self.stop_event.set()
        self.terminals.stop_all()
        self.status_var.set(self._text("status_stopping"))

    def clear_transcript(self):
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.delete("1.0", tk.END)
        self.transcript.configure(state=tk.DISABLED)


class CodeAgentGUI:
    def __init__(self, client, model="gemini-3.5-flash-lite", start_dir=".", theme="dark", debug=False, lang="en", settings=None):
        self.root = tk.Tk()
        self.root.title(f"GD Assistant :: {get_text('mode_code', lang)}")
        self.root.geometry("1280x800")
        self.root.minsize(980, 600)
        self.root.configure(bg=get_theme(theme)["background"])
        self.panel = CodeAgentPanel(self.root, client, model=model, start_dir=start_dir, theme=theme, debug=debug, lang=lang, settings=settings)
        self.panel.pack(fill=tk.BOTH, expand=True)
        self.panel.bind("<<CodeSettings>>", lambda _e: self._open_settings())

    def _open_settings(self):
        messagebox.showinfo(get_text("settings_title", self.panel.lang), get_text("code_settings_hint", self.panel.lang), parent=self.root)

    def run(self):
        self.root.mainloop()


def launch_coding_gui(client, model="gemini-3.5-flash-lite", start_dir=".", theme="dark", debug=False, lang="en", settings=None):
    app = CodeAgentGUI(client, model=model, start_dir=start_dir, theme=theme, debug=debug, lang=lang, settings=settings)
    app.run()
