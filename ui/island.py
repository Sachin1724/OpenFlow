"""Dynamic Island style capsule: one black shape that sits flush to the top (or bottom) screen edge,
rests as a tiny pill, tucks up out of the way when idle, and springs open for dictation, alerts and settings.
Exposes the same signals and methods as FloatingPill, so the app drives either one."""
import math
import time

from PyQt6.QtCore import QObject, Qt, QTimer, QRectF, QRect, QPointF, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QFontMetrics, QPen, QRegion, QCursor, QGuiApplication
from PyQt6.QtWidgets import QWidget, QApplication, QMenu

try:
    from .floating_pill import FloatingPill, ValueRow, WaveformBars, ui_font_family, _force_topmost
    from ..engine import model_manager
    from ..engine.audio_recorder import list_microphones
except ImportError:
    try:
        from openflow.ui.floating_pill import FloatingPill, ValueRow, WaveformBars, ui_font_family, _force_topmost
        from openflow.engine import model_manager
        from openflow.engine.audio_recorder import list_microphones
    except ImportError:
        from ui.floating_pill import FloatingPill, ValueRow, WaveformBars, ui_font_family, _force_topmost
        from engine import model_manager
        from engine.audio_recorder import list_microphones

W, H = 380, 300            # the window is fixed; the shape inside it grows and shrinks
PEEK = 5                   # px of the island left showing when it has tucked up
SNOOZE_AFTER_MS = 3500
INK, DIM = QColor("#ffffff"), QColor("#9a9fa9")
REC, OK, WARN, INFO = QColor("#ff453a"), QColor("#30d158"), QColor("#ff9f0a"), QColor("#0a84ff")
DIMS = {"idle": (92, 26, 14), "listen": (236, 40, 20), "write": (188, 40, 20), "done": (160, 40, 20),
        "note": (344, 62, 26), "msg": (260, 44, 22), "panel": (356, 284, 30)}
LANG_SHORT = {"auto": "AUTO", "en-in": "EN-IN", "or-mix": "OR+EN", "or-en": "OR→EN", "translate": "→EN"}


class IslandPill(QWidget):
    sig_mic_changed = pyqtSignal(object)
    sig_language_changed = pyqtSignal(str)
    sig_tone_changed = pyqtSignal(str)
    sig_model_changed = pyqtSignal(str)
    sig_open_dashboard = pyqtSignal()
    sig_update_requested = pyqtSignal()
    sig_hide_idle_changed = pyqtSignal(bool)

    def __init__(self, current_mic_name="Microphone", current_language="en", current_model="base",
                 hide_when_idle=False, follow_mouse_screen=True, position="top"):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.resize(W, H)

        self.font_family = ui_font_family()
        self.current_mic_name, self.current_language, self.current_model = current_mic_name, current_language, current_model
        self.hide_when_idle, self.follow_mouse_screen, self.position = hide_when_idle, follow_mouse_screen, position
        self.opacity = 1.0
        self._recent_mics = []
        self._state = "idle"
        self._face = self._prev_face = "idle"
        self._face_t = 1.0
        self._dims = (92.0, 26.0, 14.0)
        self._from = self._dims
        self._snooze = 0.0
        self._note = None           # (title, sub, icon, ms, click, key)
        self._queue = []
        self._dl = -1
        self._panel_idle = 0
        self._screen = None

        self._shape_anim = QVariantAnimation(self)
        self._shape_anim.setDuration(550)
        curve = QEasingCurve(QEasingCurve.Type.OutBack)
        curve.setOvershoot(1.25)
        self._shape_anim.setEasingCurve(curve)
        self._shape_anim.setStartValue(0.0)
        self._shape_anim.setEndValue(1.0)
        self._shape_anim.valueChanged.connect(self._on_shape)
        self._shape_anim.finished.connect(self._on_shape_done)

        self._face_anim = QVariantAnimation(self)
        self._face_anim.setDuration(300)
        self._face_anim.setStartValue(0.0)
        self._face_anim.setEndValue(1.0)
        self._face_anim.valueChanged.connect(lambda v: (setattr(self, "_face_t", float(v)), self.update()))

        self._snooze_anim = QVariantAnimation(self)
        self._snooze_anim.setDuration(420)
        self._snooze_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._snooze_anim.valueChanged.connect(self._on_snooze)
        self._snooze_anim.finished.connect(self._on_snooze_done)

        self._rest_timer = QTimer(self, singleShot=True)
        self._rest_timer.timeout.connect(lambda: self._set_snooze(1.0))
        self._note_timer = QTimer(self, singleShot=True)
        self._note_timer.timeout.connect(self._finish_note)
        self._done_timer = QTimer(self, singleShot=True)
        self._done_timer.timeout.connect(self._to_idle)
        self._frame = QTimer(self)                  # runs only while something is moving
        self._frame.setInterval(16)
        self._frame.timeout.connect(self._tick)
        self._watch = QTimer(self)                  # keeps the island above other topmost windows; closes an idle panel
        self._watch.timeout.connect(self._keep_up)
        self._watch.start(1000)

        QFontMetrics(self._font(11)).horizontalAdvance("EN")  # Qt loads its font database on first use (~2 s): do it now, not mid-animation
        self.wave = WaveformBars(self)
        self.wave.hide()
        self._build_panel()
        self._place()

    # -- settings panel -----------------------------------------------------

    def _build_panel(self):
        self.lang_row = ValueRow("Language", self.font_family, self)
        for code, label in FloatingPill.LANGS:
            self.lang_row.addItem(label, code)
            if code == self.current_language:
                self.lang_row.setCurrentIndex(self.lang_row.count() - 1)
        self.model_row = ValueRow("Model", self.font_family, self)
        self.mic_row = ValueRow("Microphone", self.font_family, self)
        self.tone_row = ValueRow("Style", self.font_family, self)
        for key, label in FloatingPill.TONES:
            self.tone_row.addItem(label, key)
        self._rows = [self.lang_row, self.model_row, self.mic_row, self.tone_row]
        self.lang_row.currentIndexChanged.connect(lambda i: self._pick(self.lang_row, self.sig_language_changed, i, True))
        self.tone_row.currentIndexChanged.connect(lambda i: self._pick(self.tone_row, self.sig_tone_changed, i))
        self.model_row.currentIndexChanged.connect(lambda i: self._pick(self.model_row, self.sig_model_changed, i))
        self.mic_row.currentIndexChanged.connect(self._mic_picked)
        for r in self._rows:
            r.hide()
        self._dash_hit = QRect()

    def _pick(self, row, sig, i, is_lang=False):
        data = row.itemData(i)
        if not data:
            return
        if is_lang:
            self.current_language = data
        elif row is self.model_row:
            self.current_model = data
        sig.emit(data)

    def _mic_picked(self, i):
        self.current_mic_name = self.mic_row.currentText().removeprefix("● ").removesuffix(" (Active)").strip()
        self.sig_mic_changed.emit(self.mic_row.itemData(i))

    def populate_mics(self, recent_mics=None):
        if recent_mics is not None:
            self._recent_mics = list(recent_mics)
        r = self.mic_row
        r.blockSignals(True)
        keep = r.currentData()
        r.clear()
        r.addItem("System Default", None)
        for dev in list_microphones():
            active = dev["name"] == self.current_mic_name
            recent = dev["name"] in self._recent_mics and not active
            r.addItem(f"● {dev['name']} (Active)" if active else (f"↺ {dev['name']} (Recent)" if recent else dev["name"]), dev["index"])
            if active or (keep is not None and keep == dev["index"]):
                r.setCurrentIndex(r.count() - 1)
        r.blockSignals(False)

    def populate_models(self, active_model=None):
        if active_model is not None:
            self.current_model = active_model
        r = self.model_row
        r.blockSignals(True)
        r.clear()
        models = [("base", "Base · Balanced", "141 MB"), ("tiny", "Tiny · Fastest", "75 MB"),
                  ("small", "Small · Accurate", "464 MB"), ("medium", "Medium · Best", "1.46 GB")]
        active_id = self.current_model.replace(".en", "").lower()
        sel = 0
        for i, (mid, label, size) in enumerate(models):
            active = mid == active_id or active_id.startswith(mid)
            ready = model_manager.is_ready(mid)
            r.addItem(label if ready or active else f"{label}   ↓ {size}", mid)  # picking never downloads
            r.setItemEnabled(i, ready or active)
            if active:
                sel = i
        r.setCurrentIndex(sel)
        r.blockSignals(False)

    def update_connected_mic(self, mic_name):
        self.current_mic_name = mic_name.removeprefix("● ").strip()

    def update_language(self, code):
        self.current_language = code
        self.update()

    # -- geometry -----------------------------------------------------------

    def _target_screen(self):
        if self.follow_mouse_screen:
            return QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        return self._screen or QGuiApplication.primaryScreen()

    def _place(self):
        scr = self._target_screen()
        self._screen = scr
        g = scr.geometry()
        y = g.top() if self.position == "top" else g.bottom() + 1 - H
        self.move(g.center().x() - W // 2, y)

    def set_position(self, position):
        self.position = "bottom" if position == "bottom" else "top"
        self._place()
        self._apply_mask()
        self.update()

    def _shape_rect(self, dims=None, snooze=None):
        w, h, _ = dims or self._dims
        x = (W - w) / 2
        shift = (self._snooze if snooze is None else snooze) * (h - PEEK)
        y = -shift if self.position == "top" else H - h + shift
        return QRectF(x, y, w, h)

    def _apply_mask(self, also=None):
        """Clicks pass through everything outside the shape. Set once per move (never per frame: changing the
        mask inside an animation tick stalls Qt's animation timer on Windows), covering where the shape is going."""
        r = self._shape_rect().toAlignedRect()
        if also is not None:
            r = r.united(also.toAlignedRect())
        self.setMask(QRegion(r.intersected(QRect(0, 0, W, H))))

    # -- state machine ------------------------------------------------------

    def _go(self, state, dims=None):
        """Move the shape to a state's size with the spring, and cross-fade its contents."""
        self._rest_timer.stop()
        self._snooze_anim.stop()
        self._snooze = 0.0
        self._state = state
        target = dims or DIMS[state]
        self._from = self._dims
        self._to = tuple(float(v) for v in target)
        self._prev_face, self._face = self._face, ("msg" if state == "msg" else state)
        self._face_anim.stop()
        self._face_t = 0.0
        self._face_anim.start()
        self._shape_anim.stop()
        self._shape_anim.start()
        self._apply_mask(self._shape_rect(self._to, 0.0))
        self._ensure_visible(state == "idle")
        self._frame.start()
        for r in self._rows:
            r.hide()

    def _ensure_visible(self, may_change_screen):
        if not self.isVisible() or may_change_screen:
            self._place()
            self.show()
        self.setWindowOpacity(self.opacity)
        _force_topmost(self)

    def _on_shape(self, t):
        t = float(t)
        self._dims = tuple(a + (b - a) * t for a, b in zip(self._from, self._to))
        self.update()

    def _on_shape_done(self):
        self._dims = self._to
        self._apply_mask()
        if self._state == "panel":
            self._show_rows()
        if self._state not in ("listen", "write") and self._snooze_anim.state() != QVariantAnimation.State.Running:
            self._frame.stop()  # nothing is moving: stop repainting
        self.update()

    def _show_rows(self):
        top = self._shape_rect().top()
        x = int(self._shape_rect().left()) + 8
        for i, r in enumerate(self._rows):
            r.setGeometry(x, int(top) + 44 + i * 44, 340, 44)
            r.show()
        self._dash_hit = QRect(x, int(top) + 44 + 4 * 44 + 4, 340, 40)

    def _to_idle(self):
        self._note = None
        if self._queue:
            self._start_note(*self._queue.pop(0))
            return
        self._go("idle")
        self._frame.start()
        if self.hide_when_idle:
            self._rest_timer.start(1200)
        else:
            self._rest_timer.start(SNOOZE_AFTER_MS)

    def _set_snooze(self, to):
        if self._state != "idle" and to > 0:
            return
        self._snooze_anim.stop()
        self._apply_mask(self._shape_rect(snooze=to))
        self._snooze_anim.setStartValue(self._snooze)
        self._snooze_anim.setEndValue(to)
        self._snooze_anim.start()
        self._frame.start()

    def _on_snooze(self, v):
        self._snooze = float(v)
        self.update()

    def _on_snooze_done(self):
        self._apply_mask()
        if self._snooze >= 0.99 and self.hide_when_idle:
            self.hide()  # fully out of sight until the next event
        self._frame.stop()

    def _tick(self):
        self.update()

    def _keep_up(self):
        if not self.isVisible():
            return
        if any(isinstance(w, QMenu) and w.isVisible() for w in QApplication.topLevelWidgets()):
            self._panel_idle = 0
            return
        _force_topmost(self)
        if self._state == "panel":
            self._panel_idle = 0 if self.underMouse() else self._panel_idle + 1
            if self._panel_idle >= 8:
                self._close_panel()

    def _close_panel(self):
        self._panel_idle = 0
        self._to_idle()

    # -- notes --------------------------------------------------------------

    def _push(self, title, sub, icon, ms, click=None, key=None):
        item = (title, sub, icon, ms, click, key)
        if self._state in ("listen", "write", "panel") or (self._state in ("note", "msg") and key != (self._note or (0,) * 6)[5]):
            if key is not None:
                self._queue = [q for q in self._queue if q[5] != key]
            self._queue.append(item)
            return
        self._start_note(*item)

    def _start_note(self, title, sub, icon, ms, click, key):
        same = self._state in ("note", "msg") and self._note and self._note[5] == key and key is not None
        self._note = (title, sub, icon, ms, click, key)
        self._note_timer.stop()
        if ms:
            self._note_timer.start(ms)
        if same:
            self.update()
            return
        if sub:
            self._go("note")
        else:
            width = QFont(self.font_family)
            width.setPixelSize(14)
            tw = QFontMetrics(width).horizontalAdvance(title)
            self._go("msg", (max(200, min(W - 24, tw + 78)), 44, 22))

    def _finish_note(self):
        self._to_idle()

    def show_message(self, text, duration_ms=2200):
        low = text.lower()
        icon = "warn" if any(k in low for k in ("error", "fail", "couldn", "stopped", "too long", "unavailable", "wrong")) else "info"
        self._push(text, "", icon, duration_ms)

    def show_mic_event(self, mic_name, status="connected"):
        gone = status != "connected"
        self._push("Microphone removed" if gone else "Microphone connected", mic_name.removeprefix("● ").strip(),
                   "warn" if gone else "mic", 3200)

    def show_update_available(self, version=""):
        def click():
            self.sig_update_requested.emit()
            self._push("Downloading update…", "OpenFlow restarts when it finishes", "down", 4000, key="update")
        self._push(f"OpenFlow {version} is available" if version else "Update available", "Click to download and restart",
                   "down", 8000, click, "update")

    def show_download(self, percent, model):
        if percent >= 100:
            self._dl = -1
            self._push("Model ready", f"{model} is loaded", "ok", 2400, key="dl")
            return
        self._dl = max(0, percent)
        self._push("Downloading model", f"{model} · {percent}%", "down", 0, key="dl")

    # -- dictation ----------------------------------------------------------

    def _preempt(self):
        self._note_timer.stop()
        self._done_timer.stop()
        if self._note and not self._note[3]:  # a download without a timeout resumes afterwards
            self._queue.insert(0, self._note)
        self._note = None

    def show_listening(self, preset_name="Listening"):
        if self._state == "listen":
            return
        self._preempt()
        self._go("listen")

    def show_processing(self):
        if self._state == "write":
            return
        self._preempt()
        self._go("write")

    def show_pasted(self, word_count=0, latency_ms=0):
        self._preempt()
        self._go("done")
        self._done_timer.start(1400)

    def set_amplitude(self, level):
        self.wave.set_level(level)

    def update_realtime_text(self, text):
        pass  # the island has no room for a live caption

    def expand_to_hud(self):
        self._open_panel()

    def _open_panel(self):
        if self._state == "panel":
            return
        self._preempt()
        self._panel_idle = 0
        self._go("panel")

    # -- settings from the app ---------------------------------------------

    def set_opacity(self, value):
        self.opacity = max(0.3, min(1.0, value))
        if self.isVisible():
            self.setWindowOpacity(self.opacity)

    def set_hide_when_idle(self, hide):
        self.hide_when_idle = hide
        if self._state == "idle":
            self._to_idle()

    def set_follow_mouse_screen(self, follow):
        self.follow_mouse_screen = follow

    def activate(self):
        """Show the island at rest (used when the app switches to this style)."""
        self._dims = DIMS["idle"]
        self._go("idle")
        self._to_idle()

    # -- input --------------------------------------------------------------

    def enterEvent(self, event):
        if self._state == "idle" and self._snooze > 0.05:
            self._rest_timer.stop()
            self._set_snooze(0.0)
            self._rest_timer.start(SNOOZE_AFTER_MS)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        if self._state == "panel":
            r = self._shape_rect()
            if QRectF(r.right() - 90, r.top() + 6, 84, 30).contains(e.position()):
                self._close_panel()
            elif self._dash_hit.contains(pos):
                self._close_panel()
                self.sig_open_dashboard.emit()
        elif self._state in ("note", "msg") and self._note and self._note[4]:
            self._note[4]()
        elif self._state == "idle":
            self._set_snooze(0.0)
            self._open_panel()

    # -- painting -----------------------------------------------------------

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = self._shape_rect()
        rad = self._dims[2]
        path = QPainterPath()
        if self.position == "top":
            path.addRoundedRect(QRectF(r.x(), r.y() - rad, r.width(), r.height() + rad), rad, rad)
        else:
            path.addRoundedRect(QRectF(r.x(), r.y(), r.width(), r.height() + rad), rad, rad)
        p.fillPath(path, QColor("#000000"))
        p.setClipPath(path)
        t = self._face_t
        fade_out = max(0.0, 1.0 - t / 0.3)
        fade_in = max(0.0, (t - 0.35) / 0.65)
        if fade_out > 0 and self._prev_face != self._face:
            self._draw_face(p, self._prev_face, r, fade_out)
        self._draw_face(p, self._face, r, fade_in if self._prev_face != self._face else 1.0)
        self.wave.setVisible(self._state == "listen" and fade_in > 0.4)
        if self.wave.isVisible():
            self.wave.move(int(r.center().x() - 24), int(r.center().y() - 11))

    def _font(self, px, weight=QFont.Weight.Medium):
        f = QFont(self.font_family)
        f.setPixelSize(px)
        f.setWeight(weight)
        return f

    def _draw_face(self, p, face, r, a):
        if a <= 0:
            return
        p.save()
        p.setOpacity(a)
        cy = r.center().y()
        top = self.position == "top"
        if face == "idle":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a3d44"))
            p.drawEllipse(r.center(), 3, 3)
        elif face == "listen":
            pulse = 0.65 + 0.35 * abs(math.sin(time.monotonic() * 2.4))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(REC)
            d = 10 * pulse
            p.drawEllipse(QRectF(r.left() + 16 + (10 - d) / 2, cy - d / 2, d, d))
            self._badge(p, r, cy)
        elif face == "write":
            self._spinner(p, r.center().x() - 38, cy)
            p.setPen(INK)
            p.setFont(self._font(14))
            p.drawText(QRectF(r.center().x() - 16, r.top(), 80, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Writing")
        elif face == "done":
            self._icon(p, "ok", QRectF(r.center().x() - 42, cy - 9, 18, 18), round_=True)
            p.setPen(INK)
            p.setFont(self._font(14))
            p.drawText(QRectF(r.center().x() - 16, r.top(), 80, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Pasted")
        elif face in ("note", "msg") and self._note:
            title, sub, icon, _, _, _ = self._note
            ic = QRectF(r.left() + 18, cy - 16, 32, 32) if face == "note" else QRectF(r.left() + 14, cy - 12, 24, 24)
            self._icon(p, icon, ic)
            tx = ic.right() + 12
            p.setPen(INK)
            if face == "note":
                p.setFont(self._font(14, QFont.Weight.DemiBold))
                p.drawText(QRectF(tx, cy - 20, r.right() - tx - 14, 20), Qt.AlignmentFlag.AlignBottom, title)
                p.setPen(DIM)
                p.setFont(self._font(12))
                p.drawText(QRectF(tx, cy, r.right() - tx - 14, 20), Qt.AlignmentFlag.AlignTop, sub)
                if self._dl >= 0 and self._note[5] == "dl":
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor("#2a2c31"))
                    bar = QRectF(tx, r.bottom() - 9, r.right() - tx - 18, 3)
                    p.drawRoundedRect(bar, 1.5, 1.5)
                    p.setBrush(INFO)
                    p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * self._dl / 100, 3), 1.5, 1.5)
            else:
                p.setFont(self._font(14))
                room = int(r.right() - tx - 14)
                p.drawText(QRectF(tx, r.top(), room, r.height()), Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, room))
        elif face == "panel":
            p.setPen(DIM)
            hf = self._font(11, QFont.Weight.DemiBold)
            hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
            p.setFont(hf)
            p.drawText(QRectF(r.left() + 20, r.top() + 10, 200, 26), Qt.AlignmentFlag.AlignVCenter, "OPENFLOW")
            p.setPen(INFO)
            p.setFont(self._font(13))
            p.drawText(QRectF(r.right() - 90, r.top() + 10, 70, 26), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "Done")
            p.setPen(INK)
            p.setFont(self._font(14))
            y = r.top() + 44 + 4 * 44 + 4
            p.drawText(QRectF(r.left() + 24, y, 200, 40), Qt.AlignmentFlag.AlignVCenter, "Open dashboard")
            p.setPen(DIM)
            p.drawText(QRectF(r.right() - 50, y, 30, 40), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, "›")
        p.restore()

    def _badge(self, p, r, cy):
        code = self.current_language
        text = LANG_SHORT.get(code, code.split("-")[0].upper())
        p.setFont(self._font(11, QFont.Weight.DemiBold))
        w = p.fontMetrics().horizontalAdvance(text) + 18
        box = QRectF(r.right() - 16 - w, cy - 10, w, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#1c1d21"))
        p.drawRoundedRect(box, 10, 10)
        p.setPen(DIM)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _spinner(self, p, cx, cy):
        rect = QRectF(cx - 7.5, cy - 7.5, 15, 15)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor("#3a3d44"), 2))
        p.drawEllipse(rect)
        pen = QPen(INK, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, int(-(time.monotonic() * 360 * 1.4) % 360 * 16), 90 * 16)

    def _icon(self, p, kind, box, round_=False):
        color = {"mic": INFO, "down": INFO, "info": INFO, "ok": OK, "warn": WARN}[kind]
        if kind == "ok" and round_:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(OK)
            p.drawEllipse(box)
            pen = QPen(QColor("#000000"), 2)
        else:
            tint = QColor(color)
            tint.setAlpha(60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tint)
            p.drawRoundedRect(box, box.width() * 0.31, box.width() * 0.31)
            pen = QPen(color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        c, s = box.center(), box.width()
        u = s / 24.0
        if kind == "ok":
            path = QPainterPath()
            path.moveTo(c.x() - 4 * u, c.y() + 0.5 * u)
            path.lineTo(c.x() - 1 * u, c.y() + 3.5 * u)
            path.lineTo(c.x() + 4.5 * u, c.y() - 3 * u)
            p.drawPath(path)
        elif kind == "mic":
            p.drawRoundedRect(QRectF(c.x() - 3 * u, c.y() - 8 * u, 6 * u, 10 * u), 3 * u, 3 * u)
            p.drawArc(QRectF(c.x() - 6 * u, c.y() - 6 * u, 12 * u, 12 * u), 180 * 16, 180 * 16)
            p.drawLine(QPointF(c.x(), c.y() + 6 * u), QPointF(c.x(), c.y() + 9 * u))
        elif kind == "down":
            p.drawLine(QPointF(c.x(), c.y() + -6 * u), QPointF(c.x(), c.y() + 4 * u))
            path = QPainterPath()
            path.moveTo(c.x() - 4 * u, c.y() + 0.5 * u)
            path.lineTo(c.x(), c.y() + 4.5 * u)
            path.lineTo(c.x() + 4 * u, c.y() + 0.5 * u)
            p.drawPath(path)
        elif kind == "warn":
            path = QPainterPath()
            path.moveTo(c.x(), c.y() - 7 * u)
            path.lineTo(c.x() + 7.5 * u, c.y() + 6 * u)
            path.lineTo(c.x() - 7.5 * u, c.y() + 6 * u)
            path.closeSubpath()
            p.drawPath(path)
            p.drawLine(QPointF(c.x(), c.y() + -2 * u), QPointF(c.x(), c.y() + 1.5 * u))
        else:  # info
            p.drawEllipse(c, 7 * u, 7 * u)
            p.drawLine(QPointF(c.x(), c.y() + -1 * u), QPointF(c.x(), c.y() + 3 * u))


class CapsuleRouter(QObject):
    """Holds the classic capsule and the island and sends every call to whichever the user chose, so the
    style can be switched live from Settings. Calls that keep both in step (lists, opacity) go to both."""
    sig_mic_changed = pyqtSignal(object)
    sig_language_changed = pyqtSignal(str)
    sig_tone_changed = pyqtSignal(str)
    sig_model_changed = pyqtSignal(str)
    sig_open_dashboard = pyqtSignal()
    sig_update_requested = pyqtSignal()
    sig_hide_idle_changed = pyqtSignal(bool)
    _BOTH = ("populate_mics", "populate_models", "update_connected_mic", "update_language", "set_opacity", "set_hide_when_idle")

    def __init__(self, pill, island, style="compact", follow=True):
        super().__init__()
        self._pill, self._island, self._on_island, self._follow = pill, island, False, follow
        for sig in ("sig_mic_changed", "sig_language_changed", "sig_tone_changed", "sig_model_changed",
                    "sig_open_dashboard", "sig_update_requested", "sig_hide_idle_changed"):
            getattr(pill, sig).connect(getattr(self, sig))
            getattr(island, sig).connect(getattr(self, sig))
        for name in self._BOTH:
            setattr(self, name, self._both(name))
        if style == "island":
            self.set_capsule_style("island")

    def _both(self, name):
        def call(*a, **k):
            getattr(self._pill, name)(*a, **k)
            getattr(self._island, name)(*a, **k)
        return call

    def set_capsule_style(self, style):
        if style == "island":
            if not self._on_island:
                self._on_island = True
                self._pill.set_follow_mouse_screen(False)  # keep the hidden capsule from reappearing on a screen change
                self._pill.hide()
            self._island.activate()
            return
        if self._on_island:
            self._on_island = False
            self._island.hide()
            self._pill.set_follow_mouse_screen(self._follow)
            self._pill.set_capsule_style(style)
            self._pill.show_message("OpenFlow capsule", duration_ms=1500)
        else:
            self._pill.set_capsule_style(style)

    def set_follow_mouse_screen(self, follow):
        self._follow = follow
        self._island.set_follow_mouse_screen(follow)
        self._pill.set_follow_mouse_screen(follow and not self._on_island)

    def set_island_position(self, position):
        self._island.set_position(position)

    def geometry(self):
        return QRect() if self._on_island else self._pill.geometry()  # the meeting bar then uses its default spot

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._island if self._on_island else self._pill, name)
