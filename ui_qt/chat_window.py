"""Qt glass chat window — phase 1 of the main-UI Tk → Qt migration.

The window is a dumb projector, deliberately: the Tk side keeps every piece
of logic (sessions, ConversationStore, streaming, voice, hotkeys) and drives
this widget through ``apply_op(op, payload)``. User gestures travel back as
``event`` emissions; the Tk side decides what they mean. No store or session
object ever crosses this boundary — rows, paths, and palettes arrive as plain
data.

The surface is a frameless translucent window (WA_TranslucentBackground +
FramelessWindowHint) whose glass is painted once per paint: stacked soft
shadow, rounded panel with a vertical gradient at near-opaque alpha, hairline
border + top edge highlight — the same material recipe as ``ui_qt.menu`` so
menus and window read as one system. The transcript is a QTextBrowser with a
transparent background; markdown goes in through a temporary QTextDocument
(``MarkdownDialectGitHub``) rendered as a fragment, then a restyle pass walks
the inserted blocks to theme fenced code (``nonBreakableLines()``) and links.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEvent,
    QEasingCurve,
    QPoint,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPixmap,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizeGrip,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from gd_core.translations import get_text
from ui_qt.menu import PopupMenu, paint_glass_panel
from ui_qt.motion import RiseEntrance, smooth_line

# Glass material (mirrors ui_qt.menu so popups and window share one recipe).
SHADOW_MARGIN = 18
SHADOW_OFFSET_Y = 3
SHADOW_STEPS = 10
SHADOW_ALPHA = 7  # per layer; overlapping layers fade toward the edges
PANEL_RADIUS = 16
SIDEBAR_RADIUS = 12

# Entrance motion: MOTION_STANDARD with OutCubic (Qt design skill).
ENTRANCE_MS = 170
ENTRANCE_RISE_PX = 10
COLLAPSE_MS = 150

DEFAULT_SIZE = (840, 620)
MIN_SIZE = (660, 480)
SIDEBAR_W = 216
RAIL_W = 24
CHIP_MAX_CHARS = 26
MAX_VISIBLE_CHIPS = 5


def _rgba(color: QColor, alpha: int) -> str:
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha})"


def _shorten(name: str) -> str:
    if len(name) <= CHIP_MAX_CHARS:
        return name
    return name[: CHIP_MAX_CHARS - 9] + "…" + name[-8:]


def chat_stylesheet(palette: dict[str, str]) -> str:
    """One stylesheet for the window and its children.

    Every text-bearing rule is id-scoped on purpose: the sheet cascades into
    parented dialogs (QMessageBox/QInputDialog), and a bare ``QLabel`` rule
    would repaint dialog text in the wrong theme colors.
    """
    foreground = QColor(palette["foreground"])
    accent = QColor(palette["accent"])
    error = QColor(palette["error"])
    panel = QColor(palette["panel"])
    light = panel.lightness() > 128
    sidebar_tint = panel.darker(103) if light else panel.darker(112)
    return f"""
    #chatRoot {{ background: transparent; }}
    QLabel#headerTitle {{ color: {palette["foreground"]}; font-size: 10pt; font-weight: 600; }}
    QPushButton#headerButton {{
        background: transparent;
        color: {palette["foreground"]};
        border: none;
        border-radius: 8px;
        padding: 5px 12px;
        font-size: 10pt;
    }}
    QPushButton#headerButton:hover {{ background: {_rgba(foreground, 26)}; }}
    QPushButton#headerButton:pressed {{ background: {_rgba(foreground, 44)}; }}
    QPushButton#windowButton, QPushButton#closeButton {{
        background: transparent;
        color: {palette["muted"]};
        border: none;
        border-radius: 7px;
        min-width: 26px;
        max-width: 26px;
        min-height: 24px;
        font-size: 10pt;
    }}
    QPushButton#windowButton:hover {{ background: {_rgba(foreground, 26)}; color: {palette["foreground"]}; }}
    QPushButton#closeButton:hover {{ background: {_rgba(error, 46)}; color: {palette["error"]}; }}
    #chatSidebar {{ background: {_rgba(sidebar_tint, 150)}; border-radius: {SIDEBAR_RADIUS}px; }}
    QPushButton#railToggle {{
        background: {palette["button"]};
        color: {palette["foreground"]};
        border: none;
        border-radius: 6px;
        font-size: 9pt;
    }}
    QPushButton#railToggle:hover {{ background: {palette["button_active"]}; }}
    QPushButton#newChatButton {{
        background: {palette["accent"]};
        color: white;
        border: none;
        border-radius: 8px;
        padding: 6px;
        font-size: 9pt;
        font-weight: 600;
    }}
    QPushButton#newChatButton:hover {{ background: {palette["accent_active"]}; }}
    QLabel#sectionLabel {{ color: {palette["muted"]}; font-size: 8pt; font-weight: 600; }}
    QListWidget#chatList {{ background: transparent; border: none; outline: none; font-size: 9pt; }}
    QListWidget#chatList::item {{ color: {palette["foreground"]}; padding: 7px 10px; border-radius: 8px; }}
    QListWidget#chatList::item:hover {{ background: {_rgba(foreground, 22)}; }}
    QListWidget#chatList::item:selected {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {accent.lighter(112).name()}, stop:1 {accent.darker(106).name()});
        color: white;
    }}
    QCheckBox#archivedCheck {{ color: {palette["muted"]}; font-size: 8pt; spacing: 6px; }}
    QCheckBox#archivedCheck::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {palette["border"]};
        border-radius: 4px;
        background: {_rgba(QColor(palette["input"]), 200)};
    }}
    QCheckBox#archivedCheck::indicator:checked {{ background: {palette["accent"]}; border-color: {palette["accent"]}; }}
    QTextBrowser#transcript {{
        background: transparent;
        border: none;
        padding: 2px 4px;
        color: {palette["foreground"]};
        font-size: 10pt;
    }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {_rgba(foreground, 60)}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: {_rgba(foreground, 96)}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QWidget#chipsRow {{ background: transparent; }}
    QWidget#chip {{
        background: {_rgba(QColor(palette["input"]), 170)};
        border: 1px solid {palette["border"]};
        border-radius: 9px;
    }}
    QLabel#chipName {{ color: {palette["foreground"]}; font-size: 8pt; }}
    QPushButton#chipClose {{
        background: transparent;
        border: none;
        color: {palette["muted"]};
        font-size: 8pt;
        padding: 0px 2px;
    }}
    QPushButton#chipClose:hover {{ color: {palette["error"]}; }}
    QLabel#chipMore {{ color: {palette["muted"]}; font-size: 8pt; }}
    QPushButton#clearChips {{
        background: transparent;
        border: none;
        color: {palette["muted"]};
        font-size: 8pt;
        padding: 0px 6px;
    }}
    QPushButton#clearChips:hover {{ color: {palette["foreground"]}; }}
    QLineEdit#chatInput {{
        background: {_rgba(QColor(palette["input"]), 205)};
        color: {palette["foreground"]};
        border: 1px solid {palette["border"]};
        border-radius: 10px;
        padding: 7px 12px;
        selection-background-color: {palette["accent"]};
        selection-color: white;
    }}
    QLineEdit#chatInput:focus {{ border: 1px solid {palette["accent"]}; }}
    QLineEdit#chatInput:disabled {{ color: {palette["muted"]}; }}
    QPushButton#attachButton {{
        background: {_rgba(QColor(palette["button"]), 205)};
        color: {palette["foreground"]};
        border: none;
        border-radius: 10px;
        font-size: 13pt;
        padding-bottom: 3px;
        min-width: 38px;
        max-width: 38px;
        min-height: 32px;
    }}
    QPushButton#attachButton:hover {{ background: {_rgba(QColor(palette["button_active"]), 225)}; }}
    QPushButton#attachButton:disabled {{ color: {palette["muted"]}; }}
    QPushButton#sendButton {{
        background: {palette["accent"]};
        color: white;
        border: none;
        border-radius: 10px;
        padding: 7px 18px;
        font-weight: 600;
    }}
    QPushButton#sendButton:hover {{ background: {accent.lighter(112).name()}; }}
    QPushButton#sendButton[stop="true"] {{ background: {palette["error"]}; }}
    QPushButton#sendButton[stop="true"]:hover {{ background: {error.lighter(110).name()}; }}
    QPushButton#micButton {{
        background: {_rgba(QColor(palette["button"]), 205)};
        color: {palette["foreground"]};
        border: none;
        border-radius: 10px;
        padding: 7px 14px;
        min-width: 88px;
    }}
    QPushButton#micButton:hover {{ background: {_rgba(QColor(palette["button_active"]), 225)}; }}
    QPushButton#micButton:disabled {{ color: {palette["muted"]}; }}
    QLabel#statusLabel {{ color: {palette["muted"]}; font-size: 9pt; }}
    """


class HeaderBar(QWidget):
    """Draggable header strip: File/Mode buttons, centred title, window buttons.

    Presses on the strip itself (or its QLabel, which ignores mouse events)
    drag the frameless window; the buttons consume their own clicks. The
    File/Mode buttons report their global rects along with each request so
    the Tk side can replay menu-dismiss clicks that the popup's mouse grab
    swallows (one-click menu switching).
    """

    fileRequested = Signal()
    modeRequested = Signal()
    menuRequested = Signal(str, dict)

    def __init__(self, lang: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lang = lang
        self._drag_offset: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.file_button = QPushButton(get_text("menu_file", lang))
        self.file_button.setObjectName("headerButton")
        self.file_button.clicked.connect(lambda _checked=False: self._request_menu("file"))
        self.mode_button = QPushButton(get_text("menu_mode", lang))
        self.mode_button.setObjectName("headerButton")
        self.mode_button.clicked.connect(lambda _checked=False: self._request_menu("mode"))

        self.title_label = QLabel(get_text("mode_chat", lang))
        self.title_label.setObjectName("headerTitle")
        self.title_label.setAlignment(Qt.AlignCenter)

        minimize_button = QPushButton("\u2014")
        minimize_button.setObjectName("windowButton")
        minimize_button.clicked.connect(lambda _checked=False: self.window().showMinimized())
        self.maximize_button = QPushButton("\u25A1")
        self.maximize_button.setObjectName("windowButton")
        self.maximize_button.setToolTip(get_text("tip_maximize", lang))
        self.maximize_button.clicked.connect(
            lambda _checked=False: self.window().toggle_maximize()
        )
        close_button = QPushButton("\u2715")
        close_button.setObjectName("closeButton")
        close_button.clicked.connect(lambda _checked=False: self.window().close())

        layout.addWidget(self.file_button)
        layout.addWidget(self.mode_button)
        layout.addStretch(1)
        layout.addWidget(self.title_label)
        layout.addStretch(1)
        layout.addWidget(minimize_button)
        layout.addWidget(self.maximize_button)
        layout.addWidget(close_button)

    def set_title(self, text: str) -> None:
        self.title_label.setText(text)

    def set_maximized(self, maximized: bool) -> None:
        self.maximize_button.setText("\u2750" if maximized else "\u25A1")
        self.maximize_button.setToolTip(
            get_text("tip_restore" if maximized else "tip_maximize", self._lang)
        )

    def _request_menu(self, kind: str) -> None:
        self.menuRequested.emit(kind, {
            "file": self._global_rect(self.file_button),
            "mode": self._global_rect(self.mode_button),
        })

    @staticmethod
    def _global_rect(button: QPushButton) -> list[int]:
        top_left = button.mapToGlobal(QPoint(0, 0))
        return [top_left.x(), top_left.y(), button.width(), button.height()]

    # -- window drag ---------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._drag_offset is not None and event.buttons() & Qt.LeftButton
                and not self.window().isMaximized()):
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.window().toggle_maximize()
        else:
            super().mouseDoubleClickEvent(event)


class ChatSidebar(QWidget):
    """Saved-chat rail: list, New button, archived toggle, context menu.

    Projection only — rows arrive as plain data via ``set_rows``; every store
    mutation is reported to the Tk side, which owns ConversationStore. The
    dialogs (rename input, delete/convert confirms, folder pick) run here so
    nothing has to parent to the hidden Tk root.
    """

    openRequested = Signal(object)
    newRequested = Signal()
    renameRequested = Signal(str, str)
    statusRequested = Signal(str, str)
    deleteRequested = Signal(str)
    convertRequested = Signal(str, str)
    archivedToggled = Signal(bool)

    def __init__(
        self,
        palette: dict[str, str],
        lang: str,
        reduced_motion: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chatSidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._palette = dict(palette)
        self._lang = lang
        self._reduced_motion = reduced_motion
        self._rows: list[dict] = []
        self._current: str | None = None
        self._loading = False
        self._expanded = True
        self._ctx_menu: PopupMenu | None = None
        self._collapse_start = float(SIDEBAR_W)
        self._collapse_target = float(SIDEBAR_W)
        self._collapse = smooth_line(COLLAPSE_MS, self)
        self._collapse.setEasingCurve(QEasingCurve.OutCubic)
        self._collapse.valueChanged.connect(self._apply_collapse)
        self._build_ui()
        self.setFixedWidth(SIDEBAR_W)

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 6, 4, 6)
        outer.setSpacing(4)

        # Full-height handle pinned to the sidebar's left edge. A small
        # button in the content column used to drift to the vertical middle
        # whenever the column hid (a lone layout item absorbs free space).
        self._toggle_button = QPushButton("\u00ab")
        self._toggle_button.setObjectName("railToggle")
        self._toggle_button.setFixedWidth(RAIL_W - 8)
        self._toggle_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._toggle_button.clicked.connect(lambda _checked=False: self.toggle())
        outer.addWidget(self._toggle_button)
        # A lone fixed-width item absorbs the leftover space whenever the
        # content hides, which parked the handle mid-bar (it slid leftward
        # during the whole collapse); alignment pins it to the left edge.
        outer.setAlignment(self._toggle_button, Qt.AlignLeft)

        self._content = QWidget()
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self._new_button = QPushButton(get_text("sidebar_new_chat", self._lang))
        self._new_button.setObjectName("newChatButton")
        self._new_button.clicked.connect(lambda _checked=False: self.newRequested.emit())
        layout.addWidget(self._new_button)

        self._section_label = QLabel(get_text("sidebar_chats", self._lang))
        self._section_label.setObjectName("sectionLabel")
        layout.addWidget(self._section_label)

        self.list = QListWidget()
        self.list.setObjectName("chatList")
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        # Long titles elide with "…" instead of hard-clipping at the edge.
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.itemClicked.connect(self._row_clicked)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.list, 1)

        self._archived_check = QCheckBox(get_text("sidebar_show_archived", self._lang))
        self._archived_check.setObjectName("archivedCheck")
        self._archived_check.toggled.connect(
            lambda checked: self.archivedToggled.emit(bool(checked))
        )
        layout.addWidget(self._archived_check)

        outer.addWidget(self._content, 1)

    # -- data in -------------------------------------------------------------

    def set_rows(self, rows: list[dict], current: object) -> None:
        self._loading = True
        self._rows = [dict(row) for row in rows if isinstance(row, dict)]
        self._current = current if isinstance(current, str) else None
        self.list.clear()
        for index, row in enumerate(self._rows):
            item = QListWidgetItem(str(row.get("label") or "..."))
            item.setData(Qt.UserRole, row.get("id"))
            if row.get("title"):
                item.setToolTip(str(row["title"]))
            self.list.addItem(item)
            if row.get("id") == self._current:
                self.list.setCurrentRow(index)
        self._loading = False

    def apply_palette(self, palette: dict[str, str]) -> None:
        self._palette = dict(palette)

    # -- collapse ------------------------------------------------------------

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._toggle_button.setText("\u00ab" if self._expanded else "\u00bb")
        target = SIDEBAR_W if self._expanded else RAIL_W
        self._collapse.stop()
        if self._reduced_motion:
            self.setFixedWidth(target)
            return
        self._collapse_start = float(self.width())
        self._collapse_target = float(target)
        self._collapse.start()

    def _apply_collapse(self, fraction: float) -> None:
        width = self._collapse_start + (self._collapse_target - self._collapse_start) * fraction
        self.setFixedWidth(int(round(width)))

    # -- row interactions ----------------------------------------------------

    def _row_clicked(self, item: QListWidgetItem) -> None:
        if self._loading:
            return
        conv_id = item.data(Qt.UserRole)
        if conv_id is None or conv_id == self._current:
            return
        self.openRequested.emit(conv_id)

    def _row_for(self, conv_id: object) -> dict | None:
        for row in self._rows:
            if row.get("id") == conv_id:
                return row
        return None

    def _show_context_menu(self, position) -> None:
        item = self.list.itemAt(position)
        if item is None:
            return
        row = self._row_for(item.data(Qt.UserRole))
        if row is None:
            return
        conv_id = str(row.get("id"))
        archived = row.get("status") == "archived"

        menu = PopupMenu(self._palette, animate=not self._reduced_motion)
        menu.addAction(get_text("ctx_open", self._lang)).triggered.connect(
            lambda _checked=False: self.openRequested.emit(conv_id)
        )
        menu.addAction(get_text("ctx_rename", self._lang)).triggered.connect(
            lambda _checked=False: self._rename(row)
        )
        menu.addAction(
            get_text("ctx_unarchive" if archived else "ctx_archive", self._lang)
        ).triggered.connect(
            lambda _checked=False: self.statusRequested.emit(
                conv_id, "active" if archived else "archived"
            )
        )
        if not archived:
            menu.addSeparator()
            menu.addAction(get_text("ctx_to_code", self._lang)).triggered.connect(
                lambda _checked=False: self._convert(conv_id)
            )
        menu.addSeparator()
        menu.addAction(get_text("ctx_delete", self._lang)).triggered.connect(
            lambda _checked=False: self._delete(conv_id)
        )
        self._ctx_menu = menu
        menu.aboutToHide.connect(lambda m=menu: self._context_menu_closed(m))
        menu.popup_at_cursor()

    def _context_menu_closed(self, menu: PopupMenu) -> None:
        if self._ctx_menu is not menu:
            menu.deleteLater()
            return
        self._ctx_menu = None
        menu.deleteLater()

    def _rename(self, row: dict) -> None:
        conv_id = str(row.get("id"))
        current = str(row.get("title") or "")
        title, accepted = QInputDialog.getText(
            self, get_text("rename_chat_title", self._lang),
            get_text("rename_chat_title", self._lang), text=current,
        )
        if accepted:
            self.renameRequested.emit(conv_id, title.strip())

    def _delete(self, conv_id: str) -> None:
        confirmed = QMessageBox.question(
            self, get_text("ctx_delete", self._lang),
            get_text("delete_chat_confirm", self._lang),
        )
        if confirmed == QMessageBox.Yes:
            self.deleteRequested.emit(conv_id)

    def _convert(self, conv_id: str) -> None:
        confirmed = QMessageBox.question(
            self, get_text("ctx_to_code", self._lang),
            get_text("convert_confirm", self._lang),
        )
        if confirmed != QMessageBox.Yes:
            return
        directory = QFileDialog.getExistingDirectory(
            self, get_text("convert_pick_dir", self._lang)
        )
        if directory:
            self.convertRequested.emit(conv_id, directory)


class ChatWindow(QWidget):
    """Glass chat window. Ops in via apply_op, user intents out via event."""

    event = Signal(str, object)

    def __init__(
        self,
        palette: dict[str, str],
        lang: str = "en",
        opacity: float = 0.93,
        maximize_opaque: bool = True,
        reduced_motion: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chatRoot")
        self._lang = lang
        self._reduced_motion = reduced_motion
        self._palette = dict(palette)
        self._streaming = False
        self._stream_pos = 0
        self._stop_mode = False
        self._glass: QPixmap | None = None
        self._glass_key: tuple | None = None
        self._chip_widgets: list[QWidget] = []
        self._opacity = max(0.4, min(1.0, float(opacity or 1.0)))
        self._maximize_opaque = bool(maximize_opaque)
        self._maximized = False

        # WindowMinimizeButtonHint adds WS_MINIMIZEBOX, which the shell needs
        # for click-taskbar-button-to-minimize on this frameless window.
        self.setWindowFlags(
            Qt.Window | Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("GD Assistant")
        self.setFont(QFont("Segoe UI", 10))
        self.setMinimumSize(*MIN_SIZE)
        self.resize(*DEFAULT_SIZE)
        screen = QApplication.primaryScreen()
        if screen is not None:
            geometry = self.frameGeometry()
            geometry.moveCenter(screen.availableGeometry().center())
            self.move(geometry.topLeft())

        self._build_ui()
        self._apply_palette(self._palette)

        self._entrance = RiseEntrance(self, ENTRANCE_MS, ENTRANCE_RISE_PX)

    # -- construction --------------------------------------------------------

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(
            SHADOW_MARGIN + 16, SHADOW_MARGIN + 12, SHADOW_MARGIN + 16, SHADOW_MARGIN + 10
        )
        root_layout.setSpacing(10)

        self._header = HeaderBar(self._lang)
        self._header.menuRequested.connect(
            lambda kind, rects: self.event.emit("menu", {"kind": kind, "rects": rects})
        )
        root_layout.addWidget(self._header)

        body = QHBoxLayout()
        body.setSpacing(12)
        self.sidebar = ChatSidebar(self._palette, self._lang, self._reduced_motion)
        self.sidebar.openRequested.connect(lambda conv_id: self.event.emit("sidebar_open", conv_id))
        self.sidebar.newRequested.connect(lambda: self.event.emit("sidebar_new", None))
        self.sidebar.renameRequested.connect(
            lambda conv_id, title: self.event.emit("sidebar_rename", (conv_id, title))
        )
        self.sidebar.statusRequested.connect(
            lambda conv_id, status: self.event.emit("sidebar_status", (conv_id, status))
        )
        self.sidebar.deleteRequested.connect(
            lambda conv_id: self.event.emit("sidebar_delete", conv_id)
        )
        self.sidebar.convertRequested.connect(
            lambda conv_id, directory: self.event.emit("sidebar_convert", (conv_id, directory))
        )
        self.sidebar.archivedToggled.connect(
            lambda checked: self.event.emit("sidebar_archived", checked)
        )
        body.addWidget(self.sidebar)

        right_column = QVBoxLayout()
        right_column.setSpacing(8)

        self.transcript = QTextBrowser()
        self.transcript.setObjectName("transcript")
        self.transcript.setOpenExternalLinks(True)
        right_column.addWidget(self.transcript, 1)
        # Re-wraps from resizing or the sidebar collapsing change the scroll
        # range; track whether the view sits at the bottom so the range
        # handler can keep it pinned there (the "chat jumps up" bug).
        self._at_bottom = True
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.valueChanged.connect(self._track_bottom)
        scrollbar.rangeChanged.connect(self._stick_bottom)

        self._chips_row = QWidget()
        self._chips_row.setObjectName("chipsRow")
        self._chips_layout = QHBoxLayout(self._chips_row)
        self._chips_layout.setContentsMargins(2, 0, 2, 0)
        self._chips_layout.setSpacing(6)
        self._chips_row.hide()
        right_column.addWidget(self._chips_row)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.attach_button = QPushButton("+")
        self.attach_button.setObjectName("attachButton")
        self.attach_button.setToolTip(get_text("attach_files_title", self._lang))
        self.attach_button.clicked.connect(lambda _checked=False: self._pick_attachments())
        self.input_box = QLineEdit()
        self.input_box.setObjectName("chatInput")
        self.input_box.returnPressed.connect(self._handle_send)
        self.send_button = QPushButton(get_text("btn_send", self._lang))
        self.send_button.setObjectName("sendButton")
        self.send_button.clicked.connect(lambda _checked=False: self._handle_send())
        self.mic_button = QPushButton(get_text("btn_voice", self._lang))
        self.mic_button.setObjectName("micButton")
        self.mic_button.clicked.connect(lambda _checked=False: self.event.emit("mic", None))
        input_row.addWidget(self.attach_button)
        input_row.addWidget(self.input_box, 1)
        input_row.addWidget(self.send_button)
        input_row.addWidget(self.mic_button)
        right_column.addLayout(input_row)

        status_row = QHBoxLayout()
        self._status_label = QLabel(get_text("status_ready", self._lang))
        self._status_label.setObjectName("statusLabel")
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        status_row.addWidget(self._status_label, 1)
        status_row.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        right_column.addLayout(status_row)

        body.addLayout(right_column, 1)
        root_layout.addLayout(body, 1)

    # -- palette / glass -----------------------------------------------------

    def _apply_palette(self, palette: dict[str, str]) -> None:
        if not palette:
            return
        self._palette = dict(palette)
        self._is_light = QColor(palette["panel"]).lightness() > 128
        self._code_bg = QColor(palette["button_active"])
        inline_bg = QColor(palette["input"])
        inline_bg.setAlpha(180)
        self._inline_code_bg = inline_bg
        self._link_color = QColor(palette["accent"])
        self.setStyleSheet(chat_stylesheet(palette))
        self.sidebar.apply_palette(palette)
        self._restyle_range(0, self.transcript.document().characterCount())
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._glass_pixmap())
        painter.end()

    def _glass_pixmap(self) -> QPixmap:
        # The shadow stack and panel only change with the window size or the
        # palette, but a paint builds ten painter paths every frame — during
        # the collapse/entrance animations that cost lands on every tick.
        # Pre-render once and blit (skill #33: cache static visual assets).
        dpr = self.devicePixelRatioF()
        key = (
            self.width(),
            self.height(),
            dpr,
            self._palette.get("panel"),
            self._palette.get("border"),
            self._is_light,
            self._opacity,
            self._maximize_opaque,
            self._maximized,
        )
        if self._glass is not None and self._glass_key == key:
            return self._glass
        pixmap = QPixmap(
            max(1, int(round(self.width() * dpr))),
            max(1, int(round(self.height() * dpr))),
        )
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        # Slider 100% = alpha 255 (fully opaque); the shipped glass look is the
        # 0.93 config default.
        slider_alpha = int(round(255 * self._opacity))
        if self._maximized:
            # Fullscreen glass: square corners, no shadow. Opacity setting is
            # ignored so the panel reads as a wall — unless the setting is off.
            panel = self.rect()
            radius = 0
            shadow_steps = 0
            alpha = 255 if self._maximize_opaque else slider_alpha
        else:
            panel = self.rect().adjusted(
                SHADOW_MARGIN, SHADOW_MARGIN, -SHADOW_MARGIN - 1, -SHADOW_MARGIN - 1
            )
            radius = PANEL_RADIUS
            shadow_steps = SHADOW_STEPS
            alpha = slider_alpha
        base = QColor(self._palette["panel"])
        base.setAlpha(alpha)
        paint_glass_panel(
            painter, panel, base, QColor(self._palette["border"]), radius,
            shadow_steps, SHADOW_ALPHA, SHADOW_OFFSET_Y,
            gradient_light=106, gradient_dark=104, highlight_alpha=30,
        )
        painter.end()
        self._glass = pixmap
        self._glass_key = key
        return pixmap

    # -- maximize --------------------------------------------------------------

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowStateChange:
            maximized = self.isMaximized()
            if maximized != self._maximized:
                self._maximized = maximized
                self._header.set_maximized(maximized)
                self.update()
        super().changeEvent(event)

    # -- entrance motion -----------------------------------------------------

    def play_entrance(self) -> None:
        if self._reduced_motion:
            self.setWindowOpacity(1.0)
            return
        self.setWindowOpacity(0.0)
        self._entrance.play()

    def closeEvent(self, event) -> None:
        # Hide, don't die: the window is persistent and the tray/hotkeys
        # bring it back. Tk side is told so its state stays in sync.
        self.hide()
        self.event.emit("close", None)

    # -- ops in --------------------------------------------------------------

    def apply_op(self, op: str, payload: object = None) -> None:
        data = payload if isinstance(payload, dict) else {}
        if op == "open":
            palette = data.get("palette")
            if isinstance(palette, dict) and palette:
                self._apply_palette(palette)
            if data.get("opacity") is not None:
                self._set_opacity(data.get("opacity"))
            if data.get("maximize_opaque") is not None:
                self._set_maximize_opaque(data.get("maximize_opaque"))
            if data.get("title"):
                self.setWindowTitle(str(data["title"]))
            if data.get("header"):
                self._header.set_title(str(data["header"]))
        elif op == "show":
            self._op_show()
        elif op == "hide":
            self.hide()
        elif op == "opacity":
            self._set_opacity(data.get("value", 1.0))
            if data.get("maximize_opaque") is not None:
                self._set_maximize_opaque(data.get("maximize_opaque"))
        elif op == "title":
            if data.get("title"):
                self.setWindowTitle(str(data["title"]))
            if data.get("header"):
                self._header.set_title(str(data["header"]))
        elif op == "append":
            self._append_message(
                str(data.get("speaker", "")), str(data.get("text", "")),
                bool(data.get("markdown")),
            )
        elif op == "clear":
            self.transcript.clear()
            self._streaming = False
        elif op == "stream_begin":
            self._stream_begin()
        elif op == "stream_replace":
            self._stream_replace(str(data.get("text", "")))
        elif op == "stream_finish":
            self._stream_finish(
                str(data.get("text", "")), bool(data.get("markdown")),
                bool(data.get("append")),
            )
        elif op == "inputs":
            self._set_inputs(bool(data.get("enabled", True)))
        elif op == "send_mode":
            self._set_send_mode(bool(data.get("stop")))
        elif op == "mic_text":
            self.mic_button.setText(str(data.get("text", "")))
        elif op == "status":
            self._status_label.setText(str(data.get("text", "")))
        elif op == "focus_input":
            self.input_box.setFocus()
        elif op == "clear_input":
            self.input_box.clear()
        elif op == "rows":
            self.sidebar.set_rows(
                list(data.get("rows") or []), data.get("current")
            )
        elif op == "attachments":
            self._set_attachments([str(path) for path in (data.get("paths") or [])])
        elif op == "palette":
            self._apply_palette(data.get("palette") or {})

    def _set_opacity(self, value: object) -> None:
        try:
            self._opacity = max(0.4, min(1.0, float(value)))
        except (TypeError, ValueError):
            return
        self.update()

    def _set_maximize_opaque(self, value: object) -> None:
        self._maximize_opaque = bool(value)
        self.update()

    def _op_show(self) -> None:
        was_visible = self.isVisible()
        if self.isMinimized():
            if self._maximized:
                self.showMaximized()
            else:
                self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        if was_visible:
            self.setWindowOpacity(1.0)
        else:
            self.play_entrance()

    # -- transcript ----------------------------------------------------------

    def _transcript_cursor(self) -> QTextCursor:
        cursor = QTextCursor(self.transcript.document())
        cursor.movePosition(QTextCursor.End)
        return cursor

    def _speaker_color(self, speaker: str) -> QColor:
        if speaker.lower().startswith("you"):
            return QColor(self._palette["user"])
        return QColor(self._palette["accent"])

    def _insert_label(self, cursor: QTextCursor, speaker: str) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.DemiBold)
        fmt.setForeground(self._speaker_color(speaker))
        cursor.insertText(f"{speaker}: ", fmt)

    def _insert_markdown(self, cursor: QTextCursor, text: str) -> None:
        if not text:
            return
        start = cursor.position()
        temporary = QTextDocument()
        temporary.setMarkdown(text, QTextDocument.MarkdownDialectGitHub)
        cursor.insertFragment(QTextDocumentFragment(temporary))
        self._restyle_range(start, cursor.position())

    def _restyle_range(self, start: int, end: int) -> None:
        """Theme the freshly inserted range: fenced code blocks, inline code
        (the importer marks both with a Courier family), and links."""
        document = self.transcript.document()
        block = document.findBlock(start)
        while block.isValid() and block.position() <= end:
            if block.blockFormat().nonBreakableLines():
                block_format = QTextBlockFormat()
                block_format.setBackground(self._code_bg)
                QTextCursor(block).setBlockFormat(block_format)
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.length() > 0:
                    cursor = QTextCursor(document)
                    cursor.setPosition(fragment.position())
                    cursor.setPosition(
                        fragment.position() + fragment.length(), QTextCursor.KeepAnchor
                    )
                    fmt = fragment.charFormat()
                    if fmt.isAnchor():
                        link_format = QTextCharFormat()
                        link_format.setForeground(self._link_color)
                        link_format.setFontUnderline(True)
                        cursor.setCharFormat(link_format)
                    elif self._has_code_family(fmt):
                        code_format = QTextCharFormat()
                        code_format.setBackground(self._inline_code_bg)
                        code_format.setFontFamilies(["Consolas"])
                        cursor.setCharFormat(code_format)
                iterator += 1
            block = block.next()

    @staticmethod
    def _has_code_family(fmt: QTextCharFormat) -> bool:
        families = fmt.fontFamilies()
        if isinstance(families, str):
            families = [families]
        for name in families or []:
            lowered = str(name).lower()
            if "courier" in lowered or "mono" in lowered or "consolas" in lowered:
                return True
        return False

    def _track_bottom(self) -> None:
        scrollbar = self.transcript.verticalScrollBar()
        self._at_bottom = scrollbar.value() >= scrollbar.maximum()

    def _stick_bottom(self, _minimum: int, _maximum: int) -> None:
        if self._at_bottom:
            scrollbar = self.transcript.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _scroll_end(self) -> None:
        self.transcript.moveCursor(QTextCursor.End)
        scrollbar = self.transcript.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _reset_tail_formats(self) -> None:
        """Paragraph splits inherit the previous block's format, so a message
        ending in a fenced code block would leave its background on the
        separator gap and tint whatever comes next. Reset trailing empty
        paragraphs to the plain defaults."""
        block = self.transcript.document().lastBlock()
        while block.isValid() and not block.text():
            cursor = QTextCursor(block)
            cursor.setBlockFormat(QTextBlockFormat())
            cursor.setBlockCharFormat(QTextCharFormat())
            cursor.setCharFormat(QTextCharFormat())
            block = block.previous()

    def _append_message(self, speaker: str, text: str, markdown: bool) -> None:
        cursor = self._transcript_cursor()
        self._insert_label(cursor, speaker)
        if markdown:
            self._insert_markdown(cursor, text)
        else:
            cursor.insertText(text)
        cursor.insertText("\n\n")
        self._reset_tail_formats()
        self._scroll_end()

    def _stream_begin(self) -> None:
        cursor = self._transcript_cursor()
        self._insert_label(cursor, "GD")
        self._stream_pos = cursor.position()
        self._streaming = True
        self._scroll_end()

    def _stream_replace(self, text: str) -> None:
        if not self._streaming:
            return
        cursor = self._transcript_cursor()
        cursor.setPosition(self._stream_pos)
        cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cursor.removeSelectedText()
        cursor.setPosition(self._stream_pos)
        self._insert_markdown(cursor, text)
        self._scroll_end()

    def _stream_finish(self, text: str, markdown: bool, append: bool) -> None:
        cursor = self._transcript_cursor()
        if self._streaming:
            if not append:
                cursor.setPosition(self._stream_pos)
                cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                cursor.setPosition(self._stream_pos)
            if text:
                if markdown:
                    self._insert_markdown(cursor, text)
                else:
                    cursor.insertText(text)
        elif text:
            self._append_message("GD", text, markdown)
            self._streaming = False
            return
        cursor.insertText("\n\n")
        self._reset_tail_formats()
        self._streaming = False
        self._scroll_end()

    # -- inputs / chips ------------------------------------------------------

    def _set_inputs(self, enabled: bool) -> None:
        self.input_box.setEnabled(enabled)
        self.attach_button.setEnabled(enabled)
        self.mic_button.setEnabled(enabled)

    def _set_send_mode(self, stop: bool) -> None:
        self._stop_mode = stop
        self.send_button.setText(get_text("btn_stop" if stop else "btn_send", self._lang))
        self.send_button.setProperty("stop", "true" if stop else "false")
        self.send_button.style().unpolish(self.send_button)
        self.send_button.style().polish(self.send_button)

    def _handle_send(self) -> None:
        if self._stop_mode:
            self.event.emit("stop", None)
        else:
            self.event.emit("send", self.input_box.text())

    def _pick_attachments(self) -> None:
        paths, _filter = QFileDialog.getOpenFileNames(
            self, get_text("attach_files_title", self._lang)
        )
        if paths:
            self.event.emit("attach_files", paths)

    def _set_attachments(self, paths: list[str]) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._chip_widgets = []
        for index, path in enumerate(paths[:MAX_VISIBLE_CHIPS]):
            self._chip_widgets.append(self._make_chip(index, path))
        hidden = len(paths) - MAX_VISIBLE_CHIPS
        if hidden > 0:
            more = QLabel(f"+{hidden}")
            more.setObjectName("chipMore")
            self._chips_layout.addWidget(more)
        if paths:
            clear = QPushButton(get_text("attach_clear", self._lang))
            clear.setObjectName("clearChips")
            clear.clicked.connect(lambda _checked=False: self.event.emit("clear_attachments", None))
            self._chips_layout.addWidget(clear)
        self._chips_layout.addStretch(1)
        self._chips_row.setVisible(bool(paths))

    def _make_chip(self, index: int, path: str) -> QWidget:
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        chip = QWidget()
        chip.setObjectName("chip")
        chip.setAttribute(Qt.WA_StyledBackground, True)
        chip.setToolTip(path)
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(8, 2, 4, 2)
        layout.setSpacing(4)
        label = QLabel(_shorten(name))
        label.setObjectName("chipName")
        close = QPushButton("\u2715")
        close.setObjectName("chipClose")
        close.setFixedSize(14, 14)
        close.clicked.connect(
            lambda _checked=False, i=index: self.event.emit("remove_attachment", i)
        )
        layout.addWidget(label)
        layout.addWidget(close)
        self._chips_layout.addWidget(chip)
        return chip
