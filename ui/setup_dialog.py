import threading
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QPushButton, QProgressBar, QCheckBox
from PyQt6.QtCore import Qt, pyqtSignal

from ..engine import hardware, model_manager
from ..engine.transcriber import resolve_model_name
from .styles import MAIN_WINDOW_QSS, COLORS

LANGS = [("en", "English"), ("auto", "Auto Detect"), ("hi", "Hindi"), ("es", "Spanish"), ("fr", "French"),
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
        self.setFixedWidth(420)
        self.setStyleSheet(MAIN_WINDOW_QSS + "QDialog { background: #000000; }")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 28, 28, 24)
        lay.setSpacing(12)

        title = QLabel("Welcome to OpenFlow")
        title.setStyleSheet("font-size: 22px; font-weight: 400;")
        sub = QLabel("Choose your language. The speech model downloads once, then everything runs offline.")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"color: {COLORS['text_secondary']};")
        lay.addWidget(title)
        lay.addWidget(sub)

        self.lang = QComboBox()
        for code, name in LANGS:
            self.lang.addItem(name, code)
        lay.addWidget(self.lang)

        self.hw = hardware.detect()
        hw_note = QLabel("Your PC: " + self.hw["note"])
        hw_note.setWordWrap(True)
        hw_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        lay.addWidget(hw_note)

        self.device = QComboBox()
        self.device.addItem("Run on: Automatic (recommended)", "auto")
        self.device.addItem("Run on: GPU (NVIDIA CUDA)", "cuda")
        self.device.addItem("Run on: CPU", "cpu")
        lay.addWidget(self.device)

        self.quality = QComboBox()
        for key, label in [("auto", f"Quality: Automatic ({self.hw['model_size']})"), ("tiny", "Quality: Tiny, fastest"),
                           ("base", "Quality: Base, balanced"), ("small", "Quality: Small, accurate"),
                           ("medium", "Quality: Medium, best")]:
            self.quality.addItem(label, key)
        lay.addWidget(self.quality)

        self.cb_start = QCheckBox("Start OpenFlow when I sign in")
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
        model = resolve_model_name(size, code)
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
        self.config["model_size"] = self.quality.currentData()
        self.config["compute_type"] = "auto"
        self.config["autostart"] = self.cb_start.isChecked()
        self.config["setup_done"] = True
        self.accept()
