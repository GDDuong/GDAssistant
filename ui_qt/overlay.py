"""Frameless, transparent, always-on-top voice orb for GD Assistant (Qt prototype).

Visual language (gd-assistant-qt-design skill + Siri AI reference shots): a
small translucent glass orb — the desktop shows through the tint
(glassmorphism), the form is carried by a crisp rim, inner bevel and top/
bottom light arcs. The light show is one lens-shaped band across the orb's
equator: a few thick, soft spectral strands braid into a single slow S-wave
(warm crest on top, magenta middle, blue lower lobe), additive crossings
converge to a white-hot core, and the band pinches to points at the edges.

In the `result` state the orb becomes a Dynamic-Island-style pill: the
response text renders inside a glass pill whose height follows the text
(capped at RESULT_MAX_LINES; longer answers are truncated and clicking the
pill emits `expandRequested`), and the pulsing rainbow band moves to the
bottom edge of the pill.

States carry no captions — each is a symbol (skill #29): listening = the
band reacting to the live mic level, thinking = three soft white dots
orbiting inside the glass, result = the answer pill. There is deliberately
no `speaking` visual: while the answer is spoken the result pill just stays
on screen.

Motion is restrained and physical and runs on the Qt animation framework
(skill #21/#26): a QVariantAnimation loops the braid phase, QPropertyAnimations
with OutBack/OutCubic easing drive the entrance bounce and the orb<->pill
morph (~280-300ms, interruptible), window opacity fades in 250ms and out
150ms. `reduced_motion=True` drops the decorative loop and lands state
changes instantly while keeping all feedback (skill #31). The static glass
is pre-rendered to a pixmap (skill #33: no per-frame gradient repaints),
and text uses AAA-contrast Segoe UI (14px DemiBold answers / 11px hints).

The orb never steals focus: it uses Qt.Tool (no taskbar entry) plus the
WS_EX_NOACTIVATE extended style set after the window is shown.
"""

from __future__ import annotations

import ctypes
import math

from PySide6.QtCore import Qt, QEasingCurve, QPointF, Property, QRect, QRectF, Signal, QTimer, QPropertyAnimation, QVariantAnimation
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QWidget

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000

SP = 8
ORB_R = 56
TYPE_RESULT_PX = 14
TYPE_HINT_PX = 11
PILL_MAX_RADIUS = 44
RESULT_MAX_LINES = 6
# Three white dots orbiting inside the glass while thinking (symbol-only
# states, skill #29: no captions).
THINK_DOTS = 3
THINK_ORBIT_R = 0.55  # fraction of ORB_R
THINK_DOT_R = 0.09  # fraction of ORB_R
# Height the result pill grows from when the state changes (skill #26:
# entrances start near the final form, never from nothing).
PILL_COLLAPSED_H = 52

# Motion tokens (skill #24) in ms.
MOTION_STANDARD_MS = 280  # entrance/state-change bounce
MORPH_STANDARD_MS = 300  # orb<->pill morph + pill unfold
FADE_IN_MS = 250
FADE_IN_SHORT_MS = 200
FADE_OUT_MS = 150  # exits resolve faster than entrances
PHASE_LOOP_MS = 3300  # one lap of the braid phase clock (~1s strand cycle)

# `speaking` is kept in the API for callers (a turn still speaks its
# answer) but has no distinct visual: the result pill stays on screen.
STATES = {"hidden", "listening", "thinking", "result", "speaking"}

# NOTE: EXPAND_HINT is user-facing and hardcoded English in the prototype;
# it moves to gd_core/translations.py (en+vi) during integration.
EXPAND_HINT = "Click to read it all in the app"

# Braided light strands inside the lens (reference close-up: a few thick,
# soft strands forming one slow S-wave — warm crest on top, magenta middle,
# blue lower lobe; additive crossings blow out to a white-hot core).
# (color, braid phase, bend/speed scale, thickness weight)
STRANDS = (
    (QColor(255, 214, 120), 0.00, 1.00, 1.00),   # warm gold crest
    (QColor(255, 120, 40), 0.90, 0.94, 0.85),    # orange
    (QColor(240, 80, 170), 2.00, 1.02, 0.80),    # magenta
    (QColor(56, 132, 255), 3.10, 1.10, 1.00),    # blue lower lobe
    (QColor(60, 220, 200), 4.20, 1.06, 0.55),    # teal fringe
    (QColor(235, 60, 60), 5.20, 0.90, 0.55),     # red fringe
)

# Braid swing radius as a fraction of the band radius.
BAND_HALF = 0.16

RESULT_TEXT_COLOR = QColor(240, 244, 250)
HINT_COLOR = QColor(170, 180, 200)
PLATE_FILL = QColor(10, 11, 16, 165)
PLATE_BORDER = QColor(255, 255, 255, 56)


def _with_alpha(color: QColor, alpha: int) -> QColor:
    return QColor(color.red(), color.green(), color.blue(), max(0, min(255, int(alpha))))


def _apply_no_activate_style(hwnd: int) -> None:
    # OR the bit in: overwriting GWL_EXSTYLE would wipe Qt's layered/composited
    # styles and turn the translucent background solid black.
    try:
        user32 = ctypes.windll.user32
        get_style, set_style = (
            (user32.GetWindowLongPtrW, user32.SetWindowLongPtrW)
            if hasattr(user32, "GetWindowLongPtrW")
            else (user32.GetWindowLongW, user32.SetWindowLongW)
        )
        get_style.restype = ctypes.c_ssize_t
        get_style.argtypes = [ctypes.c_void_p, ctypes.c_int]
        set_style.restype = ctypes.c_ssize_t
        set_style.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t]
        set_style(hwnd, GWL_EXSTYLE, get_style(hwnd, GWL_EXSTYLE) | WS_EX_NOACTIVATE)
    except Exception:
        pass


class VoiceBubble(QWidget):
    # Emitted when the user clicks a truncated result pill: the app should
    # open and show the full response.
    expandRequested = Signal()

    def __init__(self, width: int = 380, height: int = 150, parent: QWidget | None = None,
                 reduced_motion: bool = False) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(width, height)
        self._reduced_motion = reduced_motion
        self._state = "hidden"
        self._result_text = ""
        self._phase = 0.0
        self._target_level = 0.0  # live mic level 0.0..1.0, set by the caller
        self._display_level = 0.0  # exponentially smoothed toward the target
        self._pop = 1.0  # 0..1 spring progress for the scale-in animation
        self._morph = 1.0  # 0..1 morph animation, reused for every state change
        self._glass = None  # lazily pre-rendered static glass orb (skill #33)
        self._glass_plain = None  # rimless variant (thinking: dots only)
        self._layout = None  # cached result-pill layout, invalidated on new text
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        # Animation framework, not a manual animation clock (skill #21):
        # QVariantAnimation drives the continuous braid phase, QPropertyAnimation
        # drives the pop/morph state-change transitions with Qt easing curves.
        self._phase_anim = QVariantAnimation(self)
        self._phase_anim.setStartValue(0.0)
        self._phase_anim.setEndValue(2.0 * math.pi)
        self._phase_anim.setDuration(PHASE_LOOP_MS)
        self._phase_anim.setLoopCount(-1)
        self._phase_anim.valueChanged.connect(self._set_phase)
        self._pop_anim = QPropertyAnimation(self, b"pop", self)
        self._pop_anim.setEasingCurve(QEasingCurve.OutBack)
        self._morph_anim = QPropertyAnimation(self, b"morph", self)
        self._morph_anim.setEasingCurve(QEasingCurve.OutCubic)
        if reduced_motion:
            # No phase loop at all; a slow timer exists only so the mic-level
            # smoothing keeps the listening pulse alive (skill #31).
            self._timer.start(100)
        else:
            self._phase_anim.start()
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._on_fade_finished)

    # Real Qt properties: QPropertyAnimation only writes registered Q_PROPERTYs,
    # plain Python attributes are ignored (silently). Paint reads the private
    # fields these getters/setters wrap.
    def _get_pop(self) -> float:
        return self._pop

    def _set_pop(self, value: float) -> None:
        self._pop = value

    def _get_morph(self) -> float:
        return self._morph

    def _set_morph(self, value: float) -> None:
        self._morph = value

    pop = Property(float, _get_pop, _set_pop)
    morph = Property(float, _get_morph, _set_morph)

    def show(self) -> None:  # noqa: D102
        super().show()
        _apply_no_activate_style(int(self.winId()))

    def set_state(self, state: str, result_text: str = "") -> None:
        if state not in STATES:
            raise ValueError(f"unknown orb state: {state}")
        previous = self._state
        self._state = state
        if state == "result" and result_text != self._result_text:
            self._result_text = result_text
            self._layout = None
        if state == "hidden":
            self._fade_out()
        elif not self.isVisible():
            self.show()
            self._start_fade(0.0, 1.0, FADE_IN_MS)
            self._restart(self._pop_anim, 0.0, 1.0, MOTION_STANDARD_MS)
        elif state != previous:
            # Any visible state change replays the micro-bounce. The morph
            # crossfade is reserved for pill transitions — replaying it on
            # orb->orb changes would briefly flash the old form's band.
            self._restart(self._pop_anim, min(self._pop, 0.4), 1.0, MOTION_STANDARD_MS)
            self._start_fade(self.windowOpacity(), 1.0, FADE_IN_SHORT_MS)
            if "result" in (previous, state):
                self._restart(self._morph_anim, 0.0, 1.0, MORPH_STANDARD_MS)
        if state == "result" and previous != "result":
            self._restart(self._morph_anim, 0.0, 1.0, MORPH_STANDARD_MS)  # pill unfolds open
        self._sync_cursor()

    def _restart(self, anim, start: float, end: float, duration: int) -> None:
        # Interruptible transitions: restart from wherever the previous run was.
        # Reduced motion lands instantly on the end value (skill #31) — the
        # assistant state stays fully communicated, only the motion is gone.
        anim.stop()
        if self._reduced_motion:
            # Land the registered Qt property instantly (skill #31).
            self.setProperty(bytes(anim.propertyName()).decode(), end)
            self.update()
            return
        anim.setDuration(duration)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def _sync_cursor(self) -> None:
        font, _, _, truncated, _, _ = self._result_layout() if self._state == "result" else (None,) * 6
        self.setCursor(Qt.PointingHandCursor if truncated else Qt.ArrowCursor)

    def _fade_out(self) -> None:
        if not self.isVisible():
            return
        # Exits resolve faster than entrances (asymmetric timing).
        self._start_fade(self.windowOpacity(), 0.0, FADE_OUT_MS)

    def _start_fade(self, start: float, end: float, duration: int) -> None:
        self._fade.stop()
        self._fade.setDuration(duration)
        self._fade.setStartValue(max(0.0, min(1.0, start)))
        self._fade.setEndValue(max(0.0, min(1.0, end)))
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._state == "hidden":
            QWidget.hide(self)

    def set_level(self, level: float) -> None:
        # Raw target from the mic callback; _tick smooths it into self._display_level.
        self._target_level = max(0.0, min(1.0, level))

    def _set_phase(self, value: float) -> None:
        self._phase = value
        self.update()

    def _tick(self) -> None:
        self.update()

    # -- wave amplitude choreography per state ---------------------------

    def _wave_amplitude(self) -> float:
        level = self._display_level
        if self._state == "listening":
            if level > 0.02:
                return 0.45 + min(1.0, level * 1.6) * 1.1
            return 0.4 + 0.12 * math.sin(self._phase * 1.8)
        if self._state == "thinking":
            return 0.0  # thinking is dots-only: no rainbow band at all
        return 0.32 + 0.05 * math.sin(self._phase * 1.4)

    def _wave_speed(self) -> float:
        return 0.9

    # -- result pill geometry ---------------------------------------------

    def _result_layout(self):
        # (font, shown_text, truncated, text_block_height, line_height, pill_rect)
        # Computed once per result text and cached (skill #33).
        if self._layout is None:
            font = QFont("Segoe UI")
            font.setPixelSize(TYPE_RESULT_PX)
            font.setWeight(QFont.DemiBold)
            metrics = QFontMetrics(font)
            pad_x = SP * 2
            inner_w = self.width() - pad_x * 2 - SP * 2
            wrap = Qt.TextWordWrap | Qt.AlignLeft
            box = QRect(0, 0, inner_w, 4000)
            full_h = metrics.boundingRect(box, wrap, self._result_text).height()
            line_h = metrics.height()
            max_text_h = line_h * RESULT_MAX_LINES
            truncated = full_h > max_text_h
            shown = self._result_text
            if truncated:
                words = self._result_text.split()
                lo, hi = 1, len(words)
                while lo < hi:
                    mid = (lo + hi + 1) // 2
                    cand = " ".join(words[:mid]) + "…"
                    if metrics.boundingRect(box, wrap, cand).height() <= max_text_h:
                        lo = mid
                    else:
                        hi = mid - 1
                shown = " ".join(words[:lo]) + "…"
            text_h = metrics.boundingRect(box, wrap, shown).height()
            hint_font = QFont("Segoe UI")
            hint_font.setPixelSize(TYPE_HINT_PX)
            hint_h = QFontMetrics(hint_font).height() + 4 if truncated else 0
            band_zone = SP * 4
            pill_h = SP * 2 + text_h + hint_h + band_zone + SP
            pill = QRectF(pad_x, SP * 2, self.width() - pad_x * 2, min(pill_h, self.height() - SP * 3))
            self._layout = (font, shown, truncated, text_h, line_h, pill)
        return self._layout

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._state == "result":
            _, _, truncated, _, _, pill = self._result_layout()
            if truncated and pill.contains(event.position().toPoint()):
                self.expandRequested.emit()

    # -- painting ---------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        # Mic-level smoothing runs at paint rate (callbacks arrive at audio rate).
        self._display_level += (self._target_level - self._display_level) * 0.35
        if self._pop < 1.0:
            # Skill #26: entrances start near full size (~0.96), never from nothing.
            # Qt's OutBack overshoots 1.0, so the overshoot is remapped to the
            # 0.96->1.04 band before clamping.
            overshoot = max(0.0, min(1.04, self._pop))
            scale = 0.96 + overshoot * 0.08
            rise = 10.0 * (1.0 - min(1.0, self._pop)) ** 3
            painter.translate(0.0, rise)
            painter.translate(self.width() / 2, self.height() / 2)
            painter.scale(scale, scale)
            painter.translate(-self.width() / 2, -self.height() / 2)

        cx = self.width() / 2
        amp = self._wave_amplitude()
        phase = self._phase * 1.8 * self._wave_speed()
        morph = self._morph  # OutCubic easing is applied by QPropertyAnimation

        if self._state == "result":
            # Orb fades out and the pill unfolds/fades in on the same clock,
            # so entering `result` reads as one morph instead of a cut.
            if morph < 1.0:
                painter.save()
                painter.setOpacity(1.0 - morph)
                cy = SP * 2 + ORB_R
                self._paint_bloom(painter, cx, cy, amp)
                painter.drawPixmap(0, 0, self._glass_pixmap())
                self._paint_orb_band(painter, cx, cy, amp, phase)
                painter.restore()
            self._paint_pill(painter, amp, phase)
        else:
            cy = SP * 2 + ORB_R
            if self._state == "thinking":
                # Dots-only symbol: plain rimless glass, no rainbow band.
                painter.drawPixmap(0, 0, self._plain_glass_pixmap())
                self._paint_thinking_dots(painter, cx, cy)
            else:
                self._paint_bloom(painter, cx, cy, amp)
                painter.drawPixmap(0, 0, self._glass_pixmap())
                self._paint_orb_band(painter, cx, cy, amp, phase)

    def _paint_thinking_dots(self, painter, cx, cy) -> None:
        # Three soft white dots orbiting inside the glass (skill #29:
        # slowly flowing, no frantic movement).
        orbit = ORB_R * THINK_ORBIT_R
        dot_r = ORB_R * THINK_DOT_R
        painter.setPen(Qt.NoPen)
        for i in range(THINK_DOTS):
            a = self._phase * 0.9 + i * 2.0 * math.pi / THINK_DOTS
            x = cx + orbit * math.cos(a)
            y = cy + orbit * math.sin(a) * 0.62  # slight ellipse reads as depth
            phase_factor = 0.5 + 0.5 * math.sin(a)
            halo = QRadialGradient(x, y, dot_r * 2.6)
            halo.setColorAt(0.0, QColor(235, 240, 255, int(95 + 90 * phase_factor)))
            halo.setColorAt(1.0, QColor(235, 240, 255, 0))
            painter.setBrush(halo)
            painter.drawEllipse(QRectF(x - dot_r * 2.6, y - dot_r * 2.6,
                                       dot_r * 5.2, dot_r * 5.2))
            painter.setBrush(QColor(255, 255, 255, int(150 + 80 * phase_factor)))
            painter.drawEllipse(QRectF(x - dot_r, y - dot_r, dot_r * 2, dot_r * 2))

    def _glass_pixmap(self) -> QPixmap:
        # The sphere body, lower reflection and rim never change between
        # frames, so they are painted once into a pixmap and blitted (skill
        # #33: no per-frame complex-gradient repaints).
        return self._static_glass(with_rim=True)

    def _plain_glass_pixmap(self) -> QPixmap:
        # Rimless variant for the dots-only thinking state — with no band
        # under it the rim's speculars would read as leftover light.
        return self._static_glass(with_rim=False)

    def _static_glass(self, with_rim: bool) -> QPixmap:
        key = "_glass" if with_rim else "_glass_plain"
        pm = getattr(self, key)
        if pm is None:
            dpr = self.devicePixelRatioF()
            pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            painter = QPainter(pm)
            painter.setRenderHint(QPainter.Antialiasing)
            self._paint_sphere_body(painter, self.width() / 2, SP * 2 + ORB_R)
            if with_rim:
                self._paint_rim(painter, self.width() / 2, SP * 2 + ORB_R)
            painter.end()
            setattr(self, key, pm)
        return pm

    def _paint_bloom(self, painter, cx, cy, amp) -> None:
        radius = ORB_R * (1.45 + amp * 0.25)
        bloom = QRadialGradient(cx, cy, radius)
        bloom.setColorAt(0.55, QColor(210, 220, 255, int(12 + 14 * amp)))
        bloom.setColorAt(1.0, QColor(210, 220, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(bloom)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

    def _paint_sphere_body(self, painter, cx, cy) -> None:
        disc = QRectF(cx - ORB_R, cy - ORB_R, ORB_R * 2, ORB_R * 2)
        # Glassmorphism (skill #6/#10): the desktop shows through the tinted
        # sphere; the form is carried by rim/edge highlights, not by opacity.
        # Darker only toward the rim so the band stays legible on light walls.
        glass = QRadialGradient(cx, cy - ORB_R * 0.3, ORB_R * 1.35)
        glass.setColorAt(0.0, QColor(14, 16, 24, 88))
        glass.setColorAt(0.72, QColor(8, 9, 14, 120))
        glass.setColorAt(1.0, QColor(4, 5, 8, 170))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glass)
        painter.drawEllipse(disc)
        path = QPainterPath()
        path.addEllipse(QPointF(cx, cy), ORB_R, ORB_R)
        painter.save()
        painter.setClipPath(path)
        lower = QRadialGradient(cx, cy + ORB_R * 1.25, ORB_R * 1.15)
        lower.setColorAt(0.0, QColor(148, 154, 168, 46))
        lower.setColorAt(1.0, QColor(148, 154, 168, 0))
        painter.setBrush(lower)
        painter.drawEllipse(disc)
        painter.restore()

    def _paint_rim(self, painter, cx, cy) -> None:
        # With the fill now translucent, the rim carries the whole form
        # (skill #16): crisp outer edge, faint inner bevel, brighter top arc,
        # cool light-gathering bottom arc.
        disc = QRectF(cx - ORB_R, cy - ORB_R, ORB_R * 2, ORB_R * 2)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(_with_alpha(QColor(255, 255, 255), 74), 1.3))
        painter.drawEllipse(disc)
        inner = disc.adjusted(2.5, 2.5, -2.5, -2.5)
        painter.setPen(QPen(_with_alpha(QColor(255, 255, 255), 20), 1.0))
        painter.drawEllipse(inner)
        # Top-left rim highlight arc, like a lit glass ball.
        painter.setPen(QPen(_with_alpha(QColor(255, 255, 255), 150), 1.6))
        painter.drawArc(disc, 55 * 16, 85 * 16)
        # Bottom arc gathers ambient light.
        painter.setPen(QPen(_with_alpha(QColor(210, 224, 255), 66), 1.4))
        painter.drawArc(disc, 235 * 16, 70 * 16)
        spec = QRectF(cx - ORB_R * 0.52, cy - ORB_R * 0.72, ORB_R * 0.5, ORB_R * 0.24)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 30))
        painter.drawEllipse(spec)

    def _paint_orb_band(self, painter, cx, cy, amp, phase) -> None:
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), ORB_R - 1, ORB_R - 1)
        painter.save()
        painter.setClipPath(clip)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        painter.setPen(Qt.NoPen)
        self._draw_band(painter, cx, cy, ORB_R, amp, phase, 1.0)
        painter.restore()

    def _paint_pill(self, painter, amp, phase) -> None:
        font, shown, truncated, text_h, _, pill_full = self._result_layout()
        # Unfold animation: _morph is eased by the QPropertyAnimation itself
        # (skill #21/#25); height grows from a collapsed capsule and the
        # content fades in slightly ahead of it (skill #26).
        e = self._morph
        fade = min(1.0, e * 2.0)
        h = PILL_COLLAPSED_H + (pill_full.height() - PILL_COLLAPSED_H) * e
        pill = QRectF(pill_full.x(), pill_full.y(), pill_full.width(), h)
        radius = min(h / 2, PILL_MAX_RADIUS)  # true capsule, never squarish
        path = QPainterPath()
        path.addRoundedRect(pill, radius, radius)
        painter.setPen(QPen(_with_alpha(PLATE_BORDER, int(56 * fade)), 1))
        painter.setBrush(_with_alpha(PLATE_FILL, int(PLATE_FILL.alpha() * min(1.0, 0.4 + 0.6 * fade))))
        painter.drawPath(path)
        # Top-edge highlight so the pill reads as glass, not a dark card.
        painter.setPen(QPen(_with_alpha(QColor(255, 255, 255), int(46 * fade)), 1.0))
        painter.drawArc(
            QRectF(pill.x() + radius, pill.y() + radius, pill.width() - radius * 2, 20),
            20 * 16, 140 * 16,
        )
        painter.save()
        painter.setClipPath(path)
        painter.setFont(font)
        painter.setPen(_with_alpha(RESULT_TEXT_COLOR, int(255 * fade)))
        text_rect = QRectF(
            pill.x() + radius * 0.62, pill.y() + SP * 2,
            pill.width() - radius * 1.24, text_h,
        )
        painter.drawText(text_rect, Qt.TextWordWrap | Qt.AlignLeft, shown)
        if truncated:
            hint_font = QFont("Segoe UI")
            hint_font.setPixelSize(TYPE_HINT_PX)
            hint_font.setItalic(True)
            painter.setFont(hint_font)
            painter.setPen(_with_alpha(HINT_COLOR, int(200 * e)))
            painter.drawText(
                QRectF(text_rect.x(), text_rect.y() + text_h + 2, text_rect.width(), SP * 2),
                Qt.AlignLeft, EXPAND_HINT,
            )
        # The rainbow band rides the pill's bottom edge.
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        painter.setPen(Qt.NoPen)
        self._draw_band(
            painter, pill.center().x(), pill.bottom() - SP * 2,
            pill.width() / 2 - SP, amp, phase, 0.5,
        )
        painter.restore()

    def _draw_band(self, painter, cx, cy, R, amp, phase, tscale) -> None:
        a = min(1.3, amp)
        for color, braid_phase, bend, weight in STRANDS:
            # Wide soft halo, mid diffusion, then the strand body — the
            # reference strands have no hard edges, only layered light.
            for thick, alpha in ((3.0, 11), (1.7, 24), (1.0, 62)):
                painter.setBrush(_with_alpha(color, alpha))
                painter.drawPath(
                    self._wave_path(cx, cy, R, a, phase, braid_phase, weight, bend, thick * tscale)
                )
        # White-hot core riding the braid where the strands cross.
        painter.setBrush(QColor(255, 255, 255, int(55 + 125 * min(1.0, a))))
        painter.drawPath(self._wave_path(cx, cy, R, a, phase, 0.0, 0.45, 1.0, 0.5 * tscale))

    def _wave_path(self, cx, cy, R, amp, phase, braid_phase, weight, bend, thick) -> QPainterPath:
        steps = 44
        top: list[QPointF] = []
        bottom: list[QPointF] = []
        for i in range(steps + 1):
            u = -1.0 + 2.0 * i / steps
            x = u * R
            pinch = math.sqrt(max(0.0, 1.0 - u * u))
            taper = pinch ** 1.25  # lens silhouette: band pinches to points at the edges
            wave = BAND_HALF * amp * math.sin(u * 2.4 + phase * bend + braid_phase)
            ripple = 0.03 * amp * pinch * math.sin(u * 5.0 + phase * bend * 1.6 + braid_phase)
            y = R * taper * (wave + ripple)
            t = R * (0.05 + 0.03 * pinch * amp) * weight * thick * taper
            top.append(QPointF(cx + x, cy + y - t))
            bottom.append(QPointF(cx + x, cy + y + t))
        path = QPainterPath(top[0])
        for point in top[1:]:
            path.lineTo(point)
        for point in reversed(bottom):
            path.lineTo(point)
        path.closeSubpath()
        return path


def main() -> None:
    import sys

    app = QApplication(sys.argv)
    orb = VoiceBubble(reduced_motion="--reduce-motion" in sys.argv[1:])
    screen = app.primaryScreen().availableGeometry()
    orb.move(screen.center().x() - orb.width() // 2, screen.top() + 30)
    orb.expandRequested.connect(lambda: print("[DEMO] expand requested -> open the app"))

    long_answer = (
        "Here's the weather for tomorrow: partly cloudy with a high of 27°C and a "
        "low of 19°C. There's a 30% chance of light rain around 4pm, so if you're "
        "heading out in the late afternoon it would be worth bringing an umbrella. "
        "Mornings will stay mild around 21°C with a soft breeze from the east, and "
        "the sun should break through again after 6pm for a clear, calm evening — "
        "nice conditions for a walk after dinner."
    )
    script = [
        (0, "listening", ""),
        (4000, "thinking", ""),
        (7000, "result", long_answer),  # pill unfolds; it also IS the speaking view
        (13500, "hidden", ""),
    ]
    for delay, state, text in script:
        QTimer.singleShot(delay, lambda s=state, t=text: orb.set_state(s, t))
    QTimer.singleShot(14000, app.quit)

    orb.set_state("listening")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
