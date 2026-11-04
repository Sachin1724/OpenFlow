"""
preview_mira_blob.py — Desktop Interactive Showcase for MIRA Blobatar
=====================================================================
Pops up an interactive preview window on Windows desktop showcasing:
1. Floating Capsule equipped with the living MIRA Blobatar
2. Top Dynamic Island with the MIRA Blobatar
3. Live audio amplitude slider & interactive poking
"""

import sys
import os
import math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QSlider, QPushButton, QFrame, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

from ui.mira_blob import MiraBlobAvatar
from ui.floating_pill import FloatingPill
from ui.island import IslandPill


class MiraBlobShowcase(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenFlow · MIRA Blobatar Desktop Sample")
        self.setFixedSize(560, 480)
        self.setStyleSheet("""
            QWidget {
                background-color: #0b0c10;
                color: #e0e2ec;
                font-family: 'Segoe UI', sans-serif;
            }
            QFrame#card {
                background-color: #14161f;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                padding: 16px;
            }
            QPushButton {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.14);
                border-radius: 8px;
                padding: 7px 14px;
                font-weight: 500;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.16);
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #252836;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #00f2fe;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Header
        title = QLabel("MIRA Blobatar Sample")
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title.setStyleSheet("color: #ffffff;")
        layout.addWidget(title)

        subtitle = QLabel("Organic living speech avatar with multi-stop Gaussian blend ('gaslan').")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setStyleSheet("color: #8c90a0;")
        layout.addWidget(subtitle)

        # --- SECTION 1: FLOATING CAPSULE WITH MIRA BLOBATAR ---
        card1 = QFrame()
        card1.setObjectName("card")
        c1_layout = QVBoxLayout(card1)
        c1_layout.setContentsMargins(16, 12, 16, 16)
        
        lbl_cap = QLabel("1. Floating Capsule (with MIRA Blobatar)")
        lbl_cap.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        lbl_cap.setStyleSheet("color: #00f2fe;")
        c1_layout.addWidget(lbl_cap)

        # Container for previewing the pill inline
        self.pill_container = QWidget()
        self.pill_container.setFixedHeight(54)
        pill_layout = QHBoxLayout(self.pill_container)
        pill_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Live Capsule Representation
        self.pill_box = QFrame()
        self.pill_box.setStyleSheet("""
            QFrame {
                background: rgba(14, 15, 19, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.16);
                border-radius: 22px;
                padding: 4px 14px;
            }
        """)
        box_layout = QHBoxLayout(self.pill_box)
        box_layout.setContentsMargins(8, 4, 12, 4)
        box_layout.setSpacing(10)

        # 1. The MIRA Blobatar!
        self.blob_pill = MiraBlobAvatar(size=28, parent=self.pill_box)
        self.blob_pill.set_state("listening")
        self.blob_pill.set_level(0.4)
        box_layout.addWidget(self.blob_pill)

        # 2. Text label
        self.txt_label = QLabel("Listening")
        self.txt_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self.txt_label.setStyleSheet("color: #ffffff; background: transparent; border: none;")
        box_layout.addWidget(self.txt_label)

        # 3. Dialect Badge
        self.badge = QLabel("Sambalpuri")
        self.badge.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.badge.setStyleSheet("""
            background: rgba(0, 242, 254, 0.15);
            color: #00f2fe;
            border: 1px solid rgba(0, 242, 254, 0.35);
            border-radius: 5px;
            padding: 2px 6px;
        """)
        box_layout.addWidget(self.badge)

        pill_layout.addWidget(self.pill_box)
        c1_layout.addWidget(self.pill_container)
        layout.addWidget(card1)

        # --- SECTION 2: LARGE ANATOMY INSPECTION ---
        card2 = QFrame()
        card2.setObjectName("card")
        c2_layout = QHBoxLayout(card2)
        c2_layout.setContentsMargins(16, 12, 16, 12)

        # Large Avatar
        self.blob_large = MiraBlobAvatar(size=72, parent=card2)
        self.blob_large.set_state("listening")
        self.blob_large.set_level(0.4)
        c2_layout.addWidget(self.blob_large)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(4)
        info_title = QLabel("Living Blobatar Anatomy")
        info_title.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        info_layout.addWidget(info_title)

        info_desc = QLabel("• Gaussian Aura: Multi-stop gradient melts into OLED capsule\n"
                           "• Natural Reactivity: Fluid Beziers morph with voice cadence\n"
                           "• Blinking Eyes & Gaze: Alive, listening to all words")
        info_desc.setFont(QFont("Segoe UI", 9))
        info_desc.setStyleSheet("color: #a0a4b4;")
        info_layout.addWidget(info_desc)
        c2_layout.addLayout(info_layout)

        layout.addWidget(card2)

        # --- SECTION 3: INTERACTIVE CONTROLS ---
        card3 = QFrame()
        card3.setObjectName("card")
        c3_layout = QVBoxLayout(card3)
        c3_layout.setSpacing(10)

        # Slider
        sl_layout = QHBoxLayout()
        sl_label = QLabel("Simulate Voice Level:")
        sl_label.setFont(QFont("Segoe UI", 10))
        self.sl_val = QLabel("40%")
        self.sl_val.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.sl_val.setStyleSheet("color: #00f2fe;")
        sl_layout.addWidget(sl_label)
        sl_layout.addStretch()
        sl_layout.addWidget(self.sl_val)
        c3_layout.addLayout(sl_layout)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(40)
        self.slider.valueChanged.connect(self._on_slider)
        c3_layout.addWidget(self.slider)

        # Buttons
        btn_layout = QHBoxLayout()
        self.btn_cyan = QPushButton("Electric Cyan")
        self.btn_amber = QPushButton("Warm Amber")
        self.btn_violet = QPushButton("Cosmic Violet")
        self.btn_web = QPushButton("🌐 Open Interactive Web Demo")

        self.btn_cyan.clicked.connect(lambda: self._set_palette("#00f2fe", "#4facfe"))
        self.btn_amber.clicked.connect(lambda: self._set_palette("#ff9a44", "#fc6076"))
        self.btn_violet.clicked.connect(lambda: self._set_palette("#f857a6", "#ff5858"))
        self.btn_web.clicked.connect(self._open_web_demo)

        btn_layout.addWidget(self.btn_cyan)
        btn_layout.addWidget(self.btn_amber)
        btn_layout.addWidget(self.btn_violet)
        btn_layout.addWidget(self.btn_web)
        c3_layout.addLayout(btn_layout)

        layout.addWidget(card3)

    def _on_slider(self, val: int):
        self.sl_val.setText(f"{val}%")
        lvl = val / 100.0
        self.blob_pill.set_level(lvl)
        self.blob_large.set_level(lvl)

    def _set_palette(self, p1: str, p2: str):
        self.blob_pill.set_palette(p1, p2)
        self.blob_large.set_palette(p1, p2)

    def _open_web_demo(self):
        import subprocess
        demo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "samples", "mira_blob_sample.html")
        os.startfile(demo_path)


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    showcase = MiraBlobShowcase()
    showcase.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
