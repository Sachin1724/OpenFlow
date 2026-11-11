"""Dynamic Island style capsule: one black shape that sits flush to the top (or bottom) screen edge,
rests as a tiny pill, tucks up out of the way when idle, and springs open for dictation, alerts and settings.
Exposes the same signals and methods as FloatingPill, so the app drives either one."""
import math
import time

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, QRectF, QRect, QPointF, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QFontMetrics, QPen, QRegion, QCursor, QGuiApplication
from PyQt6.QtWidgets import QWidget, QApplication, QMenu

try:
    from .floating_pill import FloatingPill, FloatingCaptionBubble, ValueRow, WaveformBars, ui_font_family, _force_topmost
    from ..engine import model_manager
    from ..engine.audio_recorder import list_microphones
except ImportError:
    try:
        from openflow.ui.floating_pill import FloatingPill, FloatingCaptionBubble, ValueRow, WaveformBars, ui_font_family, _force_topmost
        from openflow.engine import model_manager
        from openflow.engine.audio_recorder import list_microphones
    except ImportError:
        from ui.floating_pill import FloatingPill, FloatingCaptionBubble, ValueRow, WaveformBars, ui_font_family, _force_topmost
        from engine import model_manager
        from engine.audio_recorder import list_microphones
try:
    from .blobatar_widget import BlobatarWidget
except (ImportError, ValueError):
    try:
        from openflow.ui.blobatar_widget import BlobatarWidget
    except ImportError:
        from ui.blobatar_widget import BlobatarWidget

W0, H0 = 380, 300          # window size at 1x; the shape inside it grows and shrinks
PEEK = 5                   # px of the island left showing when it has tucked up
SNOOZE_AFTER_MS = 3500
INK, DIM = QColor("#ffffff"), QColor("#9a9fa9")
REC, OK, WARN, INFO = QColor("#ff453a"), QColor("#30d158"), QColor("#ff9f0a"), QColor("#0a84ff")
DIMS = {"idle": (92, 26, 14), "listen": (236, 40, 20), "write": (188, 40, 20), "done": (160, 40, 20),
        "note": (344, 62, 26), "msg": (260, 44, 22), "panel": (356, 284, 30)}
LANG_SHORT = {"auto": "AUTO", "en-in": "EN-IN", "or-mix": "OR+EN", "or-auto": "OR/EN", "or-en": "OR→EN", "translate": "→EN"}
# Motion. The shape rides a spring, so a state that arrives mid-move (listen -> write -> done in a second)
# bends the path instead of restarting from rest. Damping 1 = no overshoot for dictation, which happens
# all day; the rare panel and notices get a little give. (response in seconds, damping ratio)
SPRING = {"listen": (0.28, 1.0), "write": (0.26, 1.0), "done": (0.24, 1.0), "idle": (0.32, 1.0),
          "msg": (0.34, 0.86), "note": (0.34, 0.86), "panel": (0.36, 0.86)}
FACE_MS, FACE_OUT_MS, FACE_IN_AT_MS = 260, 120, 80   # contents swap: old face out fast, new face in after it


def _bezier(x1, y1, x2, y2):
    c = QEasingCurve(QEasingCurve.Type.BezierSpline)
    c.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1, 1))
    return c


EASE_OUT = _bezier(0.23, 1, 0.32, 1)          # things arriving
EASE_IN_OUT = _bezier(0.77, 0, 0.175, 1)      # things moving on screen (tucking up and back)


def animations_enabled():
    """Windows 'Animation effects' (Settings > Accessibility > Visual effects). Off: the shape snaps, fades stay short."""
    try:
        import ctypes
        on = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)  # SPI_GETCLIENTAREAANIMATION
        return bool(on.value)
    except (AttributeError, OSError):
        return True


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
        self.W, self.H = W0, H0
        self._wf = self._hf = 1.0     # user's width/height percent / 100
        self._auto = False            # grow with the screen: 1920 px wide = 1x, never below
        self._wk = self._hk = self._sk = 1.0   # the factors in force on the current screen
        self.resize(self.W, self.H)

        self.font_family = ui_font_family()
        self.current_mic_name, self.current_language, self.current_model = current_mic_name, current_language, current_model
        self.hide_when_idle, self.follow_mouse_screen, self.position = hide_when_idle, follow_mouse_screen, position
        self.opacity = 1.0
        self._recent_mics = []
        self._state = "idle"
        self._face = self._prev_face = "idle"
        self._face_t = 1.0
        self._dims = (92.0, 26.0, 14.0)
        self._snooze = 0.0
        self._note = None           # (title, sub, icon, ms, click, key)
        self._queue = []
        self._dl = -1
        self._panel_idle = 0
        self._screen = None
        self._enabled = False         # only an activated island ever shows; Settings can switch it off for good

        self._motion = animations_enabled()
        self._to = self._dims
        self._vel = (0.0, 0.0, 0.0)   # the spring's speed per dimension, carried into the next target
        self._spring = SPRING["idle"]
        self._moving = False
        self._last = 0.0

        self._face_anim = QVariantAnimation(self)   # linear clock; paintEvent shapes it with EASE_OUT
        self._face_anim.setDuration(FACE_MS)
        self._face_anim.setStartValue(0.0)
        self._face_anim.setEndValue(1.0)
        self._face_anim.valueChanged.connect(lambda v: (setattr(self, "_face_t", float(v)), self.update()))

        self._snooze_anim = QVariantAnimation(self)
        self._snooze_anim.setDuration(360)
        self._snooze_anim.setEasingCurve(EASE_IN_OUT)
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
        self.blobatar = BlobatarWidget(size=24, parent=self)
        self.blobatar.hide()
        self._active_dialect = None
        self.caption_bubble = FloatingCaptionBubble(self)  # live words, typed in under the island
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
        self._active_dialect = None  # a stale dialect would keep is_odia_active() true after switching to English
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
        self._refresh_scale()
        y = g.top() if self.position == "top" else g.bottom() + 1 - self.H
        self.move(g.center().x() - self.W // 2, y)

    @property
    def caption_below(self):
        return self.position == "top"

    def body_top(self):
        return int(self._shape_rect().top())

    def body_bottom(self):
        return int(self._shape_rect().bottom())

    def set_position(self, position):
        self.position = "bottom" if position == "bottom" else "top"
        self._place()
        self._apply_mask()
        self.update()

    def _refresh_scale(self):
        """Effective width/height factors on the current screen, and a window big enough to hold the widest shape."""
        k = 1.0
        if self._auto and self._screen is not None:
            k = max(1.0, min(1.5, self._screen.geometry().width() / 1920.0))
        self._wk, self._hk = self._wf * k, self._hf * k
        self._sk = min(self._wk, self._hk)  # contents scale by the smaller factor, so they always fit; the other adds room
        W = max(W0, round(344 * self._wk) + 36)
        if W != self.W:
            self.W = W
            self.resize(self.W, self.H)
            if self._screen is not None:
                self.move(self._screen.geometry().center().x() - self.W // 2, self.y())
        self.wave.setFixedSize(round(48 * self._sk), round(22 * self._sk))

    def set_capsule_size(self, wf, hf, auto):
        """Width and height as fractions of the default, plus 'grow with the screen'. Shows a short preview."""
        self._wf, self._hf, self._auto = wf, hf, auto
        self._screen = self._screen or self._target_screen()
        self._refresh_scale()
        if not (self._enabled and self.isVisible()) or self._state == "panel":
            return
        if self._state == "idle":
            self._go("listen")
            self._done_timer.start(1400)  # a short preview, then back to rest (which re-snoozes)
        else:  # every change retargets the shape, whatever is showing, so it never lags behind its contents
            self._go(self._state, self._note_dims() if self._state in ("note", "msg") and self._note else None)
            if self._state == "listen" and self._done_timer.isActive():
                self._done_timer.start(1400)

    def is_odia_active(self) -> bool:
        return self.current_language in ("or", "odia", "or-mix", "or-en", "or-auto") or bool(getattr(self, "_active_dialect", None))

    def set_detected_dialect(self, dialect: str):
        self._active_dialect = dialect
        self.update()

    def _shape_rect(self, dims=None, snooze=None):
        w, h, _ = dims or self._dims
        x = (self.W - w) / 2
        shift = (self._snooze if snooze is None else snooze) * (h - PEEK)
        y = -shift if self.position == "top" else self.H - h + shift
        return QRectF(x, y, w, h)

    def _apply_mask(self, also=None):
        """Clicks pass through everything outside the shape. Set once per move (never per frame: changing the
        mask inside an animation tick stalls Qt's animation timer on Windows), covering where the shape is going."""
        r = self._shape_rect().toAlignedRect()
        if also is not None:
            r = r.united(also.toAlignedRect())
        self.setMask(QRegion(r.intersected(QRect(0, 0, self.W, self.H))))

    # -- state machine ------------------------------------------------------

    def _go(self, state, dims=None):
        """Move the shape to a state's size with the spring, and cross-fade its contents."""
        if not self._enabled:
            return
        if state != "listen":
            self.caption_bubble.fade_out()
        self._rest_timer.stop()
        self._snooze_anim.stop()
        self._snooze = 0.0
        self._state = state
        if state == "idle" or not self.isVisible():
            self._screen = self._target_screen()  # a screen change is picked up while resting
            self._refresh_scale()
        w, h, r = dims or DIMS[state]
        if state != "panel":  # the settings panel keeps its size; everything else follows the size settings
            w, h, r = w * self._wk, h * self._hk, r * self._hk
        self._to = (float(w), float(h), float(r))
        self._spring = SPRING.get(state, SPRING["idle"])
        self._prev_face, self._face = self._face, ("msg" if state == "msg" else state)
        self._face_anim.stop()
        self._face_anim.setDuration(FACE_MS if self._motion else 120)
        self._face_t = 0.0
        self._face_anim.start()
        target = self._shape_rect(self._to, 0.0)
        if self._spring[1] < 1.0:  # room for the overshoot, so the mask never clips the shape
            target.adjust(-0.06 * w, -0.06 * h, 0.06 * w, 0.06 * h)
        self._apply_mask(target)
        self._ensure_visible(state == "idle")
        self._frame.start()
        for r in self._rows:
            r.hide()
        if self._motion:
            if not self._moving:
                self._last = time.monotonic()
            self._moving = True
        else:
            self._dims = self._to
            self._on_shape_done()

    def _ensure_visible(self, may_change_screen):
        if not self._enabled:
            return
        if not self.isVisible() or may_change_screen:
            self._place()
            self.show()
        self.setWindowOpacity(self.opacity)
        _force_topmost(self)

    def _step_spring(self):
        """Advance the shape's spring by the real time since the last frame."""
        now = time.monotonic()
        dt, self._last = min(0.05, now - self._last), now   # a stalled frame never flings the shape
        response, zeta = self._spring
        k, c = (2 * math.pi / response) ** 2, 4 * math.pi * zeta / response
        dims, vel = [], []
        for x, v, to in zip(self._dims, self._vel, self._to):
            for _ in range(4):  # substeps keep a stiff spring stable at 60 fps
                v += (-k * (x - to) - c * v) * dt / 4
                x += v * dt / 4
            dims.append(x)
            vel.append(v)
        self._dims, self._vel = tuple(dims), tuple(vel)
        if all(abs(x - to) < 0.25 and abs(v) < 4 for x, v, to in zip(dims, vel, self._to)):
            self._on_shape_done()

    def _on_shape_done(self):
        self._moving, self._vel = False, (0.0, 0.0, 0.0)
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
        if not self._moving:
            self._frame.stop()

    def _tick(self):
        if self._moving:
            self._step_spring()
        self.update()
        if self.caption_bubble.isVisible():
            self.caption_bubble._reposition()  # follows the shape as it springs

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
        self._go("note" if sub else "msg", self._note_dims())

    def _note_dims(self):
        """Design size of the current notice (a two-line note is fixed; a one-line message follows its text)."""
        if self._note[1]:
            return None
        f = QFont(self.font_family)
        f.setPixelSize(14)
        tw = QFontMetrics(f).horizontalAdvance(self._note[0])
        need = (tw + 78) * self._sk / self._wk  # contents scale by the smaller factor; keep the whole text in view
        return (max(200, min((self.W - 24) / self._wk, need)), 44, 22)

    def _finish_note(self):
        self._to_idle()

    def show_message(self, text, duration_ms=2200):
        low = text.lower()
        icon = "warn" if any(k in low for k in ("error", "fail", "couldn", "stopped", "too long", "unavailable", "wrong")) else "info"
        if self._state in ("listen", "write"):
            # Dictation ended without text (a tap, too short, silent): leave the live state now. Queued, the
            # message only shows after the next pasted result, so the island sits in "recording" until then.
            self._preempt()
            self._start_note(text, "", icon, duration_ms, None, None)
            return
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
            self._done_timer.stop()  # a size preview may be showing this state: real dictation must not be cut short
            return
        self._preempt()
        self._go("listen")

    def show_processing(self):
        if self._state == "write":
            return
        self._preempt()
        self._go("write")

    show_refining = show_processing  # the island has no separate refining face

    def show_pasted(self, word_count=0, latency_ms=0):
        self._preempt()
        self._go("done")
        self._done_timer.start(1400)

    def set_amplitude(self, level):
        self.wave.set_level(level)
        if hasattr(self, "blobatar"):
            self.blobatar.set_level(level)

    def update_realtime_text(self, text):
        if text and self._state == "listen":
            self.caption_bubble.set_text(text[-160:])

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
        self._enabled = True
        self._motion = animations_enabled()  # the Windows setting may have changed since start
        self._snooze_anim.setDuration(360 if self._motion else 0)
        self._dims, self._vel, self._moving = DIMS["idle"], (0.0, 0.0, 0.0), False
        self._go("idle")
        self._to_idle()

    def deactivate(self):
        """Switched to another style: stop everything so no pending timer can bring the island back."""
        self._enabled = False
        for t in (self._rest_timer, self._note_timer, self._done_timer, self._frame):
            t.stop()
        for a in (self._face_anim, self._snooze_anim):
            a.stop()
        self._moving, self._vel = False, (0.0, 0.0, 0.0)
        self._queue.clear()
        self._note = None
        self._state, self._snooze = "idle", 0.0
        self.caption_bubble.fade_out()
        for r in self._rows:
            r.hide()
        self.hide()

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
        # contents swap: the old face fades out fast; the new one eases in a beat later, rising 4 px from 96%
        dur = self._face_anim.duration()
        ms = self._face_t * dur
        out_ms, in_at = (FACE_OUT_MS, FACE_IN_AT_MS) if self._motion else (dur / 2, 0)
        fade_out = max(0.0, 1.0 - ms / out_ms)
        fade_in = EASE_OUT.valueForProgress(min(1.0, max(0.0, (ms - in_at) / (dur - in_at))))
        if self._prev_face == self._face:
            fade_in = 1.0
        elif fade_out > 0:
            self._draw_face(p, self._prev_face, r, fade_out)
        self._draw_face(p, self._face, r, fade_in, (1.0 - fade_in) if self._motion else 0.0)
        is_odia = self.is_odia_active()
        self.blobatar.setVisible(self._state == "listen" and is_odia and fade_in > 0.4)
        if self.blobatar.isVisible():
            self.blobatar.move(int(r.left() + 10), int(r.center().y() - self.blobatar.height() / 2))
        self.wave.setVisible(self._state == "listen" and fade_in > 0.4)
        if self.wave.isVisible():
            self.wave.move(int(r.center().x() - self.wave.width() / 2), int(r.center().y() - self.wave.height() / 2))

    def _font(self, px, weight=QFont.Weight.Medium):
        f = QFont(self.font_family)
        f.setPixelSize(px)
        f.setWeight(weight)
        return f

    def _draw_face(self, p, face, r, a, rise=0.0):
        if a <= 0:
            return
        p.save()
        p.setOpacity(a)
        if rise > 0:  # still arriving: a little low and a little small, settling into place
            c = r.center()
            s = 1.0 - 0.04 * rise
            p.translate(c.x(), c.y() + 4 * rise)
            p.scale(s, s)
            p.translate(-c.x(), -c.y())
        s = 1.0 if face == "panel" else self._sk
        if s != 1.0:
            c = r.center()
            p.translate(c)
            p.scale(s, s)
            r = QRectF(-r.width() / (2 * s), -r.height() / (2 * s), r.width() / s, r.height() / s)
        cy = r.center().y()
        top = self.position == "top"
        if face == "idle":
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#3a3d44"))
            p.drawEllipse(r.center(), 3, 3)
        elif face == "listen":
            if not self.is_odia_active():
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
        self._size = (1.0, 1.0, False)
        pill.installEventFilter(self)  # whatever shows the classic capsule while the island is in use, it is hidden again
        for sig in ("sig_mic_changed", "sig_language_changed", "sig_tone_changed", "sig_model_changed",
                    "sig_open_dashboard", "sig_update_requested", "sig_hide_idle_changed"):
            getattr(pill, sig).connect(getattr(self, sig))
            getattr(island, sig).connect(getattr(self, sig))
        for name in self._BOTH:
            setattr(self, name, self._both(name))
        if style == "island":
            self.set_capsule_style("island")

    def eventFilter(self, obj, event):
        if obj is self._pill and self._on_island and event.type() == QEvent.Type.Show:
            QTimer.singleShot(0, self._pill.hide)
        return False

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
            self._island.deactivate()
            self._pill.set_follow_mouse_screen(self._follow)
            self._pill.set_capsule_size(*self._size)
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

    def set_capsule_size(self, wf, hf, auto):
        self._size = (wf, hf, auto)
        self._island.set_capsule_size(wf, hf, auto)
        if not self._on_island:  # re-laying out the hidden capsule could show it
            self._pill.set_capsule_size(wf, hf, auto)

    def geometry(self):
        return QRect() if self._on_island else self._pill.geometry()  # the meeting bar then uses its default spot

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._island if self._on_island else self._pill, name)
