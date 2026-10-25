from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QComboBox, QCheckBox, QFrame, QMessageBox, QAbstractItemView, QDoubleSpinBox, QProgressBar
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QColor, QPixmap
import pyperclip

from ..config import load_config, save_config
from ..database import Database
from ..engine import hardware
from ..engine.audio_recorder import list_microphones
from .styles import MAIN_WINDOW_QSS, COLORS


class MainWindow(QMainWindow):
    config_changed = pyqtSignal(dict)
    sig_request_check_update = pyqtSignal()
    sig_request_install_update = pyqtSignal()

    def __init__(self, db: Database, config: dict):
        super().__init__()
        self.db = db
        self.config = config

        self.setWindowTitle("OpenFlow")
        self.setMinimumSize(880, 640)
        self.setStyleSheet(MAIN_WINDOW_QSS)

        self._init_ui()
        self.refresh_history()
        self.refresh_dictionary()
        self.refresh_stats()

    def _init_ui(self):
        central = QWidget(self)
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(24, 20, 24, 20)
        main_layout.setSpacing(16)

        # Header Section
        header_layout = QHBoxLayout()

        # Logo thumbnail or vector mark
        logo_label = QLabel(self)
        import os
        logo_path = os.path.join(os.path.dirname(__file__), "..", "assets", "logo.jpg")
        if os.path.exists(logo_path):
            pix = QPixmap(logo_path).scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pix)
            logo_label.setStyleSheet("border-radius: 8px;")
            header_layout.addWidget(logo_label)

        header_title_layout = QVBoxLayout()
        header_title_layout.setSpacing(3)

        title_label = QLabel("OpenFlow", self)
        title_label.setStyleSheet("font-size: 24px; font-weight: 400; color: #ffffff;")

        subtitle_label = QLabel("Private, unlimited voice dictation. Runs on your device.", self)
        subtitle_label.setStyleSheet(f"font-size: 13px; color: {COLORS['text_secondary']};")

        header_title_layout.addWidget(title_label)
        header_title_layout.addWidget(subtitle_label)
        header_layout.addLayout(header_title_layout)
        header_layout.addStretch()

        # Hotkey badge card
        hotkey_badge = QFrame(self)
        hotkey_badge.setObjectName("HotkeyBadge")
        hotkey_badge.setStyleSheet("QFrame#HotkeyBadge { background: rgba(255, 255, 255, 0.08); border-radius: 14px; }")
        badge_layout = QHBoxLayout(hotkey_badge)
        badge_layout.setContentsMargins(8, 4, 8, 4)
        badge_text = QLabel(f"Hold <b>{self.config.get('hotkey', 'ctrl+shift').upper()}</b> to speak", self)
        badge_text.setStyleSheet("color: #ffffff; font-size: 12px;")
        badge_layout.addWidget(badge_text)
        header_layout.addWidget(hotkey_badge)

        main_layout.addLayout(header_layout)

        # Model download progress (hidden unless a model is downloading)
        self.dl_box = QWidget(self)
        dl_lay = QHBoxLayout(self.dl_box)
        dl_lay.setContentsMargins(0, 0, 0, 0)
        dl_lay.setSpacing(14)
        self.dl_label = QLabel("", self)
        self.dl_label.setStyleSheet(f"color: {COLORS['text_secondary']};")
        self.dl_bar = QProgressBar(self)
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setTextVisible(False)
        self.dl_bar.setFixedHeight(4)
        self.dl_bar.setStyleSheet("QProgressBar { background: rgba(255,255,255,0.10); border: none; border-radius: 2px; }"
                                  "QProgressBar::chunk { background: #ffffff; border-radius: 2px; }")
        dl_lay.addWidget(self.dl_label)
        dl_lay.addWidget(self.dl_bar, 1)
        self.dl_box.hide()
        main_layout.addWidget(self.dl_box)

        # Tabs
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._create_history_tab(), "History")
        self.tabs.addTab(self._create_dictionary_tab(), "Vocabulary")
        self.tabs.addTab(self._create_settings_tab(), "Settings")
        self.tabs.addTab(self._create_stats_tab(), "Analytics")

        main_layout.addWidget(self.tabs)

    def set_download(self, percent: int, model: str):
        """Shows or hides the download bar under the header."""
        if percent >= 100:
            self.dl_box.hide()
            return
        self.dl_label.setText(f"Downloading {model} model  {percent}%")
        self.dl_bar.setValue(percent)
        self.dl_box.show()

    def _create_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Search Bar & Actions
        search_layout = QHBoxLayout()
        self.history_search = QLineEdit(self)
        self.history_search.setPlaceholderText("Search history")
        self.history_search.textChanged.connect(self.refresh_history)
        search_layout.addWidget(self.history_search)

        refresh_btn = QPushButton("Refresh", self)
        refresh_btn.clicked.connect(self.refresh_history)
        search_layout.addWidget(refresh_btn)

        clear_btn = QPushButton("Clear All", self)
        clear_btn.clicked.connect(self._clear_history)
        search_layout.addWidget(clear_btn)

        layout.addLayout(search_layout)

        # Table
        self.history_table = QTableWidget(0, 5, self)
        self.history_table.setHorizontalHeaderLabels(["Time", "Target App", "Words", "Speed", "Transcribed Text"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

        self.history_table.cellDoubleClicked.connect(self._copy_history_row)
        layout.addWidget(self.history_table)

        hint = QLabel("Double-click a row to copy its text.", self)
        hint.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        layout.addWidget(hint)

        return widget

    def refresh_history(self):
        query = self.history_search.text().strip() if hasattr(self, "history_search") else ""
        rows = self.db.get_history(limit=150, query=query)
        self.history_table.setRowCount(len(rows))

        for idx, row in enumerate(rows):
            ts = row["timestamp"][:19].replace("T", " ") if "T" in row["timestamp"] else row["timestamp"]
            app = row["target_app"] or "Desktop"
            words = str(row["word_count"] or len(row["formatted_text"].split()))
            latency = f"{row['latency_ms']}ms" if row["latency_ms"] else "-"
            text = row["formatted_text"]

            self.history_table.setItem(idx, 0, QTableWidgetItem(ts))
            self.history_table.setItem(idx, 1, QTableWidgetItem(app))
            self.history_table.setItem(idx, 2, QTableWidgetItem(words))
            self.history_table.setItem(idx, 3, QTableWidgetItem(latency))
            self.history_table.setItem(idx, 4, QTableWidgetItem(text))

    def _copy_history_row(self, row, col):
        item = self.history_table.item(row, 4)
        if item:
            pyperclip.copy(item.text())
            QMessageBox.information(self, "Copied", "Transcription copied to clipboard.")

    def _clear_history(self):
        reply = QMessageBox.question(self, "Confirm Clear", "Clear all dictation history?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.db.clear_history()
            self.refresh_history()
            self.refresh_stats()

    def _create_dictionary_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        desc = QLabel("Add custom terms, acronyms, or names. OpenFlow will automatically correct them in your speech.", self)
        desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        layout.addWidget(desc)

        form_frame = QFrame(self)
        form_frame.setProperty("class", "Card")
        form_layout = QHBoxLayout(form_frame)
        form_layout.setContentsMargins(12, 10, 12, 10)

        self.dict_phrase = QLineEdit(self)
        self.dict_phrase.setPlaceholderText("Phrase spoken (e.g. 'pi torch', 'open flow')")
        self.dict_replace = QLineEdit(self)
        self.dict_replace.setPlaceholderText("Replace with (e.g. 'PyTorch', 'OpenFlow')")

        self.dict_case = QCheckBox("Case sensitive", self)
        add_btn = QPushButton("Add Word", self)
        add_btn.setObjectName("PrimaryButton")
        add_btn.clicked.connect(self._add_dictionary_word)

        form_layout.addWidget(self.dict_phrase, 2)
        form_layout.addWidget(self.dict_replace, 2)
        form_layout.addWidget(self.dict_case)
        form_layout.addWidget(add_btn)
        layout.addWidget(form_frame)

        self.dict_table = QTableWidget(0, 4, self)
        self.dict_table.setHorizontalHeaderLabels(["ID", "Spoken Match", "Replaced With", "Case Sensitive"])
        self.dict_table.verticalHeader().setVisible(False)
        self.dict_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.dict_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.dict_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.dict_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.dict_table)

        del_btn = QPushButton("Delete Selected", self)
        del_btn.clicked.connect(self._delete_dictionary_word)
        layout.addWidget(del_btn)

        return widget

    def refresh_dictionary(self):
        rows = self.db.get_dictionary()
        self.dict_table.setRowCount(len(rows))
        for idx, row in enumerate(rows):
            self.dict_table.setItem(idx, 0, QTableWidgetItem(str(row["id"])))
            self.dict_table.setItem(idx, 1, QTableWidgetItem(row["phrase_match"]))
            self.dict_table.setItem(idx, 2, QTableWidgetItem(row["replace_with"]))
            self.dict_table.setItem(idx, 3, QTableWidgetItem("Yes" if row["case_sensitive"] else "No"))

    def _add_dictionary_word(self):
        phrase = self.dict_phrase.text().strip()
        replace = self.dict_replace.text().strip()
        case_sens = self.dict_case.isChecked()
        if not phrase or not replace:
            QMessageBox.warning(self, "Missing Fields", "Please enter both spoken phrase and replacement.")
            return
        self.db.add_dictionary_entry(phrase, replace, case_sens)
        self.dict_phrase.clear()
        self.dict_replace.clear()
        self.refresh_dictionary()

    def _delete_dictionary_word(self):
        row = self.dict_table.currentRow()
        if row >= 0:
            entry_id = int(self.dict_table.item(row, 0).text())
            self.db.delete_dictionary_entry(entry_id)
            self.refresh_dictionary()

    def _create_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        card = QFrame(self)
        card.setProperty("class", "Card")
        c_layout = QVBoxLayout(card)
        c_layout.setSpacing(12)

        # Detected hardware and what the app will use
        hw = hardware.detect()
        self.hw_note = QLabel(hw["note"], self)
        self.hw_note.setWordWrap(True)
        self.hw_note.setStyleSheet(f"color: {COLORS['text_secondary']};")
        c_layout.addWidget(self.hw_note)

        # Whisper model quality
        m_layout = QHBoxLayout()
        m_label = QLabel("Speech model:", self)
        m_label.setStyleSheet("font-weight: 500;")
        self.model_combo = QComboBox(self)
        for key, label in [
            ("auto", f"Automatic (recommended: {hw['model_size']})"),
            ("tiny", "Tiny: fastest, lowest accuracy (~39 MB)"),
            ("base", "Base: balanced (~74 MB)"),
            ("small", "Small: high accuracy (~244 MB)"),
            ("medium", "Medium: best accuracy, wants a GPU (~769 MB)"),
        ]:
            self.model_combo.addItem(label, key)
        curr_m = self.config.get("model_size", "auto").replace(".en", "")
        for i in range(self.model_combo.count()):
            if self.model_combo.itemData(i) == curr_m:
                self.model_combo.setCurrentIndex(i)
                break
        m_layout.addWidget(m_label)
        m_layout.addWidget(self.model_combo, 1)
        c_layout.addLayout(m_layout)

        # Compute hardware
        hw_layout = QHBoxLayout()
        hw_label = QLabel("Run on:", self)
        hw_label.setStyleSheet("font-weight: 500;")
        self.device_combo = QComboBox(self)
        self.device_combo.addItem("Automatic (recommended)", "auto")
        self.device_combo.addItem("GPU (NVIDIA CUDA)", "cuda")
        self.device_combo.addItem("CPU", "cpu")
        curr_d = self.config.get("device", "auto")
        for i in range(self.device_combo.count()):
            if self.device_combo.itemData(i) == curr_d:
                self.device_combo.setCurrentIndex(i)
        hw_layout.addWidget(hw_label)
        hw_layout.addWidget(self.device_combo, 1)
        c_layout.addLayout(hw_layout)

        # Microphone Input Device
        mic_layout = QHBoxLayout()
        mic_label = QLabel("Microphone:", self)
        mic_label.setStyleSheet("font-weight: 500;")
        self.mic_combo = QComboBox(self)
        self.mic_devices = list_microphones()
        self.mic_combo.addItem("Default System Microphone", None)
        curr_dev = self.config.get("input_device_index")
        for dev in self.mic_devices:
            self.mic_combo.addItem(f"{dev['name']} (Ch: {dev['channels']})", dev["index"])
            if curr_dev == dev["index"]:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        mic_layout.addWidget(mic_label)
        mic_layout.addWidget(self.mic_combo, 1)
        c_layout.addLayout(mic_layout)

        # Hotkey Configuration
        hk_layout = QHBoxLayout()
        hk_label = QLabel("Global Hotkey:", self)
        hk_label.setStyleSheet("font-weight: 500;")
        self.hotkey_input = QLineEdit(self)
        self.hotkey_input.setText(self.config.get("hotkey", "ctrl+shift"))
        self.hotkey_input.setPlaceholderText("e.g. ctrl+shift, f8, alt+space")
        hk_layout.addWidget(hk_label)
        hk_layout.addWidget(self.hotkey_input, 1)
        c_layout.addLayout(hk_layout)

        # Auto-Write Silence Duration
        sil_layout = QHBoxLayout()
        sil_label = QLabel("Auto-Write Pause Duration (sec):", self)
        sil_label.setStyleSheet("font-weight: 500;")
        self.silence_spin = QDoubleSpinBox(self)
        self.silence_spin.setRange(0.6, 3.5)
        self.silence_spin.setSingleStep(0.1)
        self.silence_spin.setValue(float(self.config.get("silence_duration", 1.1)))
        sil_layout.addWidget(sil_label)
        sil_layout.addWidget(self.silence_spin, 1)
        c_layout.addLayout(sil_layout)

        # Tone / Style Preset
        tone_layout = QHBoxLayout()
        tone_label = QLabel("Formatting Tone Preset:", self)
        tone_label.setStyleSheet("font-weight: 500;")
        self.tone_combo = QComboBox(self)
        self.tone_combo.addItem("Smart Clean (Removes fillers, natural sentences)", "smart_clean")
        self.tone_combo.addItem("Developer / Code (Variable casing, technical syntax)", "developer")
        self.tone_combo.addItem("Email & Professional (Structured greeting & signoff)", "email")
        self.tone_combo.addItem("Bullet Points (Thought outline)", "bullets")
        self.tone_combo.addItem("Raw Verbatim (No modification)", "verbatim")

        curr_tone = self.config.get("tone_preset", "smart_clean")
        for i in range(self.tone_combo.count()):
            if self.tone_combo.itemData(i) == curr_tone:
                self.tone_combo.setCurrentIndex(i)
                break
        tone_layout.addWidget(tone_label)
        tone_layout.addWidget(self.tone_combo, 1)
        c_layout.addLayout(tone_layout)

        # Real-time and Auto-write Checkboxes
        self.cb_autowrite = QCheckBox("Write automatically when you pause speaking", self)
        self.cb_autowrite.setChecked(self.config.get("auto_write_on_silence", True))
        c_layout.addWidget(self.cb_autowrite)

        self.cb_realtime = QCheckBox("Show live preview of words in the capsule", self)
        self.cb_realtime.setChecked(self.config.get("realtime_preview", True))
        c_layout.addWidget(self.cb_realtime)

        self.cb_sound = QCheckBox("Play sounds on start and finish", self)
        self.cb_sound.setChecked(self.config.get("sound_feedback", True))
        c_layout.addWidget(self.cb_sound)

        self.cb_restore_clip = QCheckBox("Restore previous clipboard after paste", self)
        self.cb_restore_clip.setChecked(self.config.get("restore_clipboard", True))
        c_layout.addWidget(self.cb_restore_clip)

        self.cb_autostart = QCheckBox("Start OpenFlow when I sign in", self)
        self.cb_autostart.setChecked(self.config.get("autostart", False))
        c_layout.addWidget(self.cb_autostart)

        # Save Button
        save_btn = QPushButton("Save Settings", self)
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save_settings)
        c_layout.addWidget(save_btn)

        # Updates Section
        up_sep = QFrame(self)
        up_sep.setFixedHeight(1)
        up_sep.setStyleSheet("background: rgba(255, 255, 255, 0.08); margin: 8px 0;")
        c_layout.addWidget(up_sep)

        up_layout = QHBoxLayout()
        up_layout.setSpacing(12)
        from .. import __version__
        self.ver_label = QLabel(f"Version: <b>v{__version__}</b>", self)
        self.ver_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        up_layout.addWidget(self.ver_label)

        self.update_status_label = QLabel("", self)
        self.update_status_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        up_layout.addWidget(self.update_status_label, 1)

        self.btn_check_update = QPushButton("Check for Updates", self)
        self.btn_check_update.clicked.connect(self._on_check_update_clicked)
        up_layout.addWidget(self.btn_check_update)

        self.btn_install_update = QPushButton("Download & Install", self)
        self.btn_install_update.setObjectName("PrimaryButton")
        self.btn_install_update.hide()
        self.btn_install_update.clicked.connect(lambda: self.sig_request_install_update.emit())
        up_layout.addWidget(self.btn_install_update)

        c_layout.addLayout(up_layout)

        layout.addWidget(card)
        layout.addStretch()
        return widget

    def _save_settings(self):
        model_choice = self.model_combo.currentData()
        # English-only fast variants are picked automatically per language at load time
        selected_model_text = model_choice
        device_choice = self.device_combo.currentData()
        compute_type = "auto" if device_choice == "auto" else ("float16" if device_choice == "cuda" else "int8")
        dev_idx = self.mic_combo.currentData()
        hotkey = self.hotkey_input.text().strip().lower() or "f8"
        tone_preset = self.tone_combo.currentData()

        self.config["model_size"] = selected_model_text
        self.config["device"] = device_choice
        self.config["compute_type"] = compute_type
        self.config["input_device_index"] = dev_idx
        self.config["hotkey"] = hotkey
        self.config["tone_preset"] = tone_preset
        self.config["silence_duration"] = float(self.silence_spin.value())
        self.config["auto_write_on_silence"] = self.cb_autowrite.isChecked()
        self.config["realtime_preview"] = self.cb_realtime.isChecked()
        self.config["sound_feedback"] = self.cb_sound.isChecked()
        self.config["restore_clipboard"] = self.cb_restore_clip.isChecked()
        self.config["autostart"] = self.cb_autostart.isChecked()

        save_config(self.config)
        self.config_changed.emit(self.config)
        QMessageBox.information(self, "Saved", "Settings updated.")

    def _create_stats_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        grid_layout = QHBoxLayout()
        self.card_dictations = self._make_metric_card("Total Dictations", "0", "#ffffff")
        self.card_words = self._make_metric_card("Total Words Spoken", "0", "#ffffff")
        self.card_saved = self._make_metric_card("Typing Time Saved", "0 hrs", "#ffffff")
        self.card_speed = self._make_metric_card("Effective Speed", "150 WPM", "#ffffff")

        grid_layout.addWidget(self.card_dictations)
        grid_layout.addWidget(self.card_words)
        grid_layout.addWidget(self.card_saved)
        grid_layout.addWidget(self.card_speed)
        layout.addLayout(grid_layout)

        comp_card = QFrame(self)
        comp_card.setProperty("class", "Card")
        comp_layout = QVBoxLayout(comp_card)
        comp_layout.setSpacing(10)

        comp_title = QLabel("Why OpenFlow", self)
        comp_title.setStyleSheet("font-size: 15px; font-weight: 500; color: #ffffff;")
        comp_layout.addWidget(comp_title)

        reasons = [
            ("No usage limits", "Runs 100% locally on your computer with your NVIDIA RTX 4050 GPU. No monthly minute quotas or tier limits."),
            ("Fully private", "Zero audio or clipboard data is sent over the internet. Everything stays strictly on your local disk."),
            ("Low latency", "Using faster-whisper CTranslate2 float16, dictation finishes in ~100-200 milliseconds."),
            ("Free", "No subscriptions, credit card prompts, or paywalls."),
        ]

        for title, detail in reasons:
            item_lbl = QLabel(f"<b>{title}</b>: {detail}", self)
            item_lbl.setStyleSheet(f"font-size: 12px; color: {COLORS['text_secondary']};")
            comp_layout.addWidget(item_lbl)

        layout.addWidget(comp_card)
        layout.addStretch()
        return widget

    def _make_metric_card(self, title: str, value: str, color: str) -> QFrame:
        card = QFrame(self)
        card.setProperty("class", "Card")
        c_layout = QVBoxLayout(card)
        c_layout.setContentsMargins(14, 14, 14, 14)
        c_layout.setSpacing(6)

        t_lbl = QLabel(title, card)
        t_lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; font-weight: 500;")

        v_lbl = QLabel(value, card)
        v_lbl.setObjectName("MetricValue")
        v_lbl.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: 500;")

        c_layout.addWidget(t_lbl)
        c_layout.addWidget(v_lbl)
        return card

    def refresh_stats(self):
        stats = self.db.get_stats()
        self.card_dictations.findChild(QLabel, "MetricValue").setText(str(stats["total_dictations"]))
        self.card_words.findChild(QLabel, "MetricValue").setText(f"{stats['total_words']:,}")
        self.card_saved.findChild(QLabel, "MetricValue").setText(f"{stats['time_saved_hours']} hrs")

    def _on_check_update_clicked(self):
        self.show_update_checking()
        self.sig_request_check_update.emit()

    def show_update_checking(self):
        self.update_status_label.setText("Checking for updates...")
        self.btn_check_update.setEnabled(False)

    def show_update_available(self, version: str, notes: str = ""):
        self.btn_check_update.setEnabled(True)
        self.update_status_label.setText(f"Update available: <b>v{version}</b>")
        self.btn_install_update.setText(f"Install v{version}")
        self.btn_install_update.show()

    def show_up_to_date(self, version: str = ""):
        self.btn_check_update.setEnabled(True)
        self.update_status_label.setText("OpenFlow is up to date.")
        self.btn_install_update.hide()

    def show_update_error(self, message: str):
        self.btn_check_update.setEnabled(True)
        self.update_status_label.setText(f"Update check: {message}")
