import ctypes
import math
import time
import glob
import os
from functools import lru_cache
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QApplication, QMenu, QSizePolicy, QCheckBox
)
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QRectF, QSize, QPropertyAnimation, QVariantAnimation,
    QEasingCurve, pyqtSignal
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontDatabase, QFontMetricsF, QLinearGradient,
    QPainterPath, QPolygonF, QPixmap, QIcon, QPalette
)


try:
    from ..config import get_asset_path
    from ..engine.audio_recorder import list_microphones
    from ..engine import model_manager
except (ImportError, ValueError):
    from config import get_asset_path
    from engine.audio_recorder import list_microphones
    from engine import model_manager


def _force_topmost(widget: QWidget):
    """Qt's stay-on-top hint is set once; other topmost windows (Teams, games, full-screen apps)
    can still cover us. Re-assert HWND_TOPMOST every time the capsule shows."""
    if not isinstance(widget, QMenu):
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMenu) and w.isVisible():
                return
    HWND_TOPMOST, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = -1, 0x0001, 0x0002, 0x0010
    try:
        # c_void_p: a bare -1 would reach a 64-bit HWND as 0xFFFFFFFF, not HWND_TOPMOST
        ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(int(widget.winId())), ctypes.c_void_p(HWND_TOPMOST), 0, 0, 0, 0,
                                          SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass

_ASSETS = get_asset_path().replace("\\", "/")

# Black & white palette
FG = "#ffffff"
FG_DIM = "rgba(255, 255, 255, 0.55)"
FG_FAINT = "rgba(255, 255, 255, 0.32)"
HAIRLINE = "rgba(255, 255, 255, 0.10)"
FILL = "rgba(255, 255, 255, 0.07)"
ACCENT = "#0A84FF"  # Apple systemBlue (dark)
GREEN = "#30D158"
RED = "#FF453A"


def get_squircle_pixmap(image_path: str, size: int = 26, radius: float = 6.0) -> QPixmap:
    """Renders a high-DPI squircle brand emblem with smooth anti-aliasing and hairline rim."""
    dest = QPixmap(size, size)
    dest.fill(Qt.GlobalColor.transparent)
    if not os.path.exists(image_path):
        return dest
    src = QPixmap(image_path).scaled(
        size * 2, size * 2,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation
    )
    painter = QPainter(dest)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, size, size, src)
    painter.setClipping(False)
    # Subtle translucent outer rim
    painter.setPen(QPen(QColor(255, 255, 255, 38), 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(0.5, 0.5, size - 1, size - 1), radius, radius)
    painter.end()
    return dest


@lru_cache(maxsize=1)
def ui_font_family() -> str:
    """Bundled Inter, so every PC looks the same. Never calls QFontDatabase.families():
    enumerating system fonts takes seconds on machines with many fonts installed."""
    family = ""
    for f in glob.glob(os.path.join(get_asset_path("fonts"), "*.ttf")):
        families = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(f))
        family = family or (families[0] if families else "")
    return family or "Segoe UI"


class StateIndicator(QWidget):
    """Monochrome vector indicator: breathing idle dot, pulsing rings, spinner arc, or animated checkmark."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.state = "idle"
        self.phase = 0.0
        self._check_p = 1.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def set_state(self, state: str):
        if state == "done" and self.state != "done":
            self._check_p = 0.0
        self.state = state
        self.update()

    def _tick(self):
        self.phase += 0.09
        if self.state == "done" and self._check_p < 1.0:
            self._check_p = min(1.0, self._check_p + 0.075)
        self.update()

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QRectF(self.rect()).center()

        if self.state == "listening":
            pulse = 0.5 + 0.5 * math.sin(self.phase * 1.6)
            ring = 5.0 + 3.5 * pulse
            p.setPen(QPen(QColor(255, 255, 255, int(90 * (1 - pulse) + 20)), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, ring, ring)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(c, 3.5, 3.5)
        elif self.state == "processing":
            angle = int(math.degrees(self.phase * 2.4)) % 360
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(c.x() - 7, c.y() - 7, 14, 14), -angle * 16, 100 * 16 * 2)
        elif self.state == "done":
            # Animated stroke draw
            p.setPen(QPen(QColor(255, 255, 255), 2.0, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            pt1 = QPointF(c.x() - 5, c.y() + 0.5)
            pt2 = QPointF(c.x() - 1.5, c.y() + 4.0)
            pt3 = QPointF(c.x() + 5.5, c.y() - 4.0)

            path = QPainterPath()
            path.moveTo(pt1)
            prog = self._check_p
            if prog <= 0.40:
                seg_p = prog / 0.40
                cur = pt1 + (pt2 - pt1) * seg_p
                path.lineTo(cur)
            else:
                path.lineTo(pt2)
                seg_p = (prog - 0.40) / 0.60
                cur = pt2 + (pt3 - pt2) * seg_p
                path.lineTo(cur)
            p.drawPath(path)
        else:
            # Idle: gentle Apple breathing luminescence
            b = 0.5 + 0.5 * math.sin(self.phase * 0.4)
            alpha = int(75 + 45 * b)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, alpha))
            p.drawEllipse(c, 3.2, 3.2)



class WaveformBars(QWidget):
    """Five responsive rounded bars reacting dynamically to real-time audio."""

    def __init__(self, parent=None, num_bars=5):
        super().__init__(parent)
        self.num_bars = num_bars
        self.bar_weights = [0.65, 0.92, 1.0, 0.88, 0.60]
        self.bar_heights = [0.18] * num_bars
        self.target_level = 0.0
        self.phase = 0.0
        self.setFixedSize(42, 20)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)  # 60 FPS fluid rendering

    def set_level(self, level: float):
        # Instant level registration with no artificial floor
        self.target_level = max(0.0, min(1.0, level))

    def reset(self):
        self.target_level = 0.0

    def _tick(self):
        if not self.isVisible():
            return
        self.phase += 0.28
        lvl = self.target_level
        is_speech = lvl > 0.04

        for i in range(self.num_bars):
            if is_speech:
                # Organic vocal envelope modulation (always strictly positive: 0.68 to 1.18)
                mod = 0.70 + 0.30 * math.sin(self.phase * 1.6 + i * 1.35)
                # Dynamic height based on formant sensitivity
                target = min(1.0, lvl * self.bar_weights[i] * mod * 1.35)
            else:
                # Subtle resting pulse (breathing animation while listening to ambient silence)
                target = 0.14 + 0.06 * math.sin(self.phase * 0.9 + i * 1.1)

            current = self.bar_heights[i]
            # Fast attack (0.70) snaps up with voice, smooth decay (0.24) falls gracefully
            if target > current:
                self.bar_heights[i] = current + (target - current) * 0.70
            else:
                self.bar_heights[i] = current + (target - current) * 0.24

        self.update()

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        # Subtle bright glow when speech energy is high
        alpha = int(210 + 45 * min(1.0, self.target_level * 1.5))
        p.setBrush(QColor(255, 255, 255, alpha))

        bar_w = 3.2
        gap = 3.5
        total = self.num_bars * bar_w + (self.num_bars - 1) * gap
        x0 = (self.width() - total) / 2.0
        max_h = float(self.height() - 2)

        for i, bh in enumerate(self.bar_heights):
            # Dynamic height smoothly between 3.5px and max_h (up to 18px)
            h = max(3.5, min(max_h, bh * max_h))
            y = (self.height() - h) / 2.0
            x = x0 + i * (bar_w + gap)
            p.drawRoundedRect(QRectF(x, y, bar_w, h), bar_w / 2.0, bar_w / 2.0)


class MoreButton(QPushButton):
    """Round button drawing three dots (no glyph dependency)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hovered = self.underMouse()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 40 if hovered else 18))
        p.drawEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        p.setBrush(QColor(255, 255, 255, 235 if hovered else 190))
        cy = self.height() / 2.0
        for dx in (-5, 0, 5):
            p.drawEllipse(QRectF(self.width() / 2.0 + dx - 1.4, cy - 1.4, 2.8, 2.8))



class Switch(QCheckBox):
    """iOS-style switch drawn in place of the checkbox; same API as QCheckBox (isChecked, toggled...)."""
    _TW, _TH = 38, 22

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pos = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)  # no overshoot
        self._anim.valueChanged.connect(self._on_tick)
        self.toggled.connect(self._animate)

    def _on_tick(self, v):
        self._pos = float(v)
        self.update()

    def _animate(self, on: bool):
        self._anim.stop()
        if not self.isVisible():  # initial state while building the UI: no slide
            self._pos = 1.0 if on else 0.0
            return
        self._anim.setStartValue(self._pos)  # from where the knob is now, so rapid taps reverse smoothly
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def sizeHint(self):
        fm = self.fontMetrics()
        w = self._TW + (10 + fm.horizontalAdvance(self.text()) if self.text() else 0)
        return QSize(w + 2, max(self._TH + 4, fm.height() + 4))

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, a0):
        if self._anim.state() != QVariantAnimation.State.Running:
            self._pos = 1.0 if self.isChecked() else 0.0  # setChecked under blockSignals
        t = self._pos
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        tw, th = self._TW, self._TH
        y = (self.height() - th) / 2.0
        off, on = QColor(120, 120, 128, 82), QColor(ACCENT)
        track = QColor(
            round(off.red() + (on.red() - off.red()) * t), round(off.green() + (on.green() - off.green()) * t),
            round(off.blue() + (on.blue() - off.blue()) * t), round(off.alpha() + (255 - off.alpha()) * t))
        if not self.isEnabled():
            track.setAlpha(track.alpha() // 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, y, tw, th), th / 2.0, th / 2.0)
        d = th - 4.0
        x = 2.0 + (tw - d - 4.0) * t
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QRectF(x, y + 2.8, d, d))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(x, y + 2.0, d, d))
        if self.text():
            p.setFont(self.font())
            p.setPen(self.palette().color(QPalette.ColorGroup.Active if self.isEnabled() else QPalette.ColorGroup.Disabled,
                                          QPalette.ColorRole.WindowText))
            p.drawText(QRectF(tw + 10, 0, self.width() - tw - 10, self.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())


_ASSETS = get_asset_path().replace("\\", "/")


class AnimatedText(QWidget):
    """Single-line text that animates its changes.
    - Replacing text (state change): the old line lifts and fades out while the new one rises in.
    - Growing text (live preview): the existing words stay put and only the new words fade in;
      when the line overflows it scrolls left under a soft fade, like a caption."""

    def __init__(self, text: str, font: QFont, parent=None):
        super().__init__(parent)
        self._font = font
        self._text = text
        self._prev = ""
        self._mode = "swap"
        self._p = 1.0
        self._x0 = 0.0
        self._x_cur = 0.0
        self._ease = QEasingCurve(QEasingCurve.Type.OutCubic)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(240)
        self._anim.valueChanged.connect(self._on_tick)

    def text(self) -> str:
        return self._text

    def setText(self, text: str):
        if text == self._text:
            return
        self._x0 = self._x_cur
        self._mode = "grow" if (self._text and text.startswith(self._text)) else "swap"
        self._prev = self._text
        self._text = text
        self._p = 0.0
        self._anim.stop()
        self._anim.setDuration(160 if self._mode == "grow" else 240)
        self._anim.start()

    def _on_tick(self, v):
        self._p = float(v)
        self.update()

    def _target_x(self, fm: QFontMetricsF, text: str) -> float:
        tw = fm.horizontalAdvance(text)
        return 0.0 if tw <= self.width() else self.width() - tw

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(self._font)
        p.setPen(QColor(255, 255, 255))
        fm = QFontMetricsF(self._font)
        base_y = (self.height() + fm.ascent() - fm.descent()) / 2.0
        e = self._ease.valueForProgress(self._p)

        if self._mode == "swap":
            w = self.width()
            if self._prev and e < 1.0:
                p.setOpacity(1.0 - e)
                p.drawText(QPointF(0, base_y - 7 * e), fm.elidedText(self._prev, Qt.TextElideMode.ElideRight, w))
            p.setOpacity(e)
            p.drawText(QPointF(0, base_y + 7 * (1.0 - e)), fm.elidedText(self._text, Qt.TextElideMode.ElideRight, w))
            self._x_cur = 0.0
            return

        tx = self._target_x(fm, self._text)
        x = self._x0 + (tx - self._x0) * e
        self._x_cur = x
        prefix, tail = self._prev, self._text[len(self._prev):]
        p.drawText(QPointF(x, base_y), prefix)
        p.setOpacity(e)
        p.drawText(QPointF(x + fm.horizontalAdvance(prefix), base_y), tail)
        if x < -0.5:  # overflowing: fade the left edge into the capsule
            p.setOpacity(1.0)
            g = QLinearGradient(0, 0, 26, 0)
            g.setColorAt(0.0, QColor(0, 0, 0, 255))
            g.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.fillRect(QRectF(0, 0, 26, self.height()), QBrush(g))


class ValueRow(QWidget):
    """iOS-style row: title on the left, current value and a pop-up chevron on the right.
    Tapping opens a rounded, translucent menu with the current choice checked.
    Provides smooth animated glass hover highlights and value transitions."""
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, title: str, font_family: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._family = font_family
        self._items = []
        self._idx = -1
        self._disabled = set()
        self._pressed = False
        self._hover_alpha = 0.0
        self._val_alpha = 1.0
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._hover_anim = QVariantAnimation(self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_anim.valueChanged.connect(self._on_hover_tick)

        self._val_anim = QVariantAnimation(self)
        self._val_anim.setDuration(130)
        self._val_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._val_anim.valueChanged.connect(self._on_val_tick)

    def _on_hover_tick(self, val):
        self._hover_alpha = float(val)
        self.update()

    def _on_val_tick(self, val):
        self._val_alpha = float(val)
        self.update()

    def clear(self):
        self._items, self._idx = [], -1
        self._disabled = set()
        self.update()

    def setItemEnabled(self, i: int, enabled: bool):
        if enabled:
            self._disabled.discard(i)
        else:
            self._disabled.add(i)

    def addItem(self, text, data=None):
        self._items.append((text, data))
        if self._idx < 0:
            self._idx = 0
        self.update()

    def count(self):
        return len(self._items)

    def currentIndex(self):
        return self._idx

    def setCurrentIndex(self, i: int):
        if 0 <= i < len(self._items) and i != self._idx:
            self._idx = i
            self._val_anim.stop()
            self._val_anim.setStartValue(0.2)
            self._val_anim.setEndValue(1.0)
            self._val_anim.start()
            self.currentIndexChanged.emit(i)

    def currentData(self):
        return self._items[self._idx][1] if self._idx >= 0 else None

    def currentText(self):
        return self._items[self._idx][0] if self._idx >= 0 else ""

    def itemText(self, i: int) -> str:
        return self._items[i][0] if 0 <= i < len(self._items) else ""

    def itemData(self, i: int):
        return self._items[i][1] if 0 <= i < len(self._items) else None

    def enterEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_alpha)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()

    def leaveEvent(self, a0):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover_alpha)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()

    def mousePressEvent(self, a0):
        if a0.button() == Qt.MouseButton.LeftButton:
            self._pressed = True  # feedback on press, not release
            self.update()

    def mouseReleaseEvent(self, a0):
        self._pressed = False
        self.update()
        if a0.button() != Qt.MouseButton.LeftButton or not self._items:
            return

        pill = self.window()
        has_topmost_timer = hasattr(pill, "_topmost_timer") and isinstance(pill, FloatingPill)
        if has_topmost_timer:
            pill._topmost_timer.stop()

        menu = QMenu(self)
        menu.setWindowFlags(
            Qt.WindowType.Popup |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet(f"""
            QMenu {{ background: rgba(40,40,42,0.98); border: 1px solid rgba(255,255,255,0.10);
                     border-radius: 10px; padding: 5px; color: #fff; }}
            QMenu::item {{ padding: 6px 22px 6px 30px; border-radius: 6px; margin: 0; }}
            QMenu::item:selected {{ background: {ACCENT}; color: #ffffff; }}
            QMenu::item:disabled {{ color: rgba(235,235,245,0.30); background: transparent; }}
            QMenu::indicator {{ width: 14px; height: 14px; left: 9px; }}
            QMenu::indicator:checked {{ image: url({_ASSETS}/check_white.svg); }}
        """)
        menu.setFont(QFont(self._family, 10))
        for i, (text, _) in enumerate(self._items):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(i == self._idx)
            act.setEnabled(i not in self._disabled)
            act.triggered.connect(lambda _=False, i=i: self.setCurrentIndex(i))

        # Ensure the menu stays strictly in front of FloatingPill on Windows
        menu.aboutToShow.connect(lambda: (_force_topmost(menu), menu.raise_()))
        QTimer.singleShot(0, lambda: (_force_topmost(menu), menu.raise_()))

        try:
            menu.exec(self.mapToGlobal(QPoint(0, self.height() + 2)))
        finally:
            if has_topmost_timer and pill.isVisible():
                pill._topmost_timer.start(2000)

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Smooth animated glass highlight on hover
        if self._hover_alpha > 0.01 or self._pressed:
            p.fillRect(self.rect(), QColor(255, 255, 255, int(12 * self._hover_alpha) + (14 if self._pressed else 0)))

        f = QFont(self._family, 10)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(14, 0, 96, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._title)

        cx, cy = self.width() - 18, self.height() / 2.0
        pen_alpha = int(120 + 85 * self._hover_alpha)
        pen = QPen(QColor(255, 255, 255, pen_alpha), 1.5,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(cx - 3, cy - 2.5), QPointF(cx, cy - 5.5), QPointF(cx + 3, cy - 2.5)]))
        p.drawPolyline(QPolygonF([QPointF(cx - 3, cy + 2.5), QPointF(cx, cy + 5.5), QPointF(cx + 3, cy + 2.5)]))

        fm = QFontMetricsF(f)
        vr = QRectF(112, 0, self.width() - 112 - 34, self.height())
        val_pen_alpha = int((150 + 50 * self._hover_alpha) * self._val_alpha)
        p.setPen(QColor(255, 255, 255, val_pen_alpha))
        p.drawText(vr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   fm.elidedText(self.currentText(), Qt.TextElideMode.ElideRight, vr.width()))


class AnimatedVectorIcon(QWidget):
    """
    High-DPI vector icon widget with 60 FPS live micro-animations (strictly zero emojis).
    - 'connected': Apple SF-style vector mic with a live radiating acoustic wave ring.
    - 'switched': Smoothly rotating circular dual-arrows showing active handoff.
    - 'unplugged': Coral warning triangle with a gentle pulse.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)
        self.mode = "connected"
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def set_mode(self, mode: str):
        self.mode = mode
        self.update()

    def _tick(self):
        if not self.isVisible():
            return
        self.phase += 0.09
        self.update()

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QRectF(self.rect()).center()

        if self.mode == "connected":
            # Live subtle soundwave ring radiating from mic
            pulse = 0.5 + 0.5 * math.sin(self.phase * 2.0)
            halo_r = 7.0 + 3.0 * pulse
            p.setPen(QPen(QColor(48, 209, 88, int(70 * (1.0 - pulse))), 1.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(c, halo_r, halo_r)

            # Apple-style vector microphone
            p.setPen(QPen(QColor(255, 255, 255), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(QBrush(QColor(255, 255, 255)))
            # glyph spans y -7..+7 so it sits on the optical centre of the halo
            p.drawRoundedRect(QRectF(c.x() - 3.0, c.y() - 7.0, 6.0, 8.5), 3.0, 3.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(c.x() - 5.5, c.y() - 4.8, 11.0, 9.3), 180 * 16, 180 * 16)
            p.drawLine(QPointF(c.x(), c.y() + 4.5), QPointF(c.x(), c.y() + 7.0))
            p.drawLine(QPointF(c.x() - 3.5, c.y() + 7.0), QPointF(c.x() + 3.5, c.y() + 7.0))

        elif self.mode == "switched":
            # Smoothly rotating circular dual-arrows
            rot = math.degrees(self.phase * 2.2) % 360
            p.save()
            p.translate(c)
            p.rotate(rot)
            p.setPen(QPen(QColor(48, 209, 88), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = 6.8
            p.drawArc(QRectF(-r, -r, 2 * r, 2 * r), 25 * 16, 135 * 16)
            p.drawArc(QRectF(-r, -r, 2 * r, 2 * r), 205 * 16, 135 * 16)
            p.setBrush(QBrush(QColor(48, 209, 88)))
            # Tip 1 at end of arc 1
            p.drawPolygon(QPolygonF([QPointF(-r + 1.2, -2.5), QPointF(-r - 2.5, -2.5), QPointF(-r - 0.5, 1.2)]))
            # Tip 2 at end of arc 2
            p.drawPolygon(QPolygonF([QPointF(r - 1.2, 2.5), QPointF(r + 2.5, 2.5), QPointF(r + 0.5, -1.2)]))
            p.restore()

        else:  # "unplugged"
            # Pulsing coral warning triangle with exclamation glyph
            pulse = 0.5 + 0.5 * math.sin(self.phase * 2.2)
            alpha = int(195 + 60 * pulse)
            p.setPen(QPen(QColor(255, 69, 58, alpha), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.setBrush(Qt.BrushStyle.NoBrush)
            tri = QPolygonF([QPointF(c.x(), c.y() - 7.5), QPointF(c.x() + 8.0, c.y() + 6.5), QPointF(c.x() - 8.0, c.y() + 6.5)])
            p.drawPolygon(tri)
            # Exclamation point
            p.drawLine(QPointF(c.x(), c.y() - 3.0), QPointF(c.x(), c.y() + 1.5))
            p.drawPoint(QPointF(c.x(), c.y() + 4.5))


class MicNotificationPill(QWidget):
    """
    Temporary 'pseudo-capsule' banner popping up smoothly directly above the main pill/line
    with Dynamic Island slide-and-spring physics (zero emojis, animated vector icons).
    """
    sig_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.w, self.h = 300, 40
        self.setFixedSize(self.w, self.h)
        self.font_family = ui_font_family()
        self._target_pos = QPoint()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(8)
        center = Qt.AlignmentFlag.AlignVCenter

        self.animated_icon = AnimatedVectorIcon(self)
        lay.addWidget(self.animated_icon, 0, center)

        self.text_label = QLabel(self)
        self.text_label.setFont(QFont(self.font_family, 9, QFont.Weight.Medium))
        self.text_label.setStyleSheet("color: #ffffff; background: transparent;")
        self.text_label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(self.text_label, 1, center)

        # fixed-height pill, centred: a bare QLabel stretched to the row height and looked misaligned
        self.badge = QLabel("ACTIVE", self)
        self.badge.setFont(QFont(self.font_family, 7, QFont.Weight.DemiBold))
        self.badge.setFixedHeight(18)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.badge, 0, center)

        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.hide_animated)

        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(220)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_anim.finished.connect(self._on_hidden)

        self.slide_anim = QVariantAnimation(self)
        self.slide_anim.setDuration(280)
        self.slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)  # critically damped: no bounce on a passive banner
        self.slide_anim.valueChanged.connect(self._apply_slide_pos)

    def _apply_slide_pos(self, pt):
        self.move(pt)

    def show_event(self, mic_name: str, status: str = "connected", anchor_rect: QRect = QRect()):
        mode, prefix, badge, rgb = {
            "switched": ("switched", "Switched to", "ACTIVE", "48,209,88"),
            "connected": ("connected", "Connected", "ACTIVE", "48,209,88"),
        }.get(status, ("unplugged", "Unplugged", "OFFLINE", "255,69,58"))
        self.animated_icon.set_mode(mode)
        self.badge.setText(badge)
        self.badge.setStyleSheet(f"color: rgb({rgb}); background: rgba({rgb},0.18); border-radius: 9px; padding: 0 8px;")
        self.badge.adjustSize()
        # elide by pixels, not characters, so the text never runs into the badge
        room = self.w - 20 - self.animated_icon.width() - self.badge.sizeHint().width() - 16
        fm = self.text_label.fontMetrics()
        self.text_label.setText(fm.elidedText(f"{prefix}  {mic_name}", Qt.TextElideMode.ElideRight, room))

        if not anchor_rect.isNull():
            target_x = anchor_rect.center().x() - self.w // 2
            target_y = anchor_rect.top() - self.h - 10
        else:
            screen = QApplication.primaryScreen()
            if screen:
                r = screen.availableGeometry()
                target_x = r.x() + (r.width() - self.w) // 2
                target_y = r.y() + r.height() - self.h - 90
            else:
                target_x, target_y = 100, 100

        self._target_pos = QPoint(target_x, target_y)
        start_pos = QPoint(target_x, target_y + 14)  # slides up from behind the capsule
        self.setGeometry(start_pos.x(), start_pos.y(), self.w, self.h)

        self.setWindowOpacity(0.0)
        self.show()
        _force_topmost(self)

        self.slide_anim.stop()
        self.slide_anim.setStartValue(start_pos)
        self.slide_anim.setEndValue(self._target_pos)
        self.slide_anim.start()

        self.fade_anim.stop()
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()
        self.dismiss_timer.start(3400)

    def hide_animated(self):
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.start()

    def _on_hidden(self):
        if self.windowOpacity() <= 0.05:
            self.hide()


    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        r = rect.height() / 2.0
        p.setBrush(QBrush(QColor(28, 28, 30, 245)))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1.0))
        p.drawRoundedRect(rect, r, r)

    def mousePressEvent(self, a0):
        self.sig_clicked.emit()
        self.hide_animated()


class MeetingBar(QWidget):
    """Bar above the capsule for meetings: offers to take notes, then shows live captions."""
    sig_start = pyqtSignal()
    sig_stop = pyqtSignal()
    sig_dismiss = pyqtSignal()

    W = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(self.W)
        font = ui_font_family()
        self._app = ""
        self._started = 0.0
        self._lines: list = []

        frame = QFrame(self)
        frame.setObjectName("meetingFrame")
        frame.setStyleSheet(
            "#meetingFrame { background: rgba(12, 12, 12, 0.94); border: 1px solid rgba(255,255,255,0.12);"
            " border-radius: 16px; }"
            "QLabel { color: #ffffff; background: transparent; }"
            "QPushButton { color: #000000; background: #ffffff; border: none; border-radius: 11px;"
            " padding: 4px 12px; font-weight: 600; }"
            "QPushButton#ghost { color: rgba(255,255,255,0.7); background: transparent; padding: 4px 6px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(6)

        row = QHBoxLayout()
        self.title = QLabel(frame)
        self.title.setFont(QFont(font, 9, QFont.Weight.DemiBold))
        row.addWidget(self.title, 1)
        self.btn = QPushButton(frame)
        self.btn.setFont(QFont(font, 8))
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self._on_btn)
        row.addWidget(self.btn)
        self.close_btn = QPushButton("✕", frame)
        self.close_btn.setObjectName("ghost")
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self._on_close)
        row.addWidget(self.close_btn)
        lay.addLayout(row)

        self.captions = QLabel(frame)
        self.captions.setFont(QFont(font, 9))
        self.captions.setWordWrap(True)
        self.captions.setTextFormat(Qt.TextFormat.RichText)
        self.captions.hide()
        lay.addWidget(self.captions)

        self._clock = QTimer(self)
        self._clock.timeout.connect(self._tick)

    @property
    def recording(self) -> bool:
        return self._started > 0

    def show_prompt(self, app: str, anchor_rect: QRect = QRect()):
        self._app, self._started, self._lines = app, 0.0, []
        self.title.setText(f"Meeting detected · {app}")
        self.btn.setText("Start notes")
        self.close_btn.show()
        self.captions.hide()
        self._place(anchor_rect)

    def show_recording(self, anchor_rect: QRect = QRect()):
        self._started = time.time()
        self.btn.setText("Stop")
        self.close_btn.hide()
        self.captions.setText("<span style='color:rgba(255,255,255,0.5)'>Listening…</span>")
        self.captions.show()
        self._tick()
        self._clock.start(1000)
        self._place(anchor_rect)

    def add_line(self, who: str, text: str):
        self._lines = (self._lines + [(who, text)])[-3:]
        esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def _chip(w: str) -> str:
            w_low = w.lower()
            if "you" in w_low:
                col, bg = "#38bdf8", "rgba(56,189,248,0.2)"
            elif "1" in w_low:
                col, bg = "#34d399", "rgba(52,211,153,0.2)"
            elif "2" in w_low:
                col, bg = "#fbbf24", "rgba(251,191,36,0.2)"
            elif "3" in w_low:
                col, bg = "#c084fc", "rgba(192,132,252,0.2)"
            else:
                col, bg = "#fb7185", "rgba(251,113,133,0.2)"
            return f"<span style='color:{col}; background:{bg}; font-weight:700; padding:1px 6px; border-radius:4px;'>{esc(w)}</span>"

        self.captions.setText("<br>".join(
            f"{_chip(w)} {esc(t)}" for w, t in self._lines))
        self.adjustSize()

    def finish(self):
        self._started = 0.0
        self._clock.stop()
        self.hide()

    def _tick(self):
        secs = int(time.time() - self._started)
        self.title.setText(f"● Taking notes · {self._app} · {secs // 60:02d}:{secs % 60:02d}")

    def _on_btn(self):
        (self.sig_stop if self.recording else self.sig_start).emit()

    def _on_close(self):
        self.hide()
        self.sig_dismiss.emit()

    def _place(self, anchor_rect: QRect):
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if not anchor_rect.isNull():
            x, bottom = anchor_rect.center().x() - self.W // 2, anchor_rect.top() - 10
        elif screen:
            r = screen.availableGeometry()
            x, bottom = r.x() + (r.width() - self.W) // 2, r.y() + r.height() - 90
        else:
            x, bottom = 100, 400
        self.move(x, bottom - self.height())
        self.show()
        _force_topmost(self)
        self.raise_()

    def resizeEvent(self, a0):
        # Grow upward as captions wrap, so the bar never covers the capsule below it
        if self.isVisible() and a0.oldSize().height() > 0:
            self.move(self.x(), self.y() - (a0.size().height() - a0.oldSize().height()))
        super().resizeEvent(a0)


class FloatingPill(QWidget):
    """
    Black-and-white capsule HUD.
    Capsule (360x44) morphs into a grouped settings panel (360x312), anchored at its
    bottom-centre. One progress value drives geometry, corner radius and a content crossfade.
    When idle, it gracefully minimizes into a sleek rounded line (64x6) at the bottom.
    """
    sig_mic_changed = pyqtSignal(object)
    sig_language_changed = pyqtSignal(str)
    sig_tone_changed = pyqtSignal(str)
    sig_model_changed = pyqtSignal(str)
    sig_open_dashboard = pyqtSignal()
    sig_update_requested = pyqtSignal()
    sig_hide_idle_changed = pyqtSignal(bool)

    LANGS = [
        ("auto", "Auto Detect"), ("en-in", "English (India) / Hinglish"), ("or", "Odia / Odia-English"),
        ("hi", "Hindi"), ("en", "English (US/UK)"), ("translate", "Any language → English"),
        ("es", "Spanish"), ("fr", "French"), ("de", "German"), ("zh", "Chinese"), ("ja", "Japanese"),
        ("pt", "Portuguese"), ("it", "Italian"), ("ar", "Arabic"), ("ru", "Russian"),
        ("ko", "Korean"), ("nl", "Dutch"), ("tr", "Turkish"),
    ]
    TONES = [
        ("auto", "Auto"), ("smart_clean", "Smart Clean"), ("developer", "Developer"), ("email", "Email"),
        ("bullets", "Bullet Points"), ("verbatim", "Verbatim"),
    ]

    def __init__(self, current_mic_name: str = "Microphone", current_language: str = "en", current_model: str = "base", hide_when_idle: bool = False):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.font_family = ui_font_family()
        self._drag_pos = QPoint()
        self.is_expanded_hud = False
        self.current_state = "idle"
        self.current_mic_name = current_mic_name
        self.current_language = current_language
        self.current_model = current_model
        self.hide_when_idle = hide_when_idle
        self._recent_mics = []

        self._cap_w, self._cap_h = 360, 44
        self._hud_w, self._hud_h = 360, 400
        self._line_w, self._line_h = 76, 8
        self._t = 0.0            # 0 = capsule, 1 = HUD
        self._line_t = 0.0       # 0 = capsule, 1 = minimal line
        self._mode = "capsule"   # "capsule", "line", "hud"
        self._is_line_hovered = False
        self._dl = -1            # model download percent, -1 when not downloading
        self._anchor = QPoint()  # bottom-centre of the window during a morph

        self.morph_anim = QVariantAnimation(self)
        self.morph_anim.setDuration(360)
        self.morph_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.morph_anim.valueChanged.connect(self._apply_t)
        self.morph_anim.finished.connect(self._on_morph_finished)

        self.line_anim = QVariantAnimation(self)
        self.line_anim.setDuration(380)
        self.line_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.line_anim.valueChanged.connect(self._apply_line_t)
        self.line_anim.finished.connect(self._on_line_anim_finished)

        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(380)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.fade_anim.finished.connect(self._on_fade_finished)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._fade_out_and_hide)

        # Level smoothing timer for HUD live input bar (60 FPS liquid spring decay)
        self._target_level = 0.0
        self._smoothed_level = 0.0
        self._level_timer = QTimer(self)
        self._level_timer.timeout.connect(self._tick_level)
        self._level_timer.start(16)

        # Periodic topmost elevation keeper (keeps capsule strictly above active windows)
        self._topmost_timer = QTimer(self)
        self._topmost_timer.timeout.connect(self.force_topmost)
        self._topmost_timer.start(2000)

        # Companion pseudo-capsule for mic connect/disconnect notifications
        self.mic_pill = MicNotificationPill()
        self.mic_pill.sig_clicked.connect(self.expand_to_hud)

        self._build_capsule()
        self._build_hud()
        self.setStyleSheet(f"QLabel {{ background: transparent; border: none; color: {FG}; }}")
        self._apply_t(0.0)
        self.position_bottom_center()

    def force_topmost(self):
        """Force the capsule window to stay at the very top of the Windows z-order above all active apps."""
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QMenu) and w.isVisible():
                return
        if self.isVisible():
            _force_topmost(self)
            self.raise_()

    def showEvent(self, a0):
        super().showEvent(a0)
        self.force_topmost()

    def _tick_level(self):
        if not self.is_expanded_hud or not hasattr(self, "live_level_bar"):
            return
        tgt = self._target_level
        cur = self._smoothed_level
        if tgt > cur:
            self._smoothed_level = cur + (tgt - cur) * 0.60
        else:
            self._smoothed_level = cur + (tgt - cur) * 0.18
        self.live_level_bar.setValue(int(self._smoothed_level * 100))

    # ---------- construction ----------

    def _font(self, size: int, weight=QFont.Weight.Normal) -> QFont:
        return QFont(self.font_family, size, weight)

    def _build_capsule(self):
        self.capsule_widget = QWidget(self)
        self.capsule_widget.setFixedSize(self._cap_w, self._cap_h)
        lay = QHBoxLayout(self.capsule_widget)
        lay.setContentsMargins(14, 0, 10, 0)
        lay.setSpacing(10)

        self.indicator = StateIndicator(self.capsule_widget)
        lay.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        self.text_label = AnimatedText(self.current_mic_name, self._font(10, QFont.Weight.Medium), self.capsule_widget)
        self.text_label.setFixedHeight(24)
        lay.addWidget(self.text_label, 1, Qt.AlignmentFlag.AlignVCenter)

        self.lang_badge = QLabel(self._lang_short(self.current_language), self.capsule_widget)
        self.lang_badge.setFont(self._font(8, QFont.Weight.Medium))
        self.lang_badge.setFixedHeight(20)
        self.lang_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lang_badge.setStyleSheet(
            f"QLabel {{ color: {FG_DIM}; background: {FILL}; border-radius: 10px; padding: 0px 8px; }}"
        )
        lay.addWidget(self.lang_badge, 0, Qt.AlignmentFlag.AlignVCenter)

        self.visualizer = WaveformBars(self.capsule_widget)
        lay.addWidget(self.visualizer, 0, Qt.AlignmentFlag.AlignVCenter)

        self.btn_more = MoreButton(self.capsule_widget)
        self.btn_more.clicked.connect(self.toggle_morph_hud)
        lay.addWidget(self.btn_more, 0, Qt.AlignmentFlag.AlignVCenter)

    def _row(self, title: str, widget: QWidget, trailing: bool = False) -> QWidget:
        """iOS settings row; trailing=True pins a compact control (switch) to the right edge."""
        row = QWidget(self)
        row.setFixedHeight(44)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)
        lbl = QLabel(title, row)
        lbl.setFont(self._font(10))
        if trailing:
            lay.addWidget(lbl, 1, Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        else:
            lbl.setFixedWidth(98)
            lay.addWidget(lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            lay.addWidget(widget, 1, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_hud(self):
        self.hud_widget = QWidget(self)
        self.hud_widget.setFixedSize(self._hud_w, self._hud_h)
        lay = QVBoxLayout(self.hud_widget)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)

        # Brand Squircle Logo
        logo_path = get_asset_path("app_icon_square.png")
        if not os.path.exists(logo_path):
            logo_path = get_asset_path("logo.jpg")
        self.hud_logo = QLabel(self)
        self.hud_logo.setFixedSize(26, 26)
        self.hud_logo.setPixmap(get_squircle_pixmap(logo_path, size=26, radius=6.5))
        header.addWidget(self.hud_logo, 0, Qt.AlignmentFlag.AlignVCenter)

        title = QLabel("OpenFlow", self)
        title.setFont(self._font(12, QFont.Weight.DemiBold))
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)

        header.addStretch()
        self.btn_minimize = QPushButton("Done", self)
        self.btn_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimize.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_minimize.setFont(self._font(10, QFont.Weight.DemiBold))
        self.btn_minimize.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {ACCENT}; border: none; padding: 4px 6px; border-radius: 6px; }}
            QPushButton:hover {{ background: rgba(10, 132, 255, 0.14); }}
            QPushButton:pressed {{ background: rgba(10, 132, 255, 0.24); }}
        """)
        self.btn_minimize.clicked.connect(self.collapse_to_capsule)
        header.addWidget(self.btn_minimize, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(header)

        group = QFrame(self)
        group.setObjectName("Group")
        group.setStyleSheet(f"QFrame#Group {{ background: {FILL}; border-radius: 12px; }}")
        g = QVBoxLayout(group)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(0)

        self.mic_combo = ValueRow("Microphone", self.font_family, self)
        self.populate_mics()
        self.mic_combo.currentIndexChanged.connect(self._on_mic_selected)

        self.lang_combo = ValueRow("Language", self.font_family, self)
        self.populate_languages()
        self.lang_combo.currentIndexChanged.connect(self._on_language_selected)

        self.tone_combo = ValueRow("Style", self.font_family, self)
        for key, label in self.TONES:
            self.tone_combo.addItem(label, key)
        self.tone_combo.currentIndexChanged.connect(self._on_tone_selected)

        self.model_combo = ValueRow("Model", self.font_family, self)
        self.populate_models()
        self.model_combo.currentIndexChanged.connect(self._on_model_selected)

        self.live_level_bar = QProgressBar(self)
        self.live_level_bar.setRange(0, 100)
        self.live_level_bar.setValue(0)
        self.live_level_bar.setTextVisible(False)
        self.live_level_bar.setFixedHeight(4)
        self.live_level_bar.setStyleSheet(f"""
            QProgressBar {{ background: {HAIRLINE}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {GREEN}; border-radius: 2px; }}
        """)


        self.cb_hide_idle_hud = Switch("", self)
        self.cb_hide_idle_hud.setChecked(self.hide_when_idle)
        self.cb_hide_idle_hud.toggled.connect(self._on_hud_hide_idle_toggled)

        rows = [
            self.mic_combo,
            self.lang_combo,
            self.tone_combo,
            self.model_combo,
            self._row("Hide when idle", self.cb_hide_idle_hud, trailing=True),
            self._row("Input level", self.live_level_bar),
        ]
        for i, r in enumerate(rows):
            g.addWidget(r)
            if i < len(rows) - 1:
                sep = QFrame(self)
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {HAIRLINE}; margin-left: 14px; margin-right: 14px;")
                g.addWidget(sep)

        # Dedicated live download progress row in HUD
        self.hud_download_sep = QFrame(self)
        self.hud_download_sep.setFixedHeight(1)
        self.hud_download_sep.setStyleSheet(f"background: {HAIRLINE}; margin-left: 14px; margin-right: 14px;")
        g.addWidget(self.hud_download_sep)

        self.hud_download_row = QWidget(self)
        self.hud_download_row.setFixedHeight(44)
        dl_lay = QHBoxLayout(self.hud_download_row)
        dl_lay.setContentsMargins(14, 0, 12, 0)
        dl_lay.setSpacing(10)

        self.hud_download_title = QLabel("Download", self.hud_download_row)
        self.hud_download_title.setFont(self._font(10))
        self.hud_download_title.setFixedWidth(98)
        dl_lay.addWidget(self.hud_download_title)

        dl_bar_container = QWidget(self.hud_download_row)
        dl_bar_lay = QVBoxLayout(dl_bar_container)
        dl_bar_lay.setContentsMargins(0, 0, 0, 0)
        dl_bar_lay.setSpacing(3)

        self.hud_download_bar = QProgressBar(dl_bar_container)
        self.hud_download_bar.setRange(0, 100)
        self.hud_download_bar.setValue(0)
        self.hud_download_bar.setTextVisible(False)
        self.hud_download_bar.setFixedHeight(5)
        self.hud_download_bar.setStyleSheet(f"""
            QProgressBar {{ background: {HAIRLINE}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}
        """)
        self.hud_download_text = QLabel("Preparing...", dl_bar_container)
        self.hud_download_text.setFont(self._font(8))
        self.hud_download_text.setStyleSheet(f"color: {FG_DIM};")

        dl_bar_lay.addWidget(self.hud_download_bar)
        dl_bar_lay.addWidget(self.hud_download_text)
        dl_lay.addWidget(dl_bar_container, 1)
        g.addWidget(self.hud_download_row)

        self.hud_download_sep.hide()
        self.hud_download_row.hide()

        lay.addWidget(group)
        lay.addStretch()

        self.btn_update = QPushButton("Update Available · Install", self)
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_update.setFixedHeight(36)
        self.btn_update.setFont(self._font(10, QFont.Weight.DemiBold))
        self.btn_update.setStyleSheet(f"""
            QPushButton {{ background: {ACCENT}; color: #ffffff; border: none; border-radius: 10px; }}
            QPushButton:hover {{ background: #3395FF; }}
            QPushButton:pressed {{ background: #0063CC; }}
            QPushButton:disabled {{ background: rgba(10,132,255,0.45); color: rgba(255,255,255,0.7); }}
        """)
        self.btn_update.hide()
        self.btn_update.clicked.connect(self._on_update_clicked)
        lay.addWidget(self.btn_update)

        self.btn_transfer = QPushButton("Open Dashboard", self)
        self.btn_transfer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_transfer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_transfer.setFixedHeight(36)
        self.btn_transfer.setFont(self._font(10, QFont.Weight.DemiBold))
        self.btn_transfer.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,0.12); color: #ffffff; border: none; border-radius: 10px; }
            QPushButton:hover { background: rgba(255,255,255,0.18); }
            QPushButton:pressed { background: rgba(255,255,255,0.26); }
        """)
        self.btn_transfer.clicked.connect(self._on_transfer_clicked)
        lay.addWidget(self.btn_transfer)

    # ---------- morph ----------

    def _apply_t(self, t):
        t = float(t)
        self._t = t
        w = round(self._cap_w + (self._hud_w - self._cap_w) * t)
        h = round(self._cap_h + (self._hud_h - self._cap_h) * t)
        if not self._anchor.isNull():
            self.setGeometry(self._anchor.x() - w // 2, self._anchor.y() - h, w, h)
        elif self.size() != self.capsule_widget.size():
            self.resize(w, h)

        # content stays bottom-centred, window clips it while growing
        self.capsule_widget.move((w - self._cap_w) // 2, h - self._cap_h)
        self.hud_widget.move((w - self._hud_w) // 2, h - self._hud_h)

        cap_a = max(0.0, 1.0 - t * 2.6)
        hud_a = max(0.0, min(1.0, (t - 0.35) * 2.2))
        self._set_content_alpha(self.capsule_widget, cap_a)
        self._set_content_alpha(self.hud_widget, hud_a)
        self.update()

    def _set_content_alpha(self, w: QWidget, a: float):
        from PyQt6.QtWidgets import QGraphicsOpacityEffect
        vis = a > 0.01
        if w.isVisible() != vis:
            w.setVisible(vis)
        eff = w.graphicsEffect()
        if a >= 0.99:
            if eff is not None:
                w.setGraphicsEffect(None)
        else:
            if eff is None:
                eff = QGraphicsOpacityEffect(w)
                w.setGraphicsEffect(eff)
            eff.setOpacity(a)  # type: ignore[attr-defined]

    def _morph_to(self, target: float):
        geo = self.geometry()
        self._anchor = QPoint(geo.center().x(), geo.bottom() + 1)
        self.morph_anim.stop()
        self.morph_anim.setStartValue(self._t)
        self.morph_anim.setEndValue(target)
        self.morph_anim.start()

    def toggle_morph_hud(self):
        self.collapse_to_capsule() if self.is_expanded_hud else self.expand_to_hud()

    def expand_to_hud(self):
        self.is_expanded_hud = True
        self.hide_timer.stop()
        self.fade_anim.stop()
        self.setWindowOpacity(1.0)
        self.show()
        _force_topmost(self)
        self._morph_to(1.0)

    def collapse_to_capsule(self):
        self.is_expanded_hud = False
        self._morph_to(0.0)

    def _on_morph_finished(self):
        self._apply_t(self._t)
        self.update()
        if not self.is_expanded_hud and self.hide_when_idle and self.current_state in ("idle", "pasted"):
            self.hide_timer.stop()
            self.hide_timer.start(1200)

    # ---------- line morph ----------

    def _on_hud_hide_idle_toggled(self, checked: bool):
        self.set_hide_when_idle(checked)
        self.sig_hide_idle_changed.emit(self.hide_when_idle)

    def set_hide_when_idle(self, hide: bool):
        self.hide_when_idle = hide
        if hasattr(self, "cb_hide_idle_hud"):
            self.cb_hide_idle_hud.blockSignals(True)
            self.cb_hide_idle_hud.setChecked(self.hide_when_idle)
            self.cb_hide_idle_hud.blockSignals(False)
        if self.hide_when_idle:
            if not self.is_expanded_hud and self.current_state in ("idle", "pasted") and (self._line_t >= 0.7 or self._mode == "line"):
                self._fade_out_and_hide()
        else:
            if not self.is_expanded_hud and not self.isVisible() and self.current_state == "idle":
                self.minimize_to_line()
                self.setWindowOpacity(0.0)
                self.show()
                _force_topmost(self)
                self.fade_anim.stop()
                self.fade_anim.setDuration(340)
                self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.fade_anim.setStartValue(0.0)
                self.fade_anim.setEndValue(1.0)
                self.fade_anim.start()

    def _apply_line_t(self, val):
        self._line_t = float(val)
        t = self._line_t
        target_w = 76 if (self._is_line_hovered and t > 0.85) else self._line_w
        target_h = 8 if (self._is_line_hovered and t > 0.85) else self._line_h
        w = round(self._cap_w - (self._cap_w - target_w) * t)
        h = round(self._cap_h - (self._cap_h - target_h) * t)

        screen = QApplication.primaryScreen()
        if screen:
            r = screen.availableGeometry()
            x = r.x() + (r.width() - w) // 2
            y = r.y() + r.height() - h - 35
            self.setGeometry(x, y, w, h)

        # Smooth organic content fade: begins softly at t=0.75 and reaches full opacity at t=0.0
        cap_a = max(0.0, min(1.0, (1.0 - t) / 0.75))
        cap_a = cap_a * cap_a * (3.0 - 2.0 * cap_a)  # smoothstep
        self._set_content_alpha(self.capsule_widget, cap_a)
        self.update()

    def minimize_to_line(self):
        if self.is_expanded_hud:
            return
        if self.hide_when_idle:
            self._fade_out_and_hide()
            return
        self._mode = "line"
        self.current_state = "idle"
        self.indicator.set_state("idle")
        self.visualizer.setVisible(False)
        self.line_anim.stop()
        self.line_anim.setDuration(400)
        self.line_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.line_anim.setStartValue(self._line_t)
        self.line_anim.setEndValue(1.0)
        self.line_anim.start()

    def expand_from_line(self):
        self._mode = "capsule"
        self.line_anim.stop()
        self.line_anim.setDuration(360)
        self.line_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.line_anim.setStartValue(self._line_t)
        self.line_anim.setEndValue(0.0)
        self.line_anim.start()

    def _on_line_anim_finished(self):
        self._apply_line_t(self._line_t)
        if self._line_t <= 0.05:
            self._mode = "capsule"
        elif self._line_t >= 0.95:
            self._mode = "line"
            if self.hide_when_idle:
                self.hide()
        self.update()

    def show_mic_event(self, mic_name: str, status: str = "connected"):
        """Spawn the pseudo-capsule notification above the main pill/line."""
        if hasattr(self, "mic_pill"):
            self.mic_pill.show_event(mic_name, status, anchor_rect=self.geometry())
        self.populate_mics()

    # ---------- data ----------

    def _lang_short(self, code: str) -> str:
        if code == "auto":
            return "AUTO"
        if code == "en-in":
            return "EN-IN"
        if code in ("or", "odia"):
            return "ODIA"
        if code == "translate":
            return "→EN"
        return code.upper()

    def populate_mics(self, recent_mics=None):
        if recent_mics is not None:
            self._recent_mics = list(recent_mics)
        self.mic_combo.blockSignals(True)
        curr_data = self.mic_combo.currentData()
        self.mic_combo.clear()
        self.mic_combo.addItem("System Default", None)
        for dev in list_microphones():
            is_active = (dev["name"] == self.current_mic_name)
            is_recent = (dev["name"] in self._recent_mics and not is_active)
            if is_active:
                name_display = f"● {dev['name']} (Active)"
            elif is_recent:
                name_display = f"↺ {dev['name']} (Recent)"
            else:
                name_display = dev["name"]
            self.mic_combo.addItem(name_display, dev["index"])
            if is_active or (curr_data is not None and curr_data == dev["index"]):
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        self.mic_combo.blockSignals(False)

    def populate_languages(self):
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        for code, label in self.LANGS:
            self.lang_combo.addItem(label, code)
            if code == self.current_language:
                self.lang_combo.setCurrentIndex(self.lang_combo.count() - 1)
        self.lang_combo.blockSignals(False)

    def populate_models(self, active_model=None):
        if active_model is not None:
            self.current_model = active_model
        if not hasattr(self, "model_combo"):
            return
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        models = [
            ("base", "Base · Balanced", "141 MB"),
            ("tiny", "Tiny · Fastest", "75 MB"),
            ("small", "Small · Accurate", "464 MB"),
            ("medium", "Medium · Best", "1.46 GB"),
        ]
        clean_active = self.current_model.replace(".en", "").lower()
        selected_idx = 0
        for idx, (m_id, label, size) in enumerate(models):
            active = m_id == clean_active or clean_active.startswith(m_id)
            downloaded = model_manager.is_ready(m_id)
            # picking a model never downloads it; downloads happen in the dashboard's Model Library
            self.model_combo.addItem(label if downloaded or active else f"{label}   \u2193 {size}", m_id)
            self.model_combo.setItemEnabled(idx, downloaded or active)
            if active:
                selected_idx = idx
        self.model_combo.setCurrentIndex(selected_idx)
        self.model_combo.blockSignals(False)

    def _on_model_selected(self, index: int):
        m_id = self.model_combo.itemData(index)
        if m_id:
            self.current_model = m_id
            self.sig_model_changed.emit(m_id)

    def update_connected_mic(self, mic_name: str):
        clean = mic_name.removeprefix("● ").strip()
        self.current_mic_name = clean
        if self.current_state == "idle":
            self.text_label.setText(clean)

    def update_language(self, lang_code: str):
        self.current_language = lang_code
        self.lang_badge.setText(self._lang_short(lang_code))

    def _on_mic_selected(self, index: int):
        self.update_connected_mic(self.mic_combo.currentText())
        self.sig_mic_changed.emit(self.mic_combo.currentData())

    def _on_language_selected(self, index: int):
        code = self.lang_combo.currentData()
        if code:
            self.update_language(code)
            self.sig_language_changed.emit(code)

    def _on_tone_selected(self, index: int):
        tone = self.tone_combo.currentData()
        if tone:
            self.sig_tone_changed.emit(tone)

    def _on_transfer_clicked(self):
        self.collapse_to_capsule()
        self.sig_open_dashboard.emit()

    def _on_update_clicked(self):
        self.btn_update.setText("Downloading update...")
        self.btn_update.setEnabled(False)
        self.sig_update_requested.emit()

    def show_update_available(self, version: str = ""):
        """Reveals the install button in the settings panel."""
        label = f"Update v{version} Available · Install" if version else "Update Available · Install"
        self.btn_update.setText(label)
        self.btn_update.setEnabled(True)
        self.btn_update.show()
        if not self.is_expanded_hud and self.isVisible():
            self.show_message(label, duration_ms=3000)

    def position_bottom_center(self):
        screen = QApplication.primaryScreen()
        if screen:
            r = screen.availableGeometry()
            self._anchor = QPoint()
            w = self._line_w if self._mode == "line" else self._cap_w
            h = self._line_h if self._mode == "line" else self._cap_h
            self.setGeometry(r.x() + (r.width() - w) // 2,
                             r.y() + r.height() - h - 35,
                             w, h)

    # ---------- state ----------

    def set_amplitude(self, level: float):
        self.visualizer.set_level(level)
        self._target_level = max(0.0, min(1.0, level))

    def show_listening(self, preset_name: str = "Listening"):
        if self.is_expanded_hud:
            return
        self.hide_timer.stop()
        was_hidden = not self.isVisible() or self.windowOpacity() < 0.1
        if self._mode == "line" or self._line_t > 0.05:
            self.expand_from_line()
        self.current_state = "listening"
        self.indicator.set_state("listening")
        self.text_label.setText(preset_name)
        self.lang_badge.setText(self._lang_short(self.current_language))
        self.visualizer.reset()
        self.visualizer.setVisible(True)
        self.update()

        self.fade_anim.stop()
        self.show()
        _force_topmost(self)
        if was_hidden:
            self.setWindowOpacity(0.0)
            self.fade_anim.setDuration(340)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.fade_anim.setStartValue(0.0)
            self.fade_anim.setEndValue(1.0)
            self.fade_anim.start()
        else:
            if self.windowOpacity() < 0.99:
                self.fade_anim.setDuration(240)
                self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.fade_anim.setStartValue(self.windowOpacity())
                self.fade_anim.setEndValue(1.0)
                self.fade_anim.start()
            else:
                self.setWindowOpacity(1.0)

    def update_realtime_text(self, text: str):
        if not text or self.current_state != "listening" or self.is_expanded_hud:
            return
        self.text_label.setText(text[-160:])

    def show_processing(self):
        if self.is_expanded_hud:
            return
        self.current_state = "processing"
        self.indicator.set_state("processing")
        self.text_label.setText("Writing")
        self.visualizer.reset()
        self.visualizer.setVisible(False)
        self.update()

    def show_download(self, percent: int, model: str):
        """Capsule and HUD progress fills while a model downloads."""
        if percent >= 100:
            self._dl = -1
            if hasattr(self, "hud_download_bar"):
                self.hud_download_bar.setValue(100)
                self.hud_download_text.setText("Model ready · CUDA active")
                QTimer.singleShot(2500, lambda: (self.hud_download_sep.hide(), self.hud_download_row.hide()))
            self.show_message("Model ready")
            return

        self._dl = percent

        # Update HUD download row
        if hasattr(self, "hud_download_row"):
            self.hud_download_sep.show()
            self.hud_download_row.show()
            self.hud_download_bar.setValue(percent)
            self.hud_download_text.setText(f"{model} · {percent}%")

        # Update Capsule
        was_hidden = not self.isVisible() or self.windowOpacity() < 0.1
        if self._mode == "line" or self._line_t > 0.05:
            self.expand_from_line()
        self.current_state = "processing"
        self.indicator.set_state("processing")
        self.text_label.setText(f"Downloading {model} model  {percent}%")
        self.visualizer.setVisible(False)
        self.hide_timer.stop()
        self.fade_anim.stop()
        if not self.is_expanded_hud:
            self.show()
            _force_topmost(self)
            if was_hidden:
                self.setWindowOpacity(0.0)
                self.fade_anim.setDuration(340)
                self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.fade_anim.setStartValue(0.0)
                self.fade_anim.setEndValue(1.0)
                self.fade_anim.start()
            else:
                self.setWindowOpacity(1.0)
        self.update()

    def show_message(self, text: str, duration_ms: int = 2200):
        """Brief notice (errors, empty result, ready notification), then minimize to line."""
        was_hidden = not self.isVisible() or self.windowOpacity() < 0.1
        if self._mode == "line" or self._line_t > 0.05:
            self.expand_from_line()
        self.current_state = "idle"
        self.indicator.set_state("idle")
        self.text_label.setText(text)
        self.visualizer.setVisible(False)
        self.update()
        if not self.is_expanded_hud:
            self.fade_anim.stop()
            self.show()
            _force_topmost(self)
            if was_hidden:
                self.setWindowOpacity(0.0)
                self.fade_anim.setDuration(340)
                self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
                self.fade_anim.setStartValue(0.0)
                self.fade_anim.setEndValue(1.0)
                self.fade_anim.start()
            else:
                self.setWindowOpacity(1.0)
            self.hide_timer.stop()
            self.hide_timer.start(duration_ms)

    def show_pasted(self, word_count: int, latency_ms: int = 0):
        if self.is_expanded_hud:
            return
        self.current_state = "pasted"
        self.indicator.set_state("done")
        self.text_label.setText(f"Pasted {word_count} words")
        self.visualizer.setVisible(False)
        self.update()
        self.hide_timer.stop()
        self.hide_timer.start(1800)

    def show_mic_event(self, mic_name: str, status: str = "connected"):
        """Displays pseudo-capsule notification pill above main capsule on mic connect/disconnect."""
        if hasattr(self, "mic_pill"):
            self.mic_pill.show_event(mic_name, status, self.geometry())

    def _fade_out_and_hide(self):
        if self.is_expanded_hud:
            return
        if self.hide_when_idle:
            self.fade_anim.stop()
            self.fade_anim.setDuration(420)
            self.fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self.fade_anim.setStartValue(self.windowOpacity())
            self.fade_anim.setEndValue(0.0)
            self.fade_anim.start()
            return
        self.minimize_to_line()

    def _on_fade_finished(self):
        if self.windowOpacity() > 0.01:
            return
        if self.hide_when_idle:
            self.hide()
            self._mode = "capsule"
            self._line_t = 0.0
            self._apply_line_t(0.0)
            self.position_bottom_center()
            return
        self.minimize_to_line()

    # ---------- painting / dragging / hovering ----------

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # 1. Transition between minimal line and capsule (and idle line state)
        if self._line_t > 0.0:
            lt = self._line_t
            r = min(rect.height() / 2.0, 22.0 - (22.0 - 3.5) * lt)
            line_fill_target = 220 if self._is_line_hovered else 140
            line_pen_target = 185 if self._is_line_hovered else 80

            if lt < 0.45:
                # Early stage: deep glass background with soft edge
                p.setBrush(QBrush(QColor(0, 0, 0, int(242 * (1.0 - lt * 0.3)))))
                p.setPen(QPen(QColor(255, 255, 255, int(40 + 30 * (1.0 - lt))), 1.0))
            else:
                # Late stage: smooth organic crossfade to luminous minimal line
                prog = (lt - 0.45) / 0.55  # 0.0 -> 1.0
                prog_e = prog * prog * (3.0 - 2.0 * prog)  # smoothstep ease
                rgb = int(255 * prog_e)
                alpha = int(242 * (1.0 - prog_e) + line_fill_target * prog_e)
                pen_a = int(60 * (1.0 - prog_e) + line_pen_target * prog_e)
                p.setBrush(QBrush(QColor(rgb, rgb, rgb, alpha)))
                p.setPen(QPen(QColor(255, 255, 255, pen_a), 1.0))

            p.drawRoundedRect(rect, r, r)
            return

        # 3. Active Capsule / HUD Sheet Mode
        r = min(rect.height() / 2.0, 22.0 + 6.0 * self._t)

        if self.current_state in ("listening", "pasted") and self._t < 0.05:
            border = QColor(255, 255, 255, 120)
        elif self.current_state == "processing" and self._t < 0.05:
            border = QColor(255, 255, 255, 70)
        else:
            border = QColor(255, 255, 255, 36)

        p.setBrush(QBrush(QColor(0, 0, 0, 242)))
        p.setPen(QPen(border, 1.0))
        p.drawRoundedRect(rect, r, r)

        if self._t > 0.4:  # sheet grabber
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, int(70 * min(1.0, (self._t - 0.4) / 0.4))))
            p.drawRoundedRect(QRectF(self.width() / 2.0 - 18, 7, 36, 4), 2, 2)

        if self._dl >= 0 and self._t < 0.05:  # download progress fill, clipped to the capsule
            clip = QPainterPath()
            clip.addRoundedRect(rect, r, r)
            p.setClipPath(clip)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(85, 255, 153, 50))
            p.drawRect(QRectF(rect.x(), rect.y(), rect.width() * self._dl / 100.0, rect.height()))

    def enterEvent(self, event):
        self.force_topmost()
        if self._mode == "line" or self._line_t > 0.8:
            self._is_line_hovered = True
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._apply_line_t(self._line_t)
        super().enterEvent(event)

    def leaveEvent(self, a0):
        if self._mode == "line" or self._line_t > 0.8:
            self._is_line_hovered = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._apply_line_t(self._line_t)
        super().leaveEvent(a0)

    def mousePressEvent(self, a0):
        if self._mode == "line" or self._line_t > 0.8:
            self.expand_from_line()
            a0.accept()
            return
        if a0.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = a0.globalPosition().toPoint() - self.frameGeometry().topLeft()
            a0.accept()

    def mouseMoveEvent(self, a0):
        if self._mode != "line" and a0.buttons() == Qt.MouseButton.LeftButton:
            self.move(a0.globalPosition().toPoint() - self._drag_pos)
            a0.accept()
