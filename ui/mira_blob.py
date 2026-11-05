"""
mira_blob.py — Reactive Living "Blobatar" Indicator for OpenFlow Capsule & Island
==================================================================================
Replaces the mechanical recording dot with an organic, listening Blobatar:
1. Multi-stop Gaussian diffuse aura ("gaslan") that melts seamlessly into the dark glass capsule
2. Organic cubic Bezier fluid morphing responding directly to microphone voice amplitude
3. Expressive living facial features: natural eye blinks, curious pupil tracking, listening mouth
4. Sub-millisecond 60 FPS rendering via hardware-accelerated QPainter
"""

import math
import time
from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QRadialGradient, QLinearGradient
from PyQt6.QtWidgets import QWidget


class MiraBlobAvatar(QWidget):
    """Organic living blob avatar that listens and reacts to voice."""

    def __init__(self, size: int = 24, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.base_size = size
        
        # State & Animation parameters
        self.state = "listening"  # "idle", "listening", "processing", "done"
        self.phase = 0.0
        self.audio_level = 0.0
        self.smoothed_level = 0.0
        
        # Eye blinking physics
        self.blink_timer = 0.0
        self.is_blinking = False
        self.blink_progress = 0.0
        self.next_blink = 3.0  # seconds until next blink
        
        # Gaussian aura glow style
        # Palette: Vibrant Neon Cyan / Sky Blue blending into glass capsule
        self.primary_color = QColor(0, 242, 254)      # Electric Cyan #00f2fe
        self.secondary_color = QColor(79, 172, 254)   # Electric Blue #4facfe
        self.glow_color = QColor(0, 220, 255)
        
        # 60 FPS smooth rendering loop
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.start(16)

    def set_level(self, level: float):
        """Set raw microphone audio level (0.0 to 1.0)."""
        self.audio_level = max(0.0, min(1.0, float(level)))

    def set_state(self, state: str):
        """Update state: 'idle', 'listening', 'processing', 'done'."""
        self.state = state
        self.update()

    def set_palette(self, primary: str, secondary: str):
        """Customize blob colors (e.g. for different modes or tones)."""
        self.primary_color = QColor(primary)
        self.secondary_color = QColor(secondary)
        self.glow_color = QColor(primary)
        self.update()

    def _tick(self):
        dt = 0.016
        self.phase += dt * 3.5
        
        # Smooth audio amplitude tracking (spring physics)
        self.smoothed_level += (self.audio_level - self.smoothed_level) * 0.25
        # Passive decay if no new audio fed
        self.audio_level = max(0.0, self.audio_level - dt * 1.5)

        # Eye blink logic
        self.blink_timer += dt
        if not self.is_blinking:
            if self.blink_timer >= self.next_blink:
                self.is_blinking = True
                self.blink_progress = 0.0
        else:
            self.blink_progress += dt / 0.14  # blink takes 140ms
            if self.blink_progress >= 1.0:
                self.is_blinking = False
                self.blink_timer = 0.0
                # Randomize next blink between 2.5 and 5.0 seconds
                self.next_blink = 2.5 + (math.sin(self.phase * 0.7) * 0.5 + 0.5) * 2.5

        self.update()

    def _generate_blob_path(self, center: QPointF, radius: float, num_points: int = 8) -> QPainterPath:
        """Generate smooth, organic cubic Bezier spline for fluid blob shape."""
        points = []
        angle_step = (2 * math.pi) / num_points
        
        # Harmonic perturbation based on time and audio
        voice_factor = self.smoothed_level * 0.45
        
        for i in range(num_points):
            angle = i * angle_step
            # Multiple sine harmonics for liquid surface tension
            w1 = math.sin(self.phase * 1.8 + angle * 2.0) * 0.08
            w2 = math.cos(self.phase * 2.6 - angle * 3.0) * 0.05
            w3 = math.sin(self.phase * 4.0 + angle * 1.0) * voice_factor
            
            r = radius * (1.0 + w1 + w2 + w3)
            x = center.x() + r * math.cos(angle)
            y = center.y() + r * math.sin(angle)
            points.append(QPointF(x, y))

        # Build closed smooth Bezier path
        path = QPainterPath()
        path.moveTo(points[0])
        
        for i in range(num_points):
            p0 = points[(i - 1) % num_points]
            p1 = points[i]
            p2 = points[(i + 1) % num_points]
            p3 = points[(i + 2) % num_points]

            # Catmull-Rom to Cubic Bezier conversion for organic curvature
            c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0, p1.y() + (p2.y() - p0.y()) / 6.0)
            c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0, p2.y() - (p3.y() - p1.y()) / 6.0)
            path.cubicTo(c1, c2, p2)

        return path

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        w, h = float(self.width()), float(self.height())
        center = QPointF(w / 2.0, h / 2.0)
        base_radius = min(w, h) * 0.36
        
        # React to listening state
        is_listening = (self.state == "listening")
        level_boost = self.smoothed_level if is_listening else 0.0
        current_radius = base_radius * (1.0 + level_boost * 0.22)

        # -------------------------------------------------------------
        # 1. GAUSSIAN DIFFUSE AURA ("gaslan" multi-stop Gaussian falloff)
        # -------------------------------------------------------------
        # Bell curve: alpha = exp(-(r / sigma)^2)
        glow_radius = current_radius * (2.1 + level_boost * 0.7)
        grad_glow = QRadialGradient(center, glow_radius)
        
        # Soft Gaussian stops blending seamlessly into dark OLED glass (#0e0f12)
        base_alpha = 110 if is_listening else 50
        alpha_boost = int(base_alpha + level_boost * 110)
        alpha_boost = min(220, alpha_boost)
        
        grad_glow.setColorAt(0.00, QColor(self.glow_color.red(), self.glow_color.green(), self.glow_color.blue(), int(alpha_boost * 0.85)))
        grad_glow.setColorAt(0.25, QColor(self.glow_color.red(), self.glow_color.green(), self.glow_color.blue(), int(alpha_boost * 0.55)))
        grad_glow.setColorAt(0.50, QColor(self.glow_color.red(), self.glow_color.green(), self.glow_color.blue(), int(alpha_boost * 0.28)))
        grad_glow.setColorAt(0.75, QColor(self.glow_color.red(), self.glow_color.green(), self.glow_color.blue(), int(alpha_boost * 0.10)))
        grad_glow.setColorAt(1.00, QColor(self.glow_color.red(), self.glow_color.green(), self.glow_color.blue(), 0))
        
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad_glow))
        p.drawEllipse(center, glow_radius, glow_radius)

        # -------------------------------------------------------------
        # 2. FLUID ORGANIC BLOB BODY
        # -------------------------------------------------------------
        blob_path = self._generate_blob_path(center, current_radius, num_points=8)
        
        # Organic gradient fill
        blob_grad = QLinearGradient(center.x() - current_radius, center.y() - current_radius,
                                    center.x() + current_radius, center.y() + current_radius)
        blob_grad.setColorAt(0.0, self.primary_color)
        blob_grad.setColorAt(1.0, self.secondary_color)
        
        p.setBrush(QBrush(blob_grad))
        p.setPen(QPen(QColor(255, 255, 255, 140), 1.0))  # Specular rim
        p.drawPath(blob_path)

        # -------------------------------------------------------------
        # 3. SPECULAR HIGHLIGHT (3D glossy sheen)
        # -------------------------------------------------------------
        sheen_pos = QPointF(center.x() - current_radius * 0.35, center.y() - current_radius * 0.35)
        sheen_r = current_radius * 0.32
        sheen_grad = QRadialGradient(sheen_pos, sheen_r)
        sheen_grad.setColorAt(0.0, QColor(255, 255, 255, 170))
        sheen_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(sheen_grad))
        p.drawEllipse(sheen_pos, sheen_r, sheen_r * 0.7)

        # -------------------------------------------------------------
        # 4. LIVING FACIAL FEATURES (Eyes + Listening Expression)
        # -------------------------------------------------------------
        # Eye physics
        eye_y = center.y() - current_radius * 0.12
        eye_spacing = current_radius * 0.42
        eye_rx = current_radius * 0.16
        
        # Calculate eye height with blink easing
        if self.is_blinking:
            # Symmetrical blink curve
            prog = self.blink_progress
            scale_y = abs(math.cos(prog * math.pi))
            eye_ry = max(0.4, current_radius * 0.18 * scale_y)
        else:
            # Listening wideness
            eye_ry = current_radius * (0.18 + level_boost * 0.08)

        # Pupils gaze slightly up or follow voice cadence
        gaze_dx = math.sin(self.phase * 0.8) * (eye_rx * 0.25)
        gaze_dy = -abs(math.cos(self.phase * 0.5)) * (eye_ry * 0.2) if is_listening else 0.0

        p.setBrush(QColor(15, 20, 28))  # Dark deep ink pupil
        p.setPen(Qt.PenStyle.NoPen)
        
        # Left Eye
        left_eye_center = QPointF(center.x() - eye_spacing + gaze_dx, eye_y + gaze_dy)
        p.drawEllipse(left_eye_center, eye_rx, eye_ry)
        
        # Right Eye
        right_eye_center = QPointF(center.x() + eye_spacing + gaze_dx, eye_y + gaze_dy)
        p.drawEllipse(right_eye_center, eye_rx, eye_ry)

        # Catchlight sparkles (alive reflection in eyes)
        if not self.is_blinking:
            p.setBrush(QColor(255, 255, 255, 230))
            sparkle_r = max(0.8, eye_rx * 0.35)
            p.drawEllipse(QPointF(left_eye_center.x() - eye_rx * 0.25, left_eye_center.y() - eye_ry * 0.3), sparkle_r, sparkle_r)
            p.drawEllipse(QPointF(right_eye_center.x() - eye_rx * 0.25, right_eye_center.y() - eye_ry * 0.3), sparkle_r, sparkle_r)

        # -------------------------------------------------------------
        # 5. LISTENING MOUTH (Tiny smiling curve or talking 'o')
        # -------------------------------------------------------------
        mouth_y = center.y() + current_radius * 0.32
        if level_boost > 0.12:
            # Talking / Listening 'o'
            mouth_w = current_radius * 0.22
            mouth_h = current_radius * (0.12 + level_boost * 0.25)
            p.setBrush(QColor(15, 20, 28))
            p.drawEllipse(QPointF(center.x(), mouth_y), mouth_w, mouth_h)
        else:
            # Gentle relaxed smile arc
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(15, 20, 28, 200), 1.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            mouth_w = current_radius * 0.28
            mouth_rect = QRectF(center.x() - mouth_w, mouth_y - 2, mouth_w * 2, 4)
            p.drawArc(mouth_rect, 190 * 16, 160 * 16)

