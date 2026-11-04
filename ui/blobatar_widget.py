"""
blobatar_widget.py — Native PyQt6 Widget for Official @blobatar/react SVG
==========================================================================
Renders the official Blobatar character (name='alain00', traits={{ shape: 0.65 }})
with:
1. Real-time mouse pointer gaze tracking (eyes look towards Windows cursor)
2. 3D perspective head tilt following the cursor position
3. Multi-stop Gaussian diffuse aura ("gaslan") that melts into the dark OLED glass capsule
4. Audio breathing and eye blink animations at 60 FPS
"""

import math
import time
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF, QByteArray
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QRadialGradient, QCursor
from PyQt6.QtWidgets import QWidget
from PyQt6.QtSvg import QSvgRenderer

# Exact official SVG paths from blobatar('alain00', { traits: { shape: 0.65 } })
_HEAD_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <g fill="{head_color}">
    <circle cx="33.69" cy="51.21" r="19.09"/>
    <circle cx="64" cy="51.21" r="19.09"/>
    <path d="M33.69 32.12H64V70.3H33.69Z"/>
  </g>
</svg>"""

_EYES_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <g fill="{eye_color}">
    <path d="M43.34 48.83C45.07 57.03 45.07 57.05 42.18 57.66C39.29 58.27 39.28 58.26 37.54 50.06C35.8 41.86 35.81 41.84 38.7 41.23C41.59 40.62 41.6 40.63 43.34 48.83Z"/>
    <path d="M64.23 49.01C65.85 56.61 65.84 56.63 62.71 57.29C59.58 57.96 59.57 57.95 57.96 50.34C56.34 42.74 56.34 42.72 59.47 42.06C62.6 41.39 62.61 41.4 64.23 49.01Z"/>
  </g>
</svg>"""


def calculate_gaze_vector(center: QPointF, cursor_pos: QPointF, max_eye_offset: float = 3.5) -> tuple[float, float, float]:
    """Calculate eye gaze offset (gx, gy) and head tilt angle (degrees) towards the mouse cursor."""
    dx = cursor_pos.x() - center.x()
    dy = cursor_pos.y() - center.y()
    dist = math.hypot(dx, dy)
    if dist < 1e-4:
        return 0.0, 0.0, 0.0

    nx = dx / dist
    ny = dy / dist

    # Logarithmic saturation reach: close mouse moves pupils slightly, far mouse saturates at max_eye_offset
    reach = min(max_eye_offset, dist * 0.015)
    gx = nx * reach
    gy = ny * reach

    # 3D Head Tilt angle (max +- 4.5 degrees)
    tilt = nx * min(4.5, dist * 0.008)

    return gx, gy, tilt


class BlobatarWidget(QWidget):
    """Native PyQt6 implementation of the Blobatar capsule avatar with cursor tracking."""

    def __init__(self, size: int = 28, head_color: str = "#a5ddff", eye_color: str = "#071117", parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.base_size = size
        self.head_color = head_color
        self.eye_color = eye_color
        
        # Gaussian aura glow settings ("gaslan")
        self.glow_color = QColor(head_color)
        
        # Audio & animation state
        self.phase = 0.0
        self.audio_level = 0.0
        self.smoothed_level = 0.0
        
        # Real-time gaze tracking & head tilt
        self.target_gaze_x = 0.0
        self.target_gaze_y = 0.0
        self.target_tilt = 0.0
        self.current_gaze_x = 0.0
        self.current_gaze_y = 0.0
        self.current_tilt = 0.0
        
        # Eye blinking
        self.blink_timer = 0.0
        self.is_blinking = False
        self.blink_progress = 0.0
        self.next_blink = 3.5

        # Renderers for head and eyes (enables independent parallax tracking)
        self.head_renderer = QSvgRenderer()
        self.eyes_renderer = QSvgRenderer()
        self._update_svg()

        # 60 FPS animation loop
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.start(16)

    def _update_svg(self):
        head_xml = _HEAD_SVG.format(head_color=self.head_color)
        eyes_xml = _EYES_SVG.format(eye_color=self.eye_color)
        self.head_renderer.load(QByteArray(head_xml.encode("utf-8")))
        self.eyes_renderer.load(QByteArray(eyes_xml.encode("utf-8")))

    def set_level(self, level: float):
        self.audio_level = max(0.0, min(1.0, float(level)))

    def set_colors(self, head_color: str, eye_color: str = "#071117"):
        self.head_color = head_color
        self.eye_color = eye_color
        self.glow_color = QColor(head_color)
        self._update_svg()
        self.update()

    def _tick(self):
        dt = 0.016
        self.phase += dt * 3.0
        self.smoothed_level += (self.audio_level - self.smoothed_level) * 0.25
        self.audio_level = max(0.0, self.audio_level - dt * 1.5)

        # 1. Real-time Mouse Pointer Gaze & Head Tilt Tracking
        try:
            cursor_pos = QCursor.pos()
            global_center = self.mapToGlobal(self.rect().center())
            max_offset = self.width() * 0.09
            tgx, tgy, ttilt = calculate_gaze_vector(QPointF(global_center), QPointF(cursor_pos), max_eye_offset=max_offset)
            self.target_gaze_x, self.target_gaze_y, self.target_tilt = tgx, tgy, ttilt
        except Exception:
            pass

        # Spring damping interpolation (lerp)
        lerp_factor = 0.18
        self.current_gaze_x += (self.target_gaze_x - self.current_gaze_x) * lerp_factor
        self.current_gaze_y += (self.target_gaze_y - self.current_gaze_y) * lerp_factor
        self.current_tilt += (self.target_tilt - self.current_tilt) * lerp_factor

        # 2. Eye Blinking Physics
        self.blink_timer += dt
        if not self.is_blinking:
            if self.blink_timer >= self.next_blink:
                self.is_blinking = True
                self.blink_progress = 0.0
        else:
            self.blink_progress += dt / 0.14
            if self.blink_progress >= 1.0:
                self.is_blinking = False
                self.blink_timer = 0.0
                self.next_blink = 2.5 + (math.sin(self.phase * 0.8) * 0.5 + 0.5) * 2.5

        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        center = QPointF(w / 2.0, h / 2.0)
        boost = self.smoothed_level

        # -------------------------------------------------------------
        # 1. GAUSSIAN DIFFUSE AURA ("gaslan")
        # -------------------------------------------------------------
        aura_r = (w / 2.0) * (1.15 + boost * 0.4)
        grad = QRadialGradient(center, aura_r)
        alpha = int(120 + boost * 110)
        alpha = min(235, alpha)

        gc = self.glow_color
        grad.setColorAt(0.00, QColor(gc.red(), gc.green(), gc.blue(), int(alpha * 0.85)))
        grad.setColorAt(0.35, QColor(gc.red(), gc.green(), gc.blue(), int(alpha * 0.45)))
        grad.setColorAt(0.65, QColor(gc.red(), gc.green(), gc.blue(), int(alpha * 0.18)))
        grad.setColorAt(0.85, QColor(gc.red(), gc.green(), gc.blue(), int(alpha * 0.05)))
        grad.setColorAt(1.00, QColor(gc.red(), gc.green(), gc.blue(), 0))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(center, aura_r, aura_r)

        # -------------------------------------------------------------
        # 2. 3D HEAD TILT & BREATHING PARALLAX
        # -------------------------------------------------------------
        p.save()
        p.translate(center)

        # Breathing + speech bobbing
        breathe = 1.0 + math.sin(self.phase * 2.2) * 0.02 + boost * 0.16
        bob_y = math.sin(self.phase * 1.8) * (0.8 + boost * 1.8)
        
        # Parallax head shift & tilt
        head_shift_x = self.current_gaze_x * 0.35
        head_shift_y = self.current_gaze_y * 0.35
        
        p.translate(head_shift_x, bob_y + head_shift_y)
        p.rotate(self.current_tilt)
        p.scale(breathe, breathe)

        # Render Head SVG
        svg_w = w * 0.88
        svg_h = h * 0.88
        svg_rect = QRectF(-svg_w / 2.0, -svg_h / 2.0, svg_w, svg_h)
        self.head_renderer.render(p, svg_rect)

        # -------------------------------------------------------------
        # 3. INDEPENDENT EYE GAZE TRACKING (Looking at Windows Cursor)
        # -------------------------------------------------------------
        p.save()
        # Eyes shift further in cursor direction for lifelike parallax depth
        p.translate(self.current_gaze_x * 0.85, self.current_gaze_y * 0.85)

        if not self.is_blinking:
            self.eyes_renderer.render(p, svg_rect)
        else:
            # Mask eyes during blink
            prog = self.blink_progress
            scale_y = abs(math.cos(prog * math.pi))
            if scale_y >= 0.5:
                # Semi-closed eyes
                p.save()
                p.scale(1.0, scale_y)
                self.eyes_renderer.render(p, svg_rect)
                p.restore()
            else:
                # Draw thin eyelid line
                eye1_x = svg_rect.left() + svg_rect.width() * 0.40
                eye2_x = svg_rect.left() + svg_rect.width() * 0.61
                eye_y = svg_rect.top() + svg_rect.height() * 0.50
                eye_r = svg_rect.width() * 0.08
                p.setPen(QPen(QColor(self.eye_color), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(eye1_x - eye_r, eye_y), QPointF(eye1_x + eye_r, eye_y))
                p.drawLine(QPointF(eye2_x - eye_r, eye_y), QPointF(eye2_x + eye_r, eye_y))

        p.restore()
        p.restore()
