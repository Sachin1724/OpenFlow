import math
import glob
import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QProgressBar, QFrame, QApplication, QMenu, QSizePolicy
)
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QRectF, QPropertyAnimation, QVariantAnimation,
    QEasingCurve, pyqtSignal
)
from PyQt6.QtGui import (
    QPainter, QColor, QBrush, QPen, QFont, QFontDatabase, QFontMetricsF, QLinearGradient, QPainterPath, QPolygonF
)


from ..engine.audio_recorder import list_microphones

# Black & white palette
FG = "#ffffff"
FG_DIM = "rgba(255, 255, 255, 0.55)"
FG_FAINT = "rgba(255, 255, 255, 0.32)"
HAIRLINE = "rgba(255, 255, 255, 0.10)"
FILL = "rgba(255, 255, 255, 0.07)"


def ui_font_family() -> str:
    """General Sans if installed, else Inter, else system UI font. Loads user-installed files."""
    for pat in ("*GeneralSans*", "*General Sans*", "Inter-*", "Inter_18pt-Regular*", "Inter_18pt-Medium*"):
        for d in (os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Windows\Fonts"), r"C:\Windows\Fonts"):
            for f in glob.glob(os.path.join(d, pat + ".[to]tf")):
                QFontDatabase.addApplicationFont(f)
    available = set(QFontDatabase.families())
    for name in ("General Sans", "Inter", "SF Pro Text", "Segoe UI Variable Text", "Segoe UI"):
        if name in available:
            return name
    return QFont().family()


class StateIndicator(QWidget):
    """Monochrome vector indicator: pulsing dot, spinner arc, or checkmark."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.state = "idle"
        self.phase = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    def set_state(self, state: str):
        self.state = state
        self.update()

    def _tick(self):
        if self.state in ("listening", "processing"):
            self.phase += 0.09
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
            p.setPen(QPen(QColor(255, 255, 255), 2.0, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            path = QPainterPath()
            path.moveTo(c.x() - 5, c.y() + 0.5)
            path.lineTo(c.x() - 1.5, c.y() + 4)
            path.lineTo(c.x() + 5.5, c.y() - 4)
            p.drawPath(path)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 90))
            p.drawEllipse(c, 3, 3)


class WaveformBars(QWidget):
    """Five rounded white bars reacting to input level."""

    def __init__(self, parent=None, num_bars=5):
        super().__init__(parent)
        self.num_bars = num_bars
        self.bar_heights = [0.2] * num_bars
        self.target_level = 0.0
        self.phase = 0.0
        self.setFixedSize(40, 20)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(24)

    def set_level(self, level: float):
        self.target_level = max(0.06, min(1.0, level))

    def _tick(self):
        if not self.isVisible():
            return
        self.phase += 0.3
        for i in range(self.num_bars):
            mod = 0.35 + 0.65 * math.sin(self.phase + i * 1.25)
            self.bar_heights[i] = self.bar_heights[i] * 0.55 + self.target_level * mod * 0.45
        self.update()

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 235))

        bar_w, gap = 3.0, 4.0
        total = self.num_bars * bar_w + (self.num_bars - 1) * gap
        x0 = (self.width() - total) / 2.0
        for i, bh in enumerate(self.bar_heights):
            h = max(3.0, bh * (self.height() - 2))
            p.drawRoundedRect(QRectF(x0 + i * (bar_w + gap), (self.height() - h) / 2.0, bar_w, h),
                              bar_w / 2, bar_w / 2)


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



_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets").replace("\\", "/")


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
    Offers the small slice of the QComboBox API the panel already uses."""
    currentIndexChanged = pyqtSignal(int)

    def __init__(self, title: str, font_family: str, parent=None):
        super().__init__(parent)
        self._title = title
        self._family = font_family
        self._items = []
        self._idx = -1
        self._hover = False
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def clear(self):
        self._items, self._idx = [], -1
        self.update()

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
            self.update()
            self.currentIndexChanged.emit(i)

    def currentData(self):
        return self._items[self._idx][1] if self._idx >= 0 else None

    def currentText(self):
        return self._items[self._idx][0] if self._idx >= 0 else ""

    def enterEvent(self, event):
        self._hover = True
        self.update()

    def leaveEvent(self, a0):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, a0):
        if a0.button() != Qt.MouseButton.LeftButton or not self._items:
            return
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet(f"""
            QMenu {{ background: rgba(28,28,30,0.97); border: 1px solid rgba(255,255,255,0.12);
                     border-radius: 12px; padding: 6px; color: #fff; }}
            QMenu::item {{ padding: 7px 30px 7px 28px; border-radius: 7px; margin: 1px 0; }}
            QMenu::item:selected {{ background: rgba(255,255,255,0.14); }}
            QMenu::indicator {{ width: 14px; height: 14px; left: 8px; }}
            QMenu::indicator:checked {{ image: url({_ASSETS}/check_white.svg); }}
        """)
        menu.setFont(QFont(self._family, 10))
        for i, (text, _) in enumerate(self._items):
            act = menu.addAction(text)
            act.setCheckable(True)
            act.setChecked(i == self._idx)
            act.triggered.connect(lambda _=False, i=i: self.setCurrentIndex(i))
        menu.exec(self.mapToGlobal(QPoint(0, self.height() + 2)))

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            p.fillRect(self.rect(), QColor(255, 255, 255, 12))
        f = QFont(self._family, 10)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(14, 0, 96, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._title)
        cx, cy = self.width() - 18, self.height() / 2.0
        pen = QPen(QColor(255, 255, 255, 200 if self._hover else 120), 1.5,
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawPolyline(QPolygonF([QPointF(cx - 3, cy - 2.5), QPointF(cx, cy - 5.5), QPointF(cx + 3, cy - 2.5)]))
        p.drawPolyline(QPolygonF([QPointF(cx - 3, cy + 2.5), QPointF(cx, cy + 5.5), QPointF(cx + 3, cy + 2.5)]))

        fm = QFontMetricsF(f)
        vr = QRectF(112, 0, self.width() - 112 - 34, self.height())
        p.setPen(QColor(255, 255, 255, 210 if self._hover else 140))
        p.drawText(vr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                   fm.elidedText(self.currentText(), Qt.TextElideMode.ElideRight, vr.width()))


class FloatingPill(QWidget):
    """
    Black-and-white capsule HUD.
    Capsule (360x44) morphs into a grouped settings panel (360x312), anchored at its
    bottom-centre. One progress value drives geometry, corner radius and a content crossfade.
    """
    sig_mic_changed = pyqtSignal(object)
    sig_language_changed = pyqtSignal(str)
    sig_tone_changed = pyqtSignal(str)
    sig_open_dashboard = pyqtSignal()
    sig_update_requested = pyqtSignal()

    LANGS = [
        ("auto", "Auto Detect"), ("en", "English"), ("hi", "Hindi"), ("es", "Spanish"),
        ("fr", "French"), ("de", "German"), ("zh", "Chinese"), ("ja", "Japanese"),
        ("pt", "Portuguese"), ("it", "Italian"), ("ar", "Arabic"), ("ru", "Russian"),
        ("ko", "Korean"), ("nl", "Dutch"), ("tr", "Turkish"),
    ]
    TONES = [
        ("smart_clean", "Smart Clean"), ("developer", "Developer"), ("email", "Email"),
        ("bullets", "Bullet Points"), ("verbatim", "Verbatim"),
    ]

    def __init__(self, current_mic_name: str = "Microphone", current_language: str = "en"):
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

        self._cap_w, self._cap_h = 360, 44
        self._hud_w, self._hud_h = 360, 312
        self._t = 0.0            # 0 = capsule, 1 = HUD
        self._dl = -1            # model download percent, -1 when not downloading
        self._anchor = QPoint()  # bottom-centre of the window during a morph

        self.morph_anim = QVariantAnimation(self)
        self.morph_anim.setDuration(320)
        self.morph_anim.setEasingCurve(QEasingCurve.Type.OutExpo)
        self.morph_anim.valueChanged.connect(self._apply_t)
        self.morph_anim.finished.connect(self._on_morph_finished)

        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(200)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.fade_anim.finished.connect(self._on_fade_finished)

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._fade_out_and_hide)

        self._build_capsule()
        self._build_hud()
        self.setStyleSheet(f"QLabel {{ background: transparent; border: none; color: {FG}; }}")
        self._apply_t(0.0)
        self.position_bottom_center()

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

    def _row(self, title: str, widget: QWidget) -> QWidget:
        row = QWidget(self)
        row.setFixedHeight(44)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(14, 0, 12, 0)
        lay.setSpacing(10)
        lbl = QLabel(title, row)
        lbl.setFont(self._font(10))
        lbl.setFixedWidth(98)
        lay.addWidget(lbl)
        lay.addWidget(widget, 1)
        return row

    def _build_hud(self):
        self.hud_widget = QWidget(self)
        self.hud_widget.setFixedSize(self._hud_w, self._hud_h)
        lay = QVBoxLayout(self.hud_widget)
        lay.setContentsMargins(16, 20, 16, 16)
        lay.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("OpenFlow", self)
        title.setFont(self._font(12, QFont.Weight.Medium))
        self.btn_minimize = QPushButton("Done", self)
        self.btn_minimize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_minimize.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_minimize.setFont(self._font(10, QFont.Weight.Medium))
        self.btn_minimize.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {FG}; border: none; padding: 4px 6px; }}
            QPushButton:hover {{ color: {FG_DIM}; }}
        """)
        self.btn_minimize.clicked.connect(self.collapse_to_capsule)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.btn_minimize)
        lay.addLayout(header)

        group = QFrame(self)
        group.setObjectName("Group")
        group.setStyleSheet(f"QFrame#Group {{ background: {FILL}; border-radius: 14px; }}")
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

        self.live_level_bar = QProgressBar(self)
        self.live_level_bar.setRange(0, 100)
        self.live_level_bar.setValue(0)
        self.live_level_bar.setTextVisible(False)
        self.live_level_bar.setFixedHeight(4)
        self.live_level_bar.setStyleSheet(f"""
            QProgressBar {{ background: {HAIRLINE}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {FG}; border-radius: 2px; }}
        """)

        rows = [
            self.mic_combo,
            self.lang_combo,
            self.tone_combo,
            self._row("Input", self.live_level_bar),
        ]
        for i, r in enumerate(rows):
            g.addWidget(r)
            if i < len(rows) - 1:
                sep = QFrame(self)
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {HAIRLINE}; margin-left: 14px; margin-right: 14px;")
                g.addWidget(sep)
        lay.addWidget(group)
        lay.addStretch()

        self.btn_update = QPushButton("Update Available · Install", self)
        self.btn_update.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_update.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_update.setFixedHeight(34)
        self.btn_update.setFont(self._font(10, QFont.Weight.Medium))
        self.btn_update.setStyleSheet("""
            QPushButton { background: rgba(255, 255, 255, 0.16); color: #ffffff; border: 1px solid rgba(255,255,255,0.30); border-radius: 17px; }
            QPushButton:hover { background: rgba(255, 255, 255, 0.26); }
        """)
        self.btn_update.hide()
        self.btn_update.clicked.connect(self._on_update_clicked)
        lay.addWidget(self.btn_update)

        self.btn_transfer = QPushButton("Open Dashboard", self)
        self.btn_transfer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_transfer.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_transfer.setFixedHeight(38)
        self.btn_transfer.setFont(self._font(10, QFont.Weight.Medium))
        self.btn_transfer.setStyleSheet("""
            QPushButton { background: #ffffff; color: #000000; border: none; border-radius: 19px; }
            QPushButton:hover { background: rgba(255,255,255,0.86); }
            QPushButton:pressed { background: rgba(255,255,255,0.70); }
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
        self._morph_to(1.0)

    def collapse_to_capsule(self):
        self.is_expanded_hud = False
        self._morph_to(0.0)

    def _on_morph_finished(self):
        self._apply_t(self._t)
        self.update()

    # ---------- data ----------

    def _lang_short(self, code: str) -> str:
        return "AUTO" if code == "auto" else code.upper()

    def populate_mics(self):
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()
        self.mic_combo.addItem("System Default", None)
        for dev in list_microphones():
            self.mic_combo.addItem(dev["name"], dev["index"])
        self.mic_combo.blockSignals(False)

    def populate_languages(self):
        self.lang_combo.blockSignals(True)
        self.lang_combo.clear()
        for code, label in self.LANGS:
            self.lang_combo.addItem(label, code)
            if code == self.current_language:
                self.lang_combo.setCurrentIndex(self.lang_combo.count() - 1)
        self.lang_combo.blockSignals(False)

    def update_connected_mic(self, mic_name: str):
        self.current_mic_name = mic_name
        if self.current_state == "idle":
            self.text_label.setText(mic_name)

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
            self.setGeometry(r.x() + (r.width() - self._cap_w) // 2,
                             r.y() + r.height() - self._cap_h - 50,
                             self._cap_w, self._cap_h)

    # ---------- state ----------

    def set_amplitude(self, level: float):
        self.visualizer.set_level(level)
        if self.is_expanded_hud:
            self.live_level_bar.setValue(int(level * 100))

    def show_listening(self, preset_name: str = "Listening"):
        if self.is_expanded_hud:
            return
        self.current_state = "listening"
        self.hide_timer.stop()
        self.indicator.set_state("listening")
        self.text_label.setText(preset_name)
        self.lang_badge.setText(self._lang_short(self.current_language))
        self.visualizer.setVisible(True)
        self.update()

        self.fade_anim.stop()
        self.show()
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

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
        self.visualizer.setVisible(False)
        self.update()

    def show_download(self, percent: int, model: str):
        """Capsule fills left to right while a model downloads; works in capsule view only."""
        if percent >= 100:
            self._dl = -1
            self.show_message("Model ready")
            return
        self._dl = percent
        self.current_state = "processing"
        self.indicator.set_state("processing")
        self.text_label.setText(f"Downloading {model} model  {percent}%")
        self.visualizer.setVisible(False)
        self.hide_timer.stop()
        self.fade_anim.stop()
        self.setWindowOpacity(1.0)
        if not self.is_expanded_hud:
            self.show()
        self.update()

    def show_message(self, text: str, duration_ms: int = 2200):
        """Brief notice (errors, empty result, ready notification), then fade away."""
        self.current_state = "idle"
        self.indicator.set_state("idle")
        self.text_label.setText(text)
        self.visualizer.setVisible(False)
        self.update()
        if not self.is_expanded_hud:
            self.show()
            self.setWindowOpacity(1.0)
            self.hide_timer.start(duration_ms)


    def show_pasted(self, word_count: int, latency_ms: int = 0):
        if self.is_expanded_hud:
            return
        self.current_state = "pasted"
        self.indicator.set_state("done")
        self.text_label.setText(f"Pasted {word_count} words")
        self.visualizer.setVisible(False)
        self.update()
        self.hide_timer.start(1600)

    def _fade_out_and_hide(self):
        if self.is_expanded_hud:
            return
        self.fade_anim.stop()
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(0.0)
        self.fade_anim.start()

    def _on_fade_finished(self):
        if self.windowOpacity() > 0.01:
            return
        self.hide()
        self.current_state = "idle"
        self.indicator.set_state("idle")
        self.visualizer.setVisible(True)
        self.text_label.setText(self.current_mic_name)

    # ---------- painting / dragging ----------

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
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
            p.setBrush(QColor(255, 255, 255, 40))
            p.drawRect(QRectF(rect.x(), rect.y(), rect.width() * self._dl / 100.0, rect.height()))

    def mousePressEvent(self, a0):
        if a0.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = a0.globalPosition().toPoint() - self.frameGeometry().topLeft()
            a0.accept()

    def mouseMoveEvent(self, a0):
        if a0.buttons() == Qt.MouseButton.LeftButton:
            self.move(a0.globalPosition().toPoint() - self._drag_pos)
            a0.accept()
