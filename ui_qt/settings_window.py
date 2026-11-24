"""Qt settings window — the Qt half of the Tk settings-dialog migration.

Views only, deliberately: the window receives the current values and the
app's palette from main.py, edits them, and emits one payload on save. The
Tk app stays the source of truth for config storage and side effects
(hotkey re-registration, live theme switch, session rebuild), so the Tk
and Qt settings dialogs share one apply path during the migration.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gd_core.translations import get_text

RAIL_WIDTH = 168
WINDOW_SIZE = (700, 440)

CATEGORIES = (
    "settings_tab_technical",
    "settings_tab_shortcuts",
    "settings_tab_voice",
    "settings_tab_appearance",
    "settings_tab_personality",
)


def build_stylesheet(palette: dict[str, str]) -> str:
    """One stylesheet generated from the app palette (no per-widget colors).

    Qt stylesheet "color" does not inherit into child widgets the way CSS
    does, so every text-bearing class gets an explicit rule — and the
    window background stays on the id selector: a window-wide QWidget
    background would paint over the rail's panel color.
    """
    return f"""
    #settingsRoot {{
        background: {palette["background"]};
    }}
    QLabel, QCheckBox, QRadioButton, QListWidget, QListWidget::item {{
        color: {palette["foreground"]};
    }}
    QLabel#railTitle {{ font-size: 15pt; font-weight: 700; }}
    QLabel#sectionLabel {{ font-weight: 600; }}
    QLabel#hint {{ color: {palette["muted"]}; font-style: italic; }}
    QLabel#error {{ color: {palette["error"]}; }}
    QFrame#rail {{ background: {palette["panel"]}; border-radius: 12px; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 8px 12px; border-radius: 8px; }}
    QListWidget::item:hover {{ background: {palette["button"]}; }}
    QListWidget::item:selected {{ background: {palette["accent"]}; color: white; }}
    QLineEdit, QPlainTextEdit, QComboBox {{
        background: {palette["input"]};
        color: {palette["foreground"]};
        border: 1px solid {palette["border"]};
        border-radius: 8px;
        padding: 6px 8px;
        selection-background-color: {palette["accent"]};
        selection-color: white;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {palette["accent"]}; }}
    QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{ color: {palette["muted"]}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QLineEdit {{ background: transparent; border: none; padding: 0; }}
    QComboBox QAbstractItemView {{
        background: {palette["input"]};
        color: {palette["foreground"]};
        border: 1px solid {palette["border"]};
        selection-background-color: {palette["accent"]};
        selection-color: white;
        outline: none;
    }}
    QCheckBox, QRadioButton {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {palette["border"]}; border-radius: 4px; background: {palette["input"]}; }}
    QCheckBox::indicator:checked {{ background: {palette["accent"]}; border-color: {palette["accent"]}; }}
    QRadioButton::indicator {{ width: 14px; height: 14px; border: 2px solid {palette["border"]}; border-radius: 9px; background: {palette["input"]}; }}
    QRadioButton::indicator:checked {{ background: white; border-color: {palette["accent"]}; }}
    QPushButton {{
        background: {palette["button"]};
        color: {palette["foreground"]};
        border: none;
        border-radius: 8px;
        padding: 8px 18px;
    }}
    QPushButton:hover {{ background: {palette["button_active"]}; }}
    QPushButton#accent {{ background: {palette["accent"]}; color: white; font-weight: 600; }}
    QPushButton#accent:hover {{ background: {palette["accent_active"]}; }}
    """


class ToggleSwitch(QAbstractButton):
    """On/off pill whose ON state carries a white check — fill alone read as
    ambiguous. Fully painted (no stylesheet): track, sliding knob, check."""

    TRACK_W = 36
    TRACK_H = 20

    def __init__(self, text: str, palette: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self._accent = QColor(palette["accent"])
        self._track_off = QColor(palette["input"])
        self._border = QColor(palette["border"])
        self._fg = QColor(palette["foreground"])
        self.toggled.connect(lambda _on: self.update())

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        width = self.TRACK_W + 8 + metrics.horizontalAdvance(self.text())
        return QSize(width, max(self.TRACK_H, metrics.height()) + 4)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QRectF(
            0.5, (self.height() - self.TRACK_H) / 2, self.TRACK_W, self.TRACK_H
        )
        on = self.isChecked()
        radius = self.TRACK_H / 2
        if on:
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._accent)
            painter.drawRoundedRect(track, radius, radius)
        else:
            painter.setPen(QPen(self._border, 1))
            painter.setBrush(self._track_off)
            inner = track.adjusted(1, 1, -0.5, -0.5)
            painter.drawRoundedRect(inner, radius - 0.5, radius - 0.5)
        knob_d = self.TRACK_H - 6
        knob_x = track.right() - knob_d - 3 if on else track.left() + 3
        knob = QRectF(knob_x, track.center().y() - knob_d / 2, knob_d, knob_d)
        painter.setBrush(QColor("white"))
        if on:
            painter.setPen(Qt.NoPen)
        else:
            # White knob needs an edge to stay visible on a light input fill.
            painter.setPen(QPen(QColor(0, 0, 0, 45), 1))
        painter.drawEllipse(knob)
        if on:
            painter.setPen(QPen(QColor("white"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            check = QPainterPath()
            check.moveTo(track.left() + 7, track.center().y() + 0.5)
            check.lineTo(track.left() + 10.5, track.center().y() + 3.5)
            check.lineTo(track.left() + 15.5, track.center().y() - 3.5)
            painter.drawPath(check)
        painter.setPen(self._fg)
        text_rect = QRectF(
            self.TRACK_W + 8, 0, self.width() - self.TRACK_W - 8, self.height()
        )
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())
        painter.end()


class SettingsWindow(QWidget):
    """Same fields and save semantics as the Tk settings dialog."""

    saved = Signal(dict)

    def __init__(self, values: dict, palette: dict[str, str], lang: str = "en",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsRoot")
        self._values = dict(values)
        self._palette = dict(palette)
        self._lang = lang
        self._mic_devices = [tuple(device) for device in values.get("mic_devices", [])]
        self.setWindowTitle(get_text("settings_title", lang))
        self.setFixedSize(*WINDOW_SIZE)
        self.setStyleSheet(build_stylesheet(palette))
        self._build_ui()

    # -- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 12)
        outer.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self._build_rail())
        self._stack = QStackedWidget()
        self._stack.addWidget(self._page_technical())
        self._stack.addWidget(self._page_shortcuts())
        self._stack.addWidget(self._page_voice())
        self._stack.addWidget(self._page_appearance())
        self._stack.addWidget(self._page_personality())
        body.addWidget(self._stack, 1)
        outer.addLayout(body, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        save_button = QPushButton(get_text("btn_save", self._lang))
        save_button.setObjectName("accent")
        save_button.clicked.connect(self._save)
        close_button = QPushButton(get_text("btn_close", self._lang))
        close_button.clicked.connect(self.close)
        footer.addWidget(save_button)
        footer.addWidget(close_button)
        outer.addLayout(footer)

        self._rail.setCurrentRow(0)
        self._rail.currentRowChanged.connect(self._stack.setCurrentIndex)

    def _build_rail(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("rail")
        frame.setFixedWidth(RAIL_WIDTH)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)
        title = QLabel(get_text("menu_settings", self._lang))
        title.setObjectName("railTitle")
        layout.addWidget(title)
        layout.addSpacing(6)
        self._rail = QListWidget()
        for key in CATEGORIES:
            self._rail.addItem(QListWidgetItem(get_text(key, self._lang)))
        layout.addWidget(self._rail, 1)
        return frame

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        return page, layout

    def _section(self, layout: QVBoxLayout, key: str) -> None:
        label = QLabel(get_text(key, self._lang))
        label.setObjectName("sectionLabel")
        layout.addWidget(label)

    def _new_model_combo(self, current: object) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems([str(model) for model in self._values.get("models", [])])
        combo.setCurrentText(str(current or ""))
        return combo

    # -- pages --------------------------------------------------------------

    def _page_technical(self) -> QWidget:
        page, layout = self._page()
        self._section(layout, "api_key_label")
        self._key_edit = QLineEdit(str(self._values.get("api_key", "")))
        self._key_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._key_edit)
        self._key_error = QLabel("")
        self._key_error.setObjectName("error")
        self._key_error.hide()
        layout.addWidget(self._key_error)
        layout.addSpacing(10)

        self._section(layout, "chat_model_label")
        self._model_combo = self._new_model_combo(self._values.get("model"))
        layout.addWidget(self._model_combo)
        layout.addSpacing(10)

        self._share_check = ToggleSwitch(
            get_text("share_models_label", self._lang), self._palette
        )
        self._share_check.setChecked(bool(self._values.get("share_chat_code_model", True)))
        layout.addWidget(self._share_check)
        layout.addSpacing(10)

        self._section(layout, "code_model_label")
        self._code_combo = self._new_model_combo(self._values.get("code_model"))
        layout.addWidget(self._code_combo)
        layout.addStretch(1)

        def sync_code_state() -> None:
            self._code_combo.setEnabled(not self._share_check.isChecked())

        self._share_check.toggled.connect(sync_code_state)
        sync_code_state()
        return page

    def _page_shortcuts(self) -> QWidget:
        page, layout = self._page()
        self._hotkey_edits: dict[str, QLineEdit] = {}
        specs = (
            ("hotkey", "hotkey_label"),
            ("hotkey_voice", "hotkey_voice_label"),
            ("hotkey_code", "hotkey_code_label"),
        )
        for key, label_key in specs:
            self._section(layout, label_key)
            edit = QLineEdit(str(self._values.get(key, "")))
            layout.addWidget(edit)
            layout.addSpacing(10)
            self._hotkey_edits[key] = edit
        hint = QLabel(get_text("hotkey_hint", self._lang))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _page_voice(self) -> QWidget:
        page, layout = self._page()
        self._section(layout, "settings_mic_label")
        self._mic_combo = QComboBox()
        self._mic_combo.addItem(get_text("mic_default_option", self._lang))
        for _index, name in self._mic_devices:
            self._mic_combo.addItem(str(name))
        position = int(self._values.get("mic_position", 0) or 0)
        self._mic_combo.setCurrentIndex(max(0, min(position, self._mic_combo.count() - 1)))
        layout.addWidget(self._mic_combo)
        layout.addSpacing(10)

        self._wake_check = ToggleSwitch(
            get_text("wake_enable_label", self._lang), self._palette
        )
        self._wake_check.setChecked(bool(self._values.get("wake_word_enabled", False)))
        layout.addWidget(self._wake_check)
        layout.addSpacing(10)

        self._section(layout, "wake_phrase_label")
        self._wake_edit = QLineEdit(str(self._values.get("wake_phrase", "")))
        layout.addWidget(self._wake_edit)
        layout.addSpacing(10)

        self._orb_check = ToggleSwitch(
            get_text("voice_orb_label", self._lang), self._palette
        )
        self._orb_check.setChecked(bool(self._values.get("voice_orb_enabled", True)))
        layout.addWidget(self._orb_check)
        layout.addStretch(1)

        # The summoning sentence only means something while the listener runs.
        def sync_wake_state() -> None:
            self._wake_edit.setEnabled(self._wake_check.isChecked())

        self._wake_check.toggled.connect(sync_wake_state)
        sync_wake_state()
        return page

    def _page_appearance(self) -> QWidget:
        page, layout = self._page()
        self._section(layout, "appearance_label")
        self._theme_dark = QRadioButton(get_text("appearance_dark", self._lang))
        self._theme_light = QRadioButton(get_text("appearance_light", self._lang))
        is_light = str(self._values.get("theme", "dark")).lower() == "light"
        self._theme_light.setChecked(is_light)
        self._theme_dark.setChecked(not is_light)
        theme_group = QButtonGroup(page)
        theme_group.addButton(self._theme_dark)
        theme_group.addButton(self._theme_light)
        layout.addWidget(self._theme_dark)
        layout.addWidget(self._theme_light)
        layout.addSpacing(10)

        self._section(layout, "language_label")
        self._lang_en = QRadioButton("English")
        self._lang_vi = QRadioButton("Tiếng Việt")
        is_vi = str(self._values.get("language", "en")).lower() == "vi"
        self._lang_vi.setChecked(is_vi)
        self._lang_en.setChecked(not is_vi)
        lang_group = QButtonGroup(page)
        lang_group.addButton(self._lang_en)
        lang_group.addButton(self._lang_vi)
        layout.addWidget(self._lang_en)
        layout.addWidget(self._lang_vi)
        layout.addSpacing(10)

        self._section(layout, "opacity_label")
        slider_row = QHBoxLayout()
        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(40, 100)
        opacity = int(round(float(self._values.get("window_opacity", 0.93)) * 100))
        self._opacity_slider.setValue(max(40, min(100, opacity)))
        self._opacity_value = QLabel(f"{self._opacity_slider.value()}%")
        self._opacity_value.setObjectName("hint")
        self._opacity_slider.valueChanged.connect(
            lambda value: self._opacity_value.setText(f"{value}%")
        )
        slider_row.addWidget(self._opacity_slider, 1)
        slider_row.addWidget(self._opacity_value)
        layout.addLayout(slider_row)
        layout.addSpacing(10)

        self._maximize_opaque_check = ToggleSwitch(
            get_text("opacity_maximize_label", self._lang), self._palette
        )
        self._maximize_opaque_check.setChecked(
            bool(self._values.get("maximize_opaque", True))
        )
        layout.addWidget(self._maximize_opaque_check)
        layout.addStretch(1)
        return page

    def _page_personality(self) -> QWidget:
        page, layout = self._page()
        self._section(layout, "personality_label")
        self._pers_edit = QPlainTextEdit()
        self._pers_edit.setPlainText(str(self._values.get("personality", "")))
        layout.addWidget(self._pers_edit, 1)
        return page

    # -- save ----------------------------------------------------------------

    def _save(self) -> None:
        api_key = self._key_edit.text().strip()
        if not api_key:
            self._key_error.setText(get_text("err_empty_key", self._lang))
            self._key_error.show()
            self._key_edit.setFocus()
            return
        position = self._mic_combo.currentIndex()
        voice_device = self._mic_devices[position - 1][0] if position > 0 else None
        self.saved.emit({
            "api_key": api_key,
            "model": self._model_combo.currentText().strip(),
            "code_model": self._code_combo.currentText().strip(),
            "share_chat_code_model": self._share_check.isChecked(),
            "hotkey": self._hotkey_edits["hotkey"].text().strip(),
            "hotkey_voice": self._hotkey_edits["hotkey_voice"].text().strip(),
            "hotkey_code": self._hotkey_edits["hotkey_code"].text().strip(),
            "voice_device": voice_device,
            "wake_word_enabled": self._wake_check.isChecked(),
            "wake_phrase": self._wake_edit.text().strip(),
            "voice_orb_enabled": self._orb_check.isChecked(),
            "theme": "light" if self._theme_light.isChecked() else "dark",
            "language": "vi" if self._lang_vi.isChecked() else "en",
            "window_opacity": round(self._opacity_slider.value() / 100, 2),
            "maximize_opaque": self._maximize_opaque_check.isChecked(),
            "personality": self._pers_edit.toPlainText().strip(),
        })
        self.close()
