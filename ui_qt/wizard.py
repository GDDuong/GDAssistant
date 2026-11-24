"""First-boot setup wizard (Qt). Plain styled by request — no glass.

One QDialog with a step stack, mirroring the legacy Tk wizard exactly:
language -> theme + window opacity -> API key & models -> mic & hotkey ->
personality. Returns one flat dict via ``result()``, or None when cancelled
(X / Esc). Runs on the Qt service thread through QtUiService.run_wizard, so
the Tk side simply blocks on the completion event.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gd_core.translations import get_text
from ui_qt.settings_window import ToggleSwitch

WINDOW_SIZE = (540, 470)

STEP_TITLES = (
    "wizard_lang_title",
    "wizard_prefs_title",
    "wizard_step1_title",
    "wizard_step2_title",
    "wizard_step3_title",
)


def build_stylesheet(palette: dict[str, str]) -> str:
    return f"""
    #wizardRoot {{ background: {palette["background"]}; }}
    QLabel {{ color: {palette["foreground"]}; }}
    QLabel#heading {{ font-size: 14pt; font-weight: 700; }}
    QLabel#sub {{ color: {palette["muted"]}; }}
    QLabel#error {{ color: {palette["error"]}; }}
    QLineEdit, QComboBox, QPlainTextEdit {{
        background: {palette["input"]};
        color: {palette["foreground"]};
        border: 1px solid {palette["border"]};
        border-radius: 8px;
        padding: 6px 8px;
        selection-background-color: {palette["accent"]};
        selection-color: white;
    }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {palette["accent"]}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {palette["input"]};
        color: {palette["foreground"]};
        border: 1px solid {palette["border"]};
        selection-background-color: {palette["accent"]};
        selection-color: white;
        outline: none;
    }}
    QRadioButton {{ color: {palette["foreground"]}; spacing: 8px; }}
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
    QPushButton#choice {{ padding: 10px 18px; }}
    """


class WizardDialog(QDialog):
    """Linear setup wizard; result() is the flat config dict or None."""

    def __init__(self, payload: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("wizardRoot")
        self._payload = payload
        self._result: dict | None = None
        self._step = 0
        self._lang = str(payload.get("language") or "en")
        self._theme = str(payload.get("theme") or "light")
        self._opacity = float(payload.get("window_opacity") or 1.0)
        self._pages: dict[int, QWidget] = {}
        self.setFixedSize(*WINDOW_SIZE)
        self.setStyleSheet(build_stylesheet(self._palette()))
        self._build_shell()
        self._show_step(0)

    # -- shell ---------------------------------------------------------------

    def _palette(self) -> dict[str, str]:
        from ui_tk.themes import get_theme

        return get_theme(self._theme)

    def _build_shell(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 14)
        layout.setSpacing(8)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self._next_button = QPushButton(get_text("btn_next", self._lang))
        self._next_button.setObjectName("accent")
        self._next_button.clicked.connect(self._next)
        footer.addWidget(self._next_button)
        layout.addLayout(footer)

    def _heading(self, layout: QVBoxLayout, heading_key: str, sub_key: str) -> None:
        heading = QLabel(get_text(heading_key, self._lang))
        heading.setObjectName("heading")
        layout.addWidget(heading)
        sub = QLabel(get_text(sub_key, self._lang))
        sub.setObjectName("sub")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(10)

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        return page, layout

    def _show_step(self, step: int) -> None:
        self._step = step
        if step not in self._pages:
            self._pages[step] = self._build_step(step)
            self._stack.addWidget(self._pages[step])
        self._stack.setCurrentWidget(self._pages[step])
        self.setWindowTitle(get_text(STEP_TITLES[step], self._lang))
        self._next_button.setText(
            get_text("btn_finish" if step == len(STEP_TITLES) - 1 else "btn_next", self._lang)
        )

    # -- steps ---------------------------------------------------------------

    def _build_step(self, step: int) -> QWidget:
        if step == 0:
            return self._step_language()
        if step == 1:
            return self._step_theme()
        if step == 2:
            return self._step_api_models()
        if step == 3:
            return self._step_mic_hotkey()
        return self._step_personality()

    def _step_language(self) -> QWidget:
        page, layout = self._page()
        self._heading(layout, "wizard_lang_heading", "wizard_lang_sub")
        for code, label in (("en", "English"), ("vi", "Tiếng Việt")):
            button = QPushButton(label)
            button.setObjectName("accent" if code == "en" else "")
            if code == "en":
                button.setDefault(True)
            button.clicked.connect(lambda _c=False, lang=code: self._pick_language(lang))
            layout.addWidget(button)
        layout.addStretch(1)
        return page

    def _pick_language(self, lang: str) -> None:
        self._lang = lang
        self._rebuild_texts()
        self._show_step(1)

    def _step_theme(self) -> QWidget:
        page, layout = self._page()
        self._heading(layout, "wizard_prefs_heading", "wizard_prefs_sub")
        self._theme_light = QRadioButton(get_text("appearance_light", self._lang))
        self._theme_dark = QRadioButton(get_text("appearance_dark", self._lang))
        self._theme_light.setChecked(self._theme != "dark")
        self._theme_dark.setChecked(self._theme == "dark")
        self._theme_light.toggled.connect(
            lambda _c: self._apply_theme("light" if self._theme_light.isChecked() else "dark")
        )
        layout.addWidget(self._theme_light)
        layout.addWidget(self._theme_dark)
        layout.addSpacing(14)

        layout.addWidget(QLabel(get_text("opacity_label", self._lang)))
        slider_row = QHBoxLayout()
        self._opacity_slider = QSlider(Qt.Horizontal)
        self._opacity_slider.setRange(40, 100)
        self._opacity_slider.setValue(max(40, min(100, int(round(self._opacity * 100)))))
        self._opacity_value = QLabel(f"{self._opacity_slider.value()}%")
        self._opacity_value.setObjectName("sub")
        self._opacity_slider.valueChanged.connect(
            lambda value: self._opacity_value.setText(f"{value}%")
        )
        slider_row.addWidget(self._opacity_slider, 1)
        slider_row.addWidget(self._opacity_value)
        layout.addLayout(slider_row)
        layout.addStretch(1)
        return page

    def _apply_theme(self, theme: str) -> None:
        self._theme = theme
        self.setStyleSheet(build_stylesheet(self._palette()))

    def _step_api_models(self) -> QWidget:
        page, layout = self._page()
        self._heading(layout, "wizard_step1_heading", "wizard_step1_sub")

        layout.addWidget(QLabel(get_text("api_key_label", self._lang)))
        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._key_edit)
        self._key_error = QLabel("")
        self._key_error.setObjectName("error")
        self._key_error.hide()
        layout.addWidget(self._key_error)
        layout.addSpacing(8)

        layout.addWidget(QLabel(get_text("chat_model_label", self._lang)))
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItems([str(m) for m in self._payload.get("models") or []])
        self._model_combo.setCurrentText(str(self._payload.get("model") or ""))
        layout.addWidget(self._model_combo)
        layout.addSpacing(8)

        self._share_check = ToggleSwitch(
            get_text("share_models_label", self._lang), self._palette()
        )
        self._share_check.setChecked(bool(self._payload.get("share_chat_code_model", True)))
        layout.addWidget(self._share_check)
        layout.addSpacing(8)

        layout.addWidget(QLabel(get_text("code_model_label", self._lang)))
        self._code_combo = QComboBox()
        self._code_combo.setEditable(True)
        self._code_combo.addItems([str(m) for m in self._payload.get("models") or []])
        self._code_combo.setCurrentText(str(self._payload.get("code_model") or ""))
        layout.addWidget(self._code_combo)

        def sync_code_state() -> None:
            self._code_combo.setEnabled(not self._share_check.isChecked())

        self._share_check.toggled.connect(sync_code_state)
        sync_code_state()
        layout.addStretch(1)
        return page

    def _step_mic_hotkey(self) -> QWidget:
        page, layout = self._page()
        self._heading(layout, "wizard_step2_heading", "wizard_step2_sub")

        layout.addWidget(QLabel(get_text("settings_mic_label", self._lang)))
        self._mic_combo = QComboBox()
        self._mic_combo.addItem(get_text("mic_default_option", self._lang))
        devices = [tuple(d) for d in (self._payload.get("mic_devices") or [])]
        for _index, name in devices:
            self._mic_combo.addItem(str(name))
        position = 0
        stored = self._payload.get("voice_device")
        for pos, (device_index, _name) in enumerate(devices, start=1):
            if device_index == stored:
                position = pos
                break
        self._mic_combo.setCurrentIndex(position)
        layout.addWidget(self._mic_combo)
        layout.addSpacing(8)

        layout.addWidget(QLabel(get_text("hotkey_label", self._lang)))
        self._hotkey_edit = QLineEdit(str(self._payload.get("hotkey") or ""))
        layout.addWidget(self._hotkey_edit)
        layout.addStretch(1)
        return page

    def _step_personality(self) -> QWidget:
        page, layout = self._page()
        self._heading(layout, "wizard_step3_heading", "wizard_step3_sub")
        layout.addWidget(QLabel(get_text("personality_label", self._lang)))
        self._pers_edit = QPlainTextEdit()
        self._pers_edit.setPlainText(str(self._payload.get("personality") or ""))
        layout.addWidget(self._pers_edit, 1)
        return page

    # -- navigation ----------------------------------------------------------

    def _rebuild_texts(self) -> None:
        # Language chosen on step 0 retexts the shell and every built step.
        self._pages.clear()
        while self._stack.count():
            self._stack.removeWidget(self._stack.widget(0))
        self._next_button.setText(get_text("btn_next", self._lang))
        self._show_step(1)

    def _next(self) -> None:
        if self._step == 2 and not self._key_edit.text().strip():
            self._key_error.setText(get_text("err_empty_key", self._lang))
            self._key_error.show()
            self._key_edit.setFocus()
            return
        if self._step < len(STEP_TITLES) - 1:
            self._show_step(self._step + 1)
            return
        self._finish()

    def _finish(self) -> None:
        devices = [tuple(d) for d in (self._payload.get("mic_devices") or [])]
        mic_position = self._mic_combo.currentIndex()
        self._result = {
            "language": self._lang,
            "theme": "dark" if self._theme_dark.isChecked() else "light",
            "window_opacity": round(self._opacity_slider.value() / 100, 2),
            "api_key": self._key_edit.text().strip(),
            "model": self._model_combo.currentText().strip(),
            "code_model": self._code_combo.currentText().strip(),
            "share_chat_code_model": self._share_check.isChecked(),
            "hotkey": self._hotkey_edit.text().strip(),
            "voice_device": (
                devices[mic_position - 1][0] if 0 < mic_position <= len(devices) else None
            ),
            "personality": self._pers_edit.toPlainText().strip(),
        }
        self.accept()

    def wizard_result(self) -> dict | None:
        return self._result
