import os
import threading
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon

try:
    from ..config import get_asset_path
    from ..engine import hardware, model_manager
    from ..engine.transcriber import engine_model_name
    from .styles import main_qss, COLORS
    from .floating_pill import get_squircle_pixmap, Switch
except (ImportError, ValueError):
    from config import get_asset_path
    from engine import hardware, model_manager
    from engine.transcriber import engine_model_name
    from ui.styles import main_qss, COLORS
    from ui.floating_pill import get_squircle_pixmap, Switch

LANGS = [("auto", "Auto Detect"), ("en-in", "English (India) / Hinglish"), ("or", "Odia / Odia-English"),
         ("hi", "Hindi"), ("en", "English (US/UK)"), ("es", "Spanish"), ("fr", "French"),
         ("de", "German"), ("zh", "Chinese"), ("ja", "Japanese"), ("pt", "Portuguese"), ("it", "Italian"),
         ("ar", "Arabic"), ("ru", "Russian"), ("ko", "Korean"), ("nl", "Dutch"), ("tr", "Turkish")]


class SetupDialog(QDialog):
    """First-run: pick language, download the matching Whisper model, optionally start at login."""
    _done = pyqtSignal(str)  # empty = ok, else error text
    _progress = pyqtSignal(int)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.setWindowTitle("OpenFlow Setup")
        self.setFixedWidth(440)
        self.setStyleSheet(main_qss() + "QDialog { background: #000000; }")

        icon_path = get_asset_path("app_icon_square.png")
        if not os.path.exists(icon_path):
            icon_path = get_asset_path("logo.jpg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 24)
        lay.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(14)

        self.logo_label = QLabel(self)
        if os.path.exists(icon_path):
            self.logo_label.setPixmap(get_squircle_pixmap(icon_path, size=46, radius=10.0))
            header_row.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignVCenter)

        header_text = QVBoxLayout()
        header_text.setSpacing(3)
        title = QLabel("Welcome to OpenFlow", self)
        title.setStyleSheet("font-size: 22px; font-weight: 500; color: #ffffff;")
        sub = QLabel("Private, local voice dictation on your device.", self)
        sub.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        header_text.addWidget(title)
        header_text.addWidget(sub)
        header_row.addLayout(header_text)
        header_row.addStretch()
        lay.addLayout(header_row)

        desc = QLabel("Choose your language. The speech recognition model downloads once, then everything runs 100% offline.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; line-height: 1.4;")
        lay.addWidget(desc)


        self.lang = QComboBox()
        for code, name in LANGS:
            self.lang.addItem(name, code)
        lay.addWidget(self.lang)

        self.hw = hardware.detect()
        npu = hardware.npu_name()
        hw_note = QLabel("Your PC: " + self.hw["note"] + (f" {npu} NPU found." if npu else ""))
        hw_note.setWordWrap(True)
        hw_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        lay.addWidget(hw_note)

        self.device = QComboBox()
        self.device.addItem("Run on: Automatic (recommended)", "auto")
        if npu:
            self.device.addItem(f"Run on: NPU ({npu}, low power)", "npu")
        self.device.addItem("Run on: GPU (NVIDIA CUDA)", "cuda")
        self.device.addItem("Run on: CPU", "cpu")
        if npu and not self.hw["cuda_ok"]:  # no NVIDIA GPU: the NPU beats the CPU on speed and battery
            self.device.setCurrentIndex(1)
        lay.addWidget(self.device)

        self.quality = QComboBox()
        for key, label in [("auto", f"Quality: Automatic ({self.hw['model_size']})"), ("tiny", "Quality: Tiny, fastest"),
                           ("base", "Quality: Base, balanced"), ("small", "Quality: Small, accurate"),
                           ("medium", "Quality: Medium, best")]:
            self.quality.addItem(label, key)
        lay.addWidget(self.quality)

        self.cb_start = Switch("Start OpenFlow when I sign in")
        self.cb_start.setChecked(True)
        lay.addWidget(self.cb_start)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        self.bar.setStyleSheet("QProgressBar { background: rgba(255,255,255,0.10); border: none; border-radius: 2px; }"
                               "QProgressBar::chunk { background: #ffffff; border-radius: 2px; }")
        self.bar.hide()
        lay.addWidget(self.bar)
        lay.addWidget(self.status)

        self.btn = QPushButton("Download and Continue")
        self.btn.setObjectName("PrimaryButton")
        self.btn.clicked.connect(self._start)
        lay.addWidget(self.btn)

        self._done.connect(self._finish)
        self._progress.connect(self._on_progress)

    def _start(self):
        self.btn.setEnabled(False)
        for w in (self.lang, self.device, self.quality):
            w.setEnabled(False)
        self.bar.show()
        code = self.lang.currentData()
        size = self.quality.currentData()
        size = self.hw["model_size"] if size == "auto" else size
        model = engine_model_name(size, code, self.device.currentData())
        self.status.setText(f"Downloading {model} model...")
        threading.Thread(target=self._download, args=(model,), daemon=True).start()

    def _download(self, model: str):
        try:
            model_manager.download(model, self._progress.emit)
            self._done.emit("")
        except Exception as e:
            self._done.emit(str(e))

    def _on_progress(self, pct: int):
        self.bar.setValue(pct)
        self.status.setText(f"Downloading model  {pct}%")

    def _finish(self, err: str):
        if err:
            self.bar.hide()
            self.status.setText(f"Download failed: {err}")
            self.btn.setText("Retry")
            self.btn.setEnabled(True)
            for w in (self.lang, self.device, self.quality):
                w.setEnabled(True)
            return
        self.config["language"] = self.lang.currentData()
        self.config["device"] = self.device.currentData()
        # save the size that was downloaded, never "auto": later boots must not pick a bigger model
        size = self.quality.currentData()
        self.config["model_size"] = self.hw["model_size"] if size == "auto" else size
        self.config["compute_type"] = "auto"
        self.config["autostart"] = self.cb_start.isChecked()
        self.config["setup_done"] = True
        self.accept()
