"""Themed popup menus: painted panel + entrance motion.

QMenu keeps ownership of the popup grab and item hit-testing; the surface is
custom-painted (soft stacked shadow, rounded panel, palette-driven gradient,
hairline border, top edge highlight) and the entrance animates windowOpacity
+ position. The shadow is a handful of translucent rounded rects painted
once per show — no QGraphicsBlurEffect over a large translucent window, per
the performance rules in the Qt design skill.

mousePress/ReleaseEvent record a click that landed outside the menu: the
popup grab routes those here and QMenu closes on them, but the click never
reaches the widget underneath (e.g. the File/Mode buttons in the Tk app), so
the recorded point lets the app replay it — one-click menu switching. Key
dismissals (Esc) and item selections do not touch the mouse path, so their
"dismiss point" stays None.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QCursor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu

from ui_qt.motion import RiseEntrance

# Entrance motion: MOTION_FAST with OutCubic (Qt design skill defaults).
ENTRANCE_MS = 140
ENTRANCE_RISE_PX = 6
PANEL_RADIUS = 12
ITEM_RADIUS = 8
# The panel floats on a transparent margin that carries a painted soft
# shadow (QMenu keeps its mouse grab over the whole window, so the margin
# stays small — it is also the dead zone around the menu edge).
SHADOW_MARGIN = 10
SHADOW_OFFSET_Y = 2
SHADOW_STEPS = 8
SHADOW_ALPHA = 10  # per layer; overlapping layers fade out toward the edge
CONTENT_PAD = 6


def paint_glass_panel(
    painter: QPainter,
    rect: QRect,
    panel_color: QColor,
    border_color: QColor,
    radius: int,
    shadow_steps: int,
    shadow_alpha: int,
    shadow_offset_y: int,
    gradient_light: int = 118,
    gradient_dark: int = 108,
    highlight_alpha: int = 36,
) -> None:
    """The one glass recipe menus and windows share: stacked soft shadow,
    rounded gradient panel, top-edge highlight, hairline border. Geometry
    knobs differ per surface; the recipe lives here so it cannot drift."""
    shadow = QColor(0, 0, 0, shadow_alpha)
    shadow_rect = rect.translated(0, shadow_offset_y)
    for step in range(shadow_steps, 0, -1):
        layer = QPainterPath()
        layer.addRoundedRect(
            shadow_rect.adjusted(-step, -step, step, step),
            radius + step, radius + step,
        )
        painter.fillPath(layer, shadow)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0.0, panel_color.lighter(gradient_light))
    gradient.setColorAt(1.0, panel_color.darker(gradient_dark))
    painter.fillPath(path, gradient)
    painter.setPen(QPen(QColor(255, 255, 255, highlight_alpha), 1))
    painter.drawLine(
        rect.left() + radius, rect.top() + 1,
        rect.right() - radius, rect.top() + 1,
    )
    border = QColor(border_color)
    border.setAlpha(200)
    painter.setPen(QPen(border, 1))
    painter.drawPath(path)


def menu_stylesheet(palette: dict[str, str]) -> str:
    """QSS for the popup menu's items.

    The panel itself is custom-painted, so the QMenu rule stays transparent;
    Qt QSS color does not inherit into child widgets the way CSS does, so
    every text-bearing selector is styled explicitly. Disabled items use the
    muted token at 66% alpha so they read as disabled, not as links.
    """
    muted = QColor(palette["muted"])
    disabled = f"rgba({muted.red()}, {muted.green()}, {muted.blue()}, 168)"
    accent = QColor(palette["accent"])
    return f"""
    QMenu {{
        background: transparent;
        border: none;
        padding: {CONTENT_PAD + SHADOW_MARGIN}px;
        font-size: 10pt;
    }}
    QMenu::item {{
        color: {palette["foreground"]};
        padding: 8px 30px 8px 12px;
        border-radius: {ITEM_RADIUS}px;
    }}
    QMenu::item:selected {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {accent.lighter(112).name()}, stop:1 {accent.darker(106).name()});
        color: white;
    }}
    QMenu::item:disabled {{
        color: {disabled};
    }}
    QMenu::separator {{
        height: 1px;
        background: {palette["border"]};
        margin: 5px 10px;
    }}
    """


class PopupMenu(QMenu):
    """Frameless translucent popup with a painted panel and a rise-in fade."""

    def __init__(self, palette: dict[str, str], animate: bool = True) -> None:
        super().__init__()
        self._panel_color = QColor(palette["panel"])
        self._border_color = QColor(palette["border"])
        self._animate = animate
        self._dismiss_click: QPoint | None = None
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(menu_stylesheet(palette))

        self._entrance = RiseEntrance(self, ENTRANCE_MS, ENTRANCE_RISE_PX)

    # -- painted surface (Qt thread only) -------------------------------------

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Panel rect inset by the shadow margin; the extra 1px on the far
        # edges keeps the 1px border stroke fully visible.
        panel = self.rect().adjusted(
            SHADOW_MARGIN, SHADOW_MARGIN, -SHADOW_MARGIN - 1, -SHADOW_MARGIN - 1
        )
        paint_glass_panel(
            painter, panel, self._panel_color, self._border_color, PANEL_RADIUS,
            SHADOW_STEPS, SHADOW_ALPHA, SHADOW_OFFSET_Y,
        )
        painter.end()
        super().paintEvent(event)

    # -- entrance motion ------------------------------------------------------

    def popup_at_cursor(self) -> None:
        """Open at the cursor, then rise ~6px into place while fading in."""
        self.setWindowOpacity(0.0)
        super().popup(QCursor.pos())
        self._play_entrance()

    def _play_entrance(self) -> None:
        if not self._animate:
            self.setWindowOpacity(1.0)
            return
        # RiseEntrance reads our current pos, so this animates from where
        # popup()/the WM placed us (screen clamping already happened).
        self._entrance.play()

    # -- dismiss-click recording ----------------------------------------------

    def mousePressEvent(self, event) -> None:
        self._note_outside_click(event)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._note_outside_click(event)
        super().mouseReleaseEvent(event)

    def _note_outside_click(self, event) -> None:
        if event.button() == Qt.LeftButton and not self.rect().contains(event.position().toPoint()):
            self._dismiss_click = event.globalPosition().toPoint()

    def dismiss_click_pos(self) -> QPoint | None:
        return self._dismiss_click
