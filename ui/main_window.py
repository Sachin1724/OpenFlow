from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QComboBox, QFrame, QMessageBox, QAbstractItemView, QDoubleSpinBox, QProgressBar,
    QListWidget, QListWidgetItem, QTextBrowser, QSplitter, QFileDialog, QInputDialog, QSlider
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QUrl, QRectF, QPointF
from PyQt6.QtGui import QFont, QIcon, QColor, QPixmap, QDesktopServices, QPainter, QPen
import pyperclip  # type: ignore[import]
import importlib.util
import os
import re

try:
    from ..config import load_config, save_config, get_asset_path
    from ..database import Database
    from ..engine import hardware, model_manager
    from ..engine.audio_recorder import list_microphones
    from ..engine.meeting import render_meeting_html
    from .styles import main_qss, COLORS
    from .floating_pill import get_squircle_pixmap, Switch
except (ImportError, ValueError):
    from config import load_config, save_config, get_asset_path
    from database import Database
    from engine import hardware, model_manager
    from engine.audio_recorder import list_microphones
    from engine.meeting import render_meeting_html
    from ui.styles import main_qss, COLORS
    from ui.floating_pill import get_squircle_pixmap, Switch


# Windows virtual-key codes -> names GlobalHotkeyManager understands
_VK_NAMES = {0x10: "shift", 0xA0: "shift", 0xA1: "shift", 0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
             0x12: "alt", 0xA4: "alt", 0xA5: "alt", 0x20: "space"}
_MOD_ORDER = ("ctrl", "shift", "alt")


def vk_name(vk: int) -> str:
    """Win32 virtual key -> hotkey token ('' if unsupported)."""
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x70 <= vk <= 0x87:
        return f"f{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk).lower()
    return ""


def _is_fkey(k: str) -> bool:
    return k[:1] == "f" and k[1:].isdigit()


def combo_from_keys(keys) -> str:
    """Orders tokens ctrl+shift+alt+key; '' if the combo would hijack normal typing."""
    mods = [m for m in _MOD_ORDER if m in keys]
    rest = sorted(k for k in keys if k not in _MOD_ORDER)
    if not mods and not (len(rest) == 1 and _is_fkey(rest[0])):
        return ""  # a bare letter, digit or space would fire while typing
    return "+".join(mods + rest[:1])


def pretty_hotkey(combo: str):
    return [k.upper() if _is_fkey(k) else k.capitalize() for k in combo.split("+") if k]


class _ClearButton(QPushButton):
    """Round x button, painted so the dashboard's global QPushButton padding can't distort it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(22, 22)

    def paintEvent(self, a0):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 80 if self.isDown() else 56 if self.underMouse() else 34))
        side = min(self.width(), self.height())  # the global QSS min-height can make the widget taller
        cx, cy, d = self.width() / 2.0, self.height() / 2.0, 3.6
        p.drawEllipse(QPointF(cx, cy), side / 2.0, side / 2.0)
        p.setPen(QPen(QColor(255, 255, 255, 220), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - d, cy - d), QPointF(cx + d, cy + d))
        p.drawLine(QPointF(cx - d, cy + d), QPointF(cx + d, cy - d))


class HotkeyRecorder(QFrame):
    """Rounded key box: shows the shortcut as keycaps; x clears it and records the next key press."""
    sig_recording = pyqtSignal(bool)  # True while capturing; the global hotkey must pause
    sig_changed = pyqtSignal(str)

    def __init__(self, hotkey: str, parent=None):
        super().__init__(parent)
        self._hotkey = hotkey
        self._recording = False
        self._held, self._best = set(), set()
        self.setObjectName("HotkeyBox")
        self.setFixedHeight(40)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 8, 0)
        lay.setSpacing(6)
        self._caps = QHBoxLayout()
        self._caps.setSpacing(4)
        lay.addLayout(self._caps)
        self._hint = QLabel("", self)
        lay.addWidget(self._hint)
        lay.addStretch()
        self._btn = _ClearButton(self)
        self._btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._btn.setToolTip("Clear and record a new shortcut")
        self._btn.clicked.connect(self._on_btn)
        lay.addWidget(self._btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setStyleSheet("""
            QFrame#HotkeyBox { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10); border-radius: 10px; }
            QFrame#HotkeyBox[recording="true"] { border: 2px solid #0A84FF; background: rgba(10,132,255,0.08); }
        """)
        self._render(pretty_hotkey(hotkey))

    def hotkey(self) -> str:
        return self._hotkey

    def _render(self, caps, hint: str = "", error: bool = False):
        while self._caps.count():
            w = self._caps.takeAt(0).widget()
            if w:
                w.deleteLater()
        for c in caps:
            cap = QLabel(c, self)
            cap.setStyleSheet("background: rgba(255,255,255,0.14); color: #ffffff; border-radius: 6px; "
                              "border-bottom: 2px solid rgba(0,0,0,0.35); padding: 2px 8px; font-size: 12px; font-weight: 600;")
            self._caps.addWidget(cap, 0, Qt.AlignmentFlag.AlignVCenter)
        self._hint.setText(hint)
        self._hint.setStyleSheet(("color: #FF453A;" if error else "color: rgba(235,235,245,0.6);")
                                 + " font-size: 12px; background: transparent; border: none;")

    def _set_recording(self, on: bool):
        self._recording = on
        self.setProperty("recording", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        if on:
            self._held, self._best = set(), set()
            self.setFocus()
            self.grabKeyboard()
        else:
            self.releaseKeyboard()
        self.sig_recording.emit(on)

    def _on_btn(self):
        if self._recording:
            self._cancel()
        else:
            self._render([], "Press a shortcut…")
            self._set_recording(True)

    def mousePressEvent(self, a0):
        if not self._recording:
            self._on_btn()

    def _cancel(self):
        self._set_recording(False)
        self._render(pretty_hotkey(self._hotkey))

    def keyPressEvent(self, a0):
        if not self._recording:
            return super().keyPressEvent(a0)
        if a0.isAutoRepeat():
            return
        if a0.key() == Qt.Key.Key_Escape:
            return self._cancel()
        name = vk_name(a0.nativeVirtualKey())
        if name:
            self._held.add(name)
            if len(self._held) >= len(self._best):
                self._best = set(self._held)
            mods = [m for m in _MOD_ORDER if m in self._best]
            self._render(pretty_hotkey("+".join(mods + sorted(self._best - set(_MOD_ORDER)))))

    def keyReleaseEvent(self, a0):
        if not self._recording or a0.isAutoRepeat():
            return super().keyReleaseEvent(a0)
        self._held.discard(vk_name(a0.nativeVirtualKey()))
        if self._held or not self._best:
            return
        combo = combo_from_keys(self._best)  # commit once every key is up
        if not combo:
            self._best = set()
            self._render([], "Use Ctrl, Shift, Alt or an F-key", error=True)
            return
        self._hotkey = combo
        self._set_recording(False)
        self._render(pretty_hotkey(combo))
        self.sig_changed.emit(combo)

    def focusOutEvent(self, a0):
        if self._recording:
            self._cancel()
        super().focusOutEvent(a0)


class MainWindow(QMainWindow):
    config_changed = pyqtSignal(dict)
    sig_request_check_update = pyqtSignal()
    sig_request_install_update = pyqtSignal()
    sig_model_switch_requested = pyqtSignal(str)
    sig_model_download_requested = pyqtSignal(str)
    sig_model_delete_requested = pyqtSignal(str)
    sig_hotkey_recording = pyqtSignal(bool)
    sig_capsule_opacity = pyqtSignal(float)  # live while the slider moves

    def __init__(self, db: Database, config: dict):
        super().__init__()
        self.db = db
        self.config = config
        self._model_progress_bars = {}

        self.setWindowTitle("OpenFlow")
        self.setMinimumSize(880, 640)
        self.setStyleSheet(main_qss())

        icon_path = get_asset_path("app_icon_square.png")
        if not os.path.exists(icon_path):
            icon_path = get_asset_path("logo.jpg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._init_ui()
        self.refresh_history()
        self.refresh_dictionary()
        self.refresh_stats()
        self.refresh_models()

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
        icon_path = get_asset_path("app_icon_square.png")
        if not os.path.exists(icon_path):
            icon_path = get_asset_path("logo.jpg")
        if os.path.exists(icon_path):
            pix = QPixmap(icon_path).scaled(42, 42, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
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
        self.hotkey_badge_text = QLabel(self)
        self.hotkey_badge_text.setStyleSheet("color: #ffffff; font-size: 12px;")
        self._update_hotkey_badge()
        badge_layout.addWidget(self.hotkey_badge_text)
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
        self.tabs.addTab(self._create_meetings_tab(), "Meeting Notes")
        self.tabs.addTab(self._create_dictionary_tab(), "Vocabulary")
        self.tabs.addTab(self._create_models_tab(), "Model Library")
        self.tabs.addTab(self._create_settings_tab(), "Settings")
        self.tabs.addTab(self._create_stats_tab(), "Analytics")
        self.tabs.addTab(self._create_about_tab(), "About")

        main_layout.addWidget(self.tabs)

    def set_download(self, percent: int, model: str):
        """Shows or hides the download bar under the header and in the model card."""
        clean_name = model.replace(".en", "").lower()
        if hasattr(self, "_model_progress_bars"):
            for mid, bar in self._model_progress_bars.items():
                if mid in clean_name:
                    if percent < 100:
                        bar.show()
                        bar.setValue(percent)
                    else:
                        bar.setValue(100)
                        QTimer.singleShot(1500, bar.hide)

        if percent >= 100:
            self.dl_box.hide()
            self.refresh_models()
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

    def _create_meetings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        actions = QHBoxLayout()
        for label, slot in [("Rename Speaker", self._rename_speaker), ("Copy Markdown", self._copy_meeting),
                            ("Export to .md", self._export_meeting), ("Delete", self._delete_meeting),
                            ("Refresh", self.refresh_meetings)]:
            btn = QPushButton(label, self)
            btn.clicked.connect(slot)
            actions.addWidget(btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        self.meeting_list = QListWidget(self)
        self.meeting_list.currentItemChanged.connect(self._show_meeting)
        self.meeting_view = QTextBrowser(self)
        self.meeting_view.setOpenExternalLinks(True)
        split.addWidget(self.meeting_list)
        split.addWidget(self.meeting_view)
        split.setSizes([240, 560])
        layout.addWidget(split, 1)

        hint = QLabel("When a call is using your mic, the capsule offers to take notes.", self)
        hint.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        layout.addWidget(hint)
        self.refresh_meetings()
        return widget

    def refresh_meetings(self):
        self._meetings = {n["id"]: n for n in self.db.get_meeting_notes()}
        self.meeting_list.clear()
        for n in self._meetings.values():
            mins = int((n["duration_seconds"] or 0) // 60)
            item = QListWidgetItem(f"{n['title']}\n{n['timestamp'][:16].replace('T', ' ')} · {mins} min")
            item.setData(Qt.ItemDataRole.UserRole, n["id"])
            self.meeting_list.addItem(item)
        if self.meeting_list.count():
            self.meeting_list.setCurrentRow(0)
        else:
            self.meeting_view.setHtml("<div style='color:#64748b; padding:20px; font-family:sans-serif;'>No meeting notes yet.</div>")

    def _current_meeting(self):
        item = self.meeting_list.currentItem()
        return self._meetings.get(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _show_meeting(self, *_):
        n = self._current_meeting()
        if n:
            app_name = n.get("app_name", "Meeting")
            html = render_meeting_html(n["formatted_notes"], app_name)
            self.meeting_view.setHtml(html)

    def _rename_speaker(self):
        """Allow user to rename generic 'Person 1' or 'Person 2' to the speaker's real name across notes and transcript."""
        n = self._current_meeting()
        if not n:
            return
        notes = n["formatted_notes"]
        raw = n.get("raw_transcript", "")

        # Extract speakers present in notes
        found = set(re.findall(r"###\s*([^·\n]+)\s*·", notes))
        found.update(re.findall(r"\[\d+:\d+(?:\s*-\s*\d+:\d+)?\]\s*([^:]+):", raw))
        candidates = [s.strip() for s in found if s.strip() and "summary" not in s.lower()]
        if not candidates:
            candidates = ["Person 1", "Person 2", "You"]

        spk, ok = QInputDialog.getItem(self, "Rename Speaker", "Select speaker to rename:", sorted(candidates), 0, False)
        if not ok or not spk:
            return

        new_name, ok2 = QInputDialog.getText(self, "Rename Speaker", f"Enter real name for '{spk}':")
        if not ok2 or not new_name.strip():
            return
        new_name = new_name.strip()

        # Replace in notes and raw transcript
        updated_notes = re.sub(rf"\b{re.escape(spk)}\b", new_name, notes)
        updated_raw = re.sub(rf"\b{re.escape(spk)}\b", new_name, raw)
        self.db.update_meeting_note(n["id"], updated_raw, updated_notes)
        curr_id = n["id"]
        self.refresh_meetings()
        # Restore selection
        for i in range(self.meeting_list.count()):
            if self.meeting_list.item(i).data(Qt.ItemDataRole.UserRole) == curr_id:
                self.meeting_list.setCurrentRow(i)
                break

    def _copy_meeting(self):
        n = self._current_meeting()
        if n:
            pyperclip.copy(n["formatted_notes"])

    def _export_meeting(self):
        n = self._current_meeting()
        if not n:
            return
        name = "".join(c if c.isalnum() or c in " -_" else "_" for c in n["title"]).strip() + ".md"
        path, _ = QFileDialog.getSaveFileName(self, "Export meeting notes", name, "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(n["formatted_notes"])

    def _delete_meeting(self):
        n = self._current_meeting()
        if n and QMessageBox.question(self, "Delete notes", f"Delete \"{n['title']}\"?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                                      ) == QMessageBox.StandardButton.Yes:
            self.db.delete_meeting_note(n["id"])
            self.refresh_meetings()

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

        self.dict_case = Switch("Case sensitive", self)
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

    def refresh_devices(self):
        if not hasattr(self, "mic_combo"):
            return
        self.mic_combo.blockSignals(True)
        curr = self.config.get("input_device_index")
        recents = self.config.get("recent_mics", [])
        self.mic_combo.clear()
        self.mic_combo.addItem("Default System Microphone", None)
        self.mic_devices = list_microphones()
        for dev in self.mic_devices:
            is_active = (dev["index"] == curr)
            is_recent = dev["name"] in recents
            tag = " ● [Active]" if is_active else (" ↺ [Recent]" if is_recent else "")
            self.mic_combo.addItem(f"{dev['name']}{tag} (Ch: {dev['channels']})", dev["index"])
            if curr == dev["index"]:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        self.mic_combo.blockSignals(False)

    def _create_models_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Overview Banner Card
        top_card = QFrame(self)
        top_card.setProperty("class", "Card")
        top_lay = QVBoxLayout(top_card)
        top_lay.setContentsMargins(16, 14, 16, 14)
        top_lay.setSpacing(8)

        t_row = QHBoxLayout()
        self.lbl_active_model_title = QLabel("Speech & AI Model Library", self)
        self.lbl_active_model_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff;")
        t_row.addWidget(self.lbl_active_model_title)
        t_row.addStretch()

        self.btn_open_cache = QPushButton("Open Cache Folder", self)
        self.btn_open_cache.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_cache.clicked.connect(self._open_cache_folder)
        t_row.addWidget(self.btn_open_cache)

        self.btn_clean_temp = QPushButton("Clean Temporary Blobs", self)
        self.btn_clean_temp.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clean_temp.clicked.connect(self._clean_temp_blobs)
        t_row.addWidget(self.btn_clean_temp)

        top_lay.addLayout(t_row)

        hw = hardware.detect()
        curr_m = self.config.get("model_size", "base").replace(".en", "").title()
        self.lbl_model_status_info = QLabel(
            f"Active: <b>{curr_m}</b> · Running on: <b>{hw.get('device', 'cpu').upper()}</b> · "
            f"Speech models operate 100% locally on your machine with zero cloud roundtrips.",
            self
        )
        self.lbl_model_status_info.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        top_lay.addWidget(self.lbl_model_status_info)

        layout.addWidget(top_card)

        # Container for Model Cards
        self.models_container = QWidget(self)
        self.models_layout = QVBoxLayout(self.models_container)
        self.models_layout.setContentsMargins(0, 0, 0, 0)
        self.models_layout.setSpacing(10)
        layout.addWidget(self.models_container)
        layout.addStretch()

        return widget

    def refresh_models(self):
        if not hasattr(self, "models_layout"):
            return

        # Clear existing cards
        while self.models_layout.count():
            item = self.models_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        curr_model = self.config.get("model_size", "base").replace(".en", "").lower()
        models = model_manager.list_available_models(active_model=curr_model)

        hw = hardware.detect()
        curr_m_disp = self.config.get("model_size", "base").replace(".en", "").title()
        if hasattr(self, "lbl_model_status_info"):
            self.lbl_model_status_info.setText(
                f"Active: <b>{curr_m_disp}</b> · Running on: <b>{hw.get('device', 'cpu').upper()}</b> · "
                f"Speech models operate 100% locally on your machine with zero cloud roundtrips."
            )

        self._model_progress_bars = {}

        for m in models:
            m_id = m["id"]
            card = QFrame(self)
            card.setProperty("class", "Card")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(16, 12, 16, 12)
            c_lay.setSpacing(8)

            header = QHBoxLayout()
            name_lbl = QLabel(m["name"], card)
            name_lbl.setStyleSheet("font-size: 14px; font-weight: 600; color: #ffffff;")
            header.addWidget(name_lbl)

            if m.get("recommended"):
                rec_badge = QLabel("RECOMMENDED", card)
                rec_badge.setStyleSheet("background: rgba(255, 255, 255, 0.15); color: #ffffff; "
                                        "border-radius: 4px; padding: 2px 6px; font-size: 10px; font-weight: 700;")
                header.addWidget(rec_badge)

            header.addStretch()

            # Status Badge
            if m["is_active"]:
                badge = QLabel("ACTIVE · IN USE", card)
                badge.setStyleSheet("background: rgba(52, 199, 89, 0.18); color: #32d74b; "
                                    "border: 1px solid rgba(52, 199, 89, 0.40); border-radius: 6px; "
                                    "padding: 3px 8px; font-size: 11px; font-weight: 600;")
            elif m["is_downloaded"]:
                badge = QLabel(f"DOWNLOADED ({m['disk_size_str']})", card)
                badge.setStyleSheet("background: rgba(10, 132, 255, 0.18); color: #0a84ff; "
                                    "border: 1px solid rgba(10, 132, 255, 0.40); border-radius: 6px; "
                                    "padding: 3px 8px; font-size: 11px; font-weight: 600;")
            else:
                badge = QLabel(f"AVAILABLE ({m['expected_size_str']})", card)
                badge.setStyleSheet("background: rgba(255, 255, 255, 0.08); color: rgba(255, 255, 255, 0.45); "
                                    "border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 6px; "
                                    "padding: 3px 8px; font-size: 11px; font-weight: 500;")

            header.addWidget(badge)
            c_lay.addLayout(header)

            desc = QLabel(m["description"], card)
            desc.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
            c_lay.addWidget(desc)

            # Details & Actions Row
            act_row = QHBoxLayout()
            perf = QLabel(f"Speed: <b>{m['speed']}</b>  ·  Accuracy: <b>{m['accuracy']}</b>", card)
            perf.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
            act_row.addWidget(perf)
            act_row.addStretch()

            if m["is_active"]:
                btn_active = QPushButton("Currently Active", card)
                btn_active.setEnabled(False)
                act_row.addWidget(btn_active)
            elif m["is_downloaded"]:
                btn_use = QPushButton("Use This Model", card)
                btn_use.setObjectName("PrimaryButton")
                btn_use.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_use.clicked.connect(lambda ch, mid=m_id: self._on_switch_model(mid))
                act_row.addWidget(btn_use)

                btn_del = QPushButton("Delete Model", card)
                btn_del.setObjectName("DangerButton")
                btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_del.clicked.connect(lambda ch, mid=m_id, name=m['name']: self._on_delete_model(mid, name))
                act_row.addWidget(btn_del)
            else:
                btn_dl = QPushButton(f"Download ({m['expected_size_str']})", card)
                btn_dl.setObjectName("PrimaryButton")
                btn_dl.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_dl.clicked.connect(lambda ch, mid=m_id: self._on_download_model(mid))
                act_row.addWidget(btn_dl)

            c_lay.addLayout(act_row)

            # In-card progress bar (hidden by default)
            p_bar = QProgressBar(card)
            p_bar.setRange(0, 100)
            p_bar.setValue(0)
            p_bar.setFixedHeight(4)
            p_bar.setTextVisible(False)
            p_bar.setStyleSheet("QProgressBar { background: rgba(255,255,255,0.10); border: none; border-radius: 2px; }"
                                "QProgressBar::chunk { background: #55ff99; border-radius: 2px; }")
            p_bar.hide()
            c_lay.addWidget(p_bar)
            self._model_progress_bars[m_id] = p_bar

            self.models_layout.addWidget(card)

    def _open_cache_folder(self):
        import os
        cache_dir = os.path.expanduser("~/.cache/huggingface/hub")
        os.makedirs(cache_dir, exist_ok=True)
        try:
            os.startfile(cache_dir)
        except Exception:
            QMessageBox.information(self, "Cache Folder", f"Path: {cache_dir}")

    def _clean_temp_blobs(self):
        model_manager.clean_incomplete_downloads()
        self.refresh_models()
        QMessageBox.information(self, "Clean Complete", "Stale and incomplete download blobs have been removed.")

    def _on_switch_model(self, model_id: str):
        self.sig_model_switch_requested.emit(model_id)

    def _on_download_model(self, model_id: str):
        self.sig_model_download_requested.emit(model_id)

    def _on_delete_model(self, model_id: str, model_name: str):
        reply = QMessageBox.question(
            self,
            "Confirm Model Deletion",
            f"Are you sure you want to delete '{model_name}' from disk?\n\n"
            "This will free up disk space. You can re-download it anytime.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.sig_model_delete_requested.emit(model_id)

    def _create_settings_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(18, 16, 18, 20)
        layout.setSpacing(16)

        LABEL_W = 190

        def _make_card(title: str, subtitle: str) -> tuple[QFrame, QVBoxLayout]:
            card = QFrame(self)
            card.setStyleSheet("""
                QFrame.SettingsCard {
                    background: rgba(255, 255, 255, 0.035);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 12px;
                }
            """)
            card.setProperty("class", "SettingsCard")
            c_lay = QVBoxLayout(card)
            c_lay.setContentsMargins(18, 16, 18, 16)
            c_lay.setSpacing(12)

            t_lbl = QLabel(title, card)
            t_lbl.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #ffffff;")
            s_lbl = QLabel(subtitle, card)
            s_lbl.setStyleSheet("font-size: 11px; color: rgba(255, 255, 255, 0.48); margin-top: -6px;")
            c_lay.addWidget(t_lbl)
            c_lay.addWidget(s_lbl)

            sep = QFrame(card)
            sep.setFixedHeight(1)
            sep.setStyleSheet("background: rgba(255, 255, 255, 0.06); margin: 2px 0 6px 0;")
            c_lay.addWidget(sep)
            return card, c_lay

        def _make_row(label_text: str, ctrl_widget: QWidget) -> QHBoxLayout:
            r = QHBoxLayout()
            r.setSpacing(12)
            lbl = QLabel(label_text, widget)
            lbl.setFixedWidth(LABEL_W)
            lbl.setStyleSheet("font-weight: 500; font-size: 12.5px; color: rgba(255, 255, 255, 0.88);")
            lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            r.addWidget(lbl)
            r.addWidget(ctrl_widget, 1)
            return r

        # -------------------------------------------------------------------------
        # CARD 1: AI Speech Engine & Hardware Stack
        # -------------------------------------------------------------------------
        card1, c1_layout = _make_card(
            "⚡ AI Speech Engine & Hardware Stack",
            "Local speech-to-text inference models and neural acceleration"
        )
        hw = hardware.detect()
        self.hw_note = QLabel(hw["note"], card1)
        self.hw_note.setWordWrap(True)
        self.hw_note.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11.5px; margin-bottom: 4px;")
        c1_layout.addWidget(self.hw_note)

        # Speech model
        self.model_combo = QComboBox(card1)
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
        c1_layout.addLayout(_make_row("Speech model:", self.model_combo))

        # Compute device
        self.device_combo = QComboBox(card1)
        self.device_combo.addItem("Automatic (recommended)", "auto")
        if importlib.util.find_spec("openvino_genai"):
            self.device_combo.addItem("NPU (Intel AI Boost, low power)", "npu")
        self.device_combo.addItem("GPU (NVIDIA CUDA)", "cuda")
        self.device_combo.addItem("CPU", "cpu")
        curr_d = self.config.get("device", "auto")
        for i in range(self.device_combo.count()):
            if self.device_combo.itemData(i) == curr_d:
                self.device_combo.setCurrentIndex(i)
        c1_layout.addLayout(_make_row("Run on:", self.device_combo))

        # Hardware diagnostics container
        stack_hdr = QHBoxLayout()
        stack_title = QLabel("Hardware Diagnostics & Pipeline", card1)
        stack_title.setStyleSheet("font-weight: 500; font-size: 12px; color: rgba(255,255,255,0.7);")
        stack_hdr.addWidget(stack_title)
        stack_hdr.addStretch()

        self.btn_refresh_stack = QPushButton("Refresh Status", card1)
        self.btn_refresh_stack.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_refresh_stack.setStyleSheet("""
            QPushButton { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.85); border: 1px solid rgba(255,255,255,0.14); border-radius: 6px; padding: 3px 8px; font-size: 11px; }
            QPushButton:hover { background: rgba(255,255,255,0.14); }
        """)
        self.btn_refresh_stack.clicked.connect(self._refresh_system_stack)
        stack_hdr.addWidget(self.btn_refresh_stack)
        c1_layout.addLayout(stack_hdr)

        self.stack_box = QFrame(card1)
        self.stack_box.setStyleSheet("background: rgba(0, 0, 0, 0.25); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px;")
        self.stack_box_layout = QVBoxLayout(self.stack_box)
        self.stack_box_layout.setContentsMargins(12, 10, 12, 10)
        self.stack_box_layout.setSpacing(6)
        c1_layout.addWidget(self.stack_box)
        self._refresh_system_stack()

        layout.addWidget(card1)

        # -------------------------------------------------------------------------
        # CARD 2: Floating Capsule & Multi-Monitor Display
        # -------------------------------------------------------------------------
        card2, c2_layout = _make_card(
            "🪄 Floating Capsule & Multi-Monitor Display",
            "Desktop presence, sizing styles, and automatic screen following"
        )

        self.capsule_style_combo = QComboBox(card2)
        self.capsule_style_combo.addItem("Option A: Compact / Wispr Flow (148 px) — Minimal & Floating Speech Bubble", "compact")
        self.capsule_style_combo.addItem("Standard Capsule (360 px) — Full Controls & Action Hints", "standard")
        self.capsule_style_combo.addItem("Option C: Micro Capsule (88 px) — Ultra-Minimal Waveform Only", "micro")
        self.capsule_style_combo.addItem("Option D: Dynamic Island (top notch) — Springs open for dictation, alerts & settings", "island")

        curr_style = self.config.get("capsule_style", "compact")
        for i in range(self.capsule_style_combo.count()):
            if self.capsule_style_combo.itemData(i) == curr_style:
                self.capsule_style_combo.setCurrentIndex(i)
                break
        c2_layout.addLayout(_make_row("Capsule Style:", self.capsule_style_combo))

        self.island_pos_combo = QComboBox(card2)
        self.island_pos_combo.addItem("Top of the screen (tucks up when idle)", "top")
        self.island_pos_combo.addItem("Bottom of the screen", "bottom")
        self.island_pos_combo.setCurrentIndex(1 if self.config.get("island_position", "top") == "bottom" else 0)
        c2_layout.addLayout(_make_row("Island Position:", self.island_pos_combo))

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, card2)
        self.opacity_slider.setRange(30, 100)  # below 30% the capsule is easy to lose
        self.opacity_slider.setValue(round(float(self.config.get("capsule_opacity", 1.0)) * 100))
        self.opacity_label = QLabel(f"{self.opacity_slider.value()}%", card2)
        self.opacity_label.setFixedWidth(40)
        opacity_row = QHBoxLayout()
        opacity_row.addWidget(self.opacity_slider, 1)
        opacity_row.addWidget(self.opacity_label)
        opacity_box = QWidget(card2)
        opacity_box.setLayout(opacity_row)
        opacity_row.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_slider.sliderReleased.connect(lambda: save_config(self.config))
        c2_layout.addLayout(_make_row("Capsule Opacity:", opacity_box))

        self.cb_follow_mouse = Switch("Follow mouse cursor to active monitor with smooth fade (multi-screen)", card2)
        self.cb_follow_mouse.setChecked(self.config.get("follow_mouse_screen", True))
        c2_layout.addWidget(self.cb_follow_mouse)

        self.cb_realtime = Switch("Show live preview of words above capsule while dictating", card2)
        self.cb_realtime.setChecked(self.config.get("realtime_preview", True))
        c2_layout.addWidget(self.cb_realtime)

        self.cb_hide_idle = Switch("Hide capsule completely when idle (don't show snooze pill on desktop)", card2)
        self.cb_hide_idle.setChecked(self.config.get("hide_capsule_when_idle", False))
        c2_layout.addWidget(self.cb_hide_idle)

        layout.addWidget(card2)

        # -------------------------------------------------------------------------
        # CARD 3: Audio & Voice Capture
        # -------------------------------------------------------------------------
        card3, c3_layout = _make_card(
            "🎙️ Audio & Voice Capture",
            "Microphone hardware selection and automatic silence gating"
        )

        self.mic_combo = QComboBox(card3)
        self.mic_devices = list_microphones()
        self.mic_combo.addItem("Default System Microphone", None)
        curr_dev = self.config.get("input_device_index")
        for dev in self.mic_devices:
            self.mic_combo.addItem(f"{dev['name']} (Ch: {dev['channels']})", dev["index"])
            if curr_dev == dev["index"]:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        c3_layout.addLayout(_make_row("Microphone:", self.mic_combo))

        self.active_mic_lbl = QLabel("Active Input: Default System Microphone", card3)
        self.active_mic_lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11.5px; margin-top: -6px; margin-left: 4px;")
        c3_layout.addWidget(self.active_mic_lbl)

        self.silence_spin = QDoubleSpinBox(card3)
        self.silence_spin.setRange(0.6, 3.5)
        self.silence_spin.setSingleStep(0.1)
        self.silence_spin.setValue(float(self.config.get("silence_duration", 1.1)))
        c3_layout.addLayout(_make_row("Auto-Write Pause (sec):", self.silence_spin))

        self.cb_autowrite = Switch("Write automatically when you pause speaking", card3)
        self.cb_autowrite.setChecked(self.config.get("auto_write_on_silence", True))
        c3_layout.addWidget(self.cb_autowrite)

        self.cb_sound = Switch("Play audio feedback tones on start and finish", card3)
        self.cb_sound.setChecked(self.config.get("sound_feedback", True))
        c3_layout.addWidget(self.cb_sound)

        self.cb_voice_edits = Switch("Voice edits: select text and say \"make this formal\" (downloads a 1.5 GB writing model once)", card3)
        self.cb_voice_edits.setChecked(self.config.get("voice_edits", False))
        c3_layout.addWidget(self.cb_voice_edits)

        layout.addWidget(card3)

        # -------------------------------------------------------------------------
        # CARD 4: Shortcuts, Text Output & System
        # -------------------------------------------------------------------------
        card4, c4_layout = _make_card(
            "⌨️ Shortcuts, Text Output & System",
            "Global activation hotkey, text injection, and application behavior"
        )

        self.hotkey_input = HotkeyRecorder(self.config.get("hotkey", "ctrl+shift"), card4)
        self.hotkey_input.sig_recording.connect(self.sig_hotkey_recording.emit)
        self.hotkey_input.sig_changed.connect(self._on_hotkey_recorded)
        c4_layout.addLayout(_make_row("Global Hotkey:", self.hotkey_input))

        self.inj_combo = QComboBox(card4)
        self.inj_combo.addItem("Instant Paste (Clipboard - Fastest)", "clipboard")
        self.inj_combo.addItem("Type-In Effect (Word by Word - No Clipboard)", "typein")
        self.inj_combo.addItem("Direct Typewriter (Unicode Emulation - No Clipboard)", "type")
        curr_inj = self.config.get("injection_method", "clipboard")
        for i in range(self.inj_combo.count()):
            if self.inj_combo.itemData(i) == curr_inj:
                self.inj_combo.setCurrentIndex(i)
                break
        c4_layout.addLayout(_make_row("Writing Method:", self.inj_combo))

        self.tone_combo = QComboBox(card4)
        self.tone_combo.addItem("Auto (Matches the app you are typing in)", "auto")
        self.tone_combo.addItem("Smart Clean (Removes fillers, natural sentences)", "smart_clean")
        self.tone_combo.addItem("Developer / Code (Variable casing, technical syntax)", "developer")
        self.tone_combo.addItem("Email & Professional (Structured greeting & signoff)", "email")
        self.tone_combo.addItem("Bullet Points (Thought outline)", "bullets")
        self.tone_combo.addItem("Raw Verbatim (No modification)", "verbatim")
        curr_tone = self.config.get("tone_preset", "auto")
        for i in range(self.tone_combo.count()):
            if self.tone_combo.itemData(i) == curr_tone:
                self.tone_combo.setCurrentIndex(i)
                break
        c4_layout.addLayout(_make_row("Formatting Preset:", self.tone_combo))

        self.cb_restore_clip = Switch("Restore previous clipboard after paste", card4)
        self.cb_restore_clip.setChecked(self.config.get("restore_clipboard", True))
        c4_layout.addWidget(self.cb_restore_clip)

        self.cb_autostart = Switch("Start OpenFlow automatically when I sign in", card4)
        self.cb_autostart.setChecked(self.config.get("autostart", False))
        c4_layout.addWidget(self.cb_autostart)

        # Save Button
        save_btn = QPushButton("Save Settings", card4)
        save_btn.setObjectName("PrimaryButton")
        save_btn.setFixedHeight(38)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_settings)
        c4_layout.addWidget(save_btn)

        # Updates Section
        up_sep = QFrame(card4)
        up_sep.setFixedHeight(1)
        up_sep.setStyleSheet("background: rgba(255, 255, 255, 0.08); margin: 6px 0;")
        c4_layout.addWidget(up_sep)

        up_layout = QHBoxLayout()
        up_layout.setSpacing(12)
        try:
            from .. import __version__
        except (ImportError, ValueError):
            from __init__ import __version__
        self.ver_label = QLabel(f"Version: <b>v{__version__}</b>", card4)
        self.ver_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px;")
        up_layout.addWidget(self.ver_label)

        self.update_status_label = QLabel("", card4)
        self.update_status_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        up_layout.addWidget(self.update_status_label, 1)

        self.btn_check_update = QPushButton("Check for Updates", card4)
        self.btn_check_update.clicked.connect(self._on_check_update_clicked)
        up_layout.addWidget(self.btn_check_update)

        self.btn_install_update = QPushButton("Download & Install", card4)
        self.btn_install_update.setObjectName("PrimaryButton")
        self.btn_install_update.hide()
        self.btn_install_update.clicked.connect(lambda: self.sig_request_install_update.emit())
        up_layout.addWidget(self.btn_install_update)

        c4_layout.addLayout(up_layout)

        layout.addWidget(card4)
        layout.addStretch()

        # the tab is taller than the minimum window; let it scroll instead of clipping
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                             "QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(widget)
        return scroll

    def _refresh_system_stack(self):
        while self.stack_box_layout.count():
            item = self.stack_box_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                sub_layout = item.layout()
                while sub_layout.count():
                    sub_item = sub_layout.takeAt(0)
                    if sub_item.widget():
                        sub_item.widget().deleteLater()

        stack = hardware.get_system_stack(self.config)

        # Active Pipeline Badge Row
        pipe_row = QHBoxLayout()
        lbl_pipe_title = QLabel("Active Engine:", self.stack_box)
        lbl_pipe_title.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.6);")
        pipe_row.addWidget(lbl_pipe_title)

        pipe_badge = QLabel(f" {stack['pipeline']} ", self.stack_box)
        pipe_badge.setStyleSheet("background: rgba(48, 209, 88, 0.16); color: #30D158; border: 1px solid rgba(48, 209, 88, 0.35); border-radius: 4px; font-weight: 600; font-size: 11px; padding: 2px 6px;")
        pipe_row.addWidget(pipe_badge)
        pipe_row.addStretch()
        self.stack_box_layout.addLayout(pipe_row)

        # GPU Line
        gpu = stack["gpu"]
        gpu_color = "#30D158" if gpu["is_active"] else ("#0A84FF" if gpu["cuda_available"] else "rgba(255,255,255,0.4)")
        lbl_gpu = QLabel(f"• <b>GPU Acceleration:</b> {gpu['name']} ({gpu['vram_gb']} GB VRAM) — <span style='color:{gpu_color}; font-weight:600;'>{gpu['status']}</span> [{gpu['backend']}]", self.stack_box)
        lbl_gpu.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.85);")
        self.stack_box_layout.addWidget(lbl_gpu)

        # NPU Line
        npu = stack["npu"]
        npu_color = "#30D158" if npu["is_active"] else ("#0A84FF" if npu["detected"] else "rgba(255,255,255,0.4)")
        lbl_npu = QLabel(f"• <b>NPU Neural Core:</b> {npu['name']} — <span style='color:{npu_color}; font-weight:600;'>{npu['status']}</span> [{npu['acceleration']}]", self.stack_box)
        lbl_npu.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.85);")
        self.stack_box_layout.addWidget(lbl_npu)

        # CPU Line
        cpu = stack["cpu"]
        cpu_color = "#30D158" if cpu["is_active"] else "rgba(255,255,255,0.5)"
        lbl_cpu = QLabel(f"• <b>CPU Host:</b> {cpu['processor']} ({cpu['cores']} Cores, {cpu['ram_gb']} GB RAM) — <span style='color:{cpu_color}; font-weight:600;'>{cpu['status']}</span>", self.stack_box)
        lbl_cpu.setStyleSheet("font-size: 11px; color: rgba(255,255,255,0.85);")
        self.stack_box_layout.addWidget(lbl_cpu)

    def _save_settings(self):
        model_choice = self.model_combo.currentData()
        # English-only fast variants are picked automatically per language at load time
        selected_model_text = model_choice
        device_choice = self.device_combo.currentData()
        if device_choice == "npu" and not hardware.npu_name():
            QMessageBox.warning(self, "No NPU found",
                                "This PC has no Intel NPU that OpenFlow can use. It will keep running on the GPU or CPU.")
        compute_type = "auto" if device_choice == "auto" else ("float16" if device_choice == "cuda" else "int8")
        dev_idx = self.mic_combo.currentData()
        hotkey = self.hotkey_input.hotkey() or "ctrl+shift"
        tone_preset = self.tone_combo.currentData()

        self.config["model_size"] = selected_model_text
        self.config["device"] = device_choice
        self.config["compute_type"] = compute_type
        if hasattr(self, "capsule_style_combo"):
            self.config["capsule_style"] = self.capsule_style_combo.currentData()
        if hasattr(self, "island_pos_combo"):
            self.config["island_position"] = self.island_pos_combo.currentData()
        self.config["input_device_index"] = dev_idx
        self.config["injection_method"] = self.inj_combo.currentData()
        self.config["hotkey"] = hotkey
        self.config["tone_preset"] = tone_preset
        self.config["silence_duration"] = float(self.silence_spin.value())
        self.config["auto_write_on_silence"] = self.cb_autowrite.isChecked()
        self.config["realtime_preview"] = self.cb_realtime.isChecked()
        self.config["hide_capsule_when_idle"] = self.cb_hide_idle.isChecked()
        if hasattr(self, "cb_follow_mouse"):
            self.config["follow_mouse_screen"] = self.cb_follow_mouse.isChecked()
        self.config["sound_feedback"] = self.cb_sound.isChecked()
        self.config["voice_edits"] = self.cb_voice_edits.isChecked()
        self.config["restore_clipboard"] = self.cb_restore_clip.isChecked()
        self.config["autostart"] = self.cb_autostart.isChecked()

        save_config(self.config)
        self.config_changed.emit(self.config)
        self._refresh_system_stack()
        QMessageBox.information(self, "Saved", "Settings updated.")

    def _on_opacity_changed(self, value: int):
        """Applies at once, like the hotkey; no Save needed."""
        self.opacity_label.setText(f"{value}%")
        self.config["capsule_opacity"] = value / 100
        self.sig_capsule_opacity.emit(value / 100)
        if not self.opacity_slider.isSliderDown():  # keyboard / wheel changes have no release
            save_config(self.config)

    def _update_hotkey_badge(self):
        keys = " + ".join(pretty_hotkey(self.config.get("hotkey", "ctrl+shift")))
        self.hotkey_badge_text.setText(f"Hold <b>{keys}</b> to speak")

    def _on_hotkey_recorded(self, combo: str):
        """A recorded shortcut applies at once; no Save needed."""
        self.config["hotkey"] = combo
        save_config(self.config)
        self._update_hotkey_badge()
        self.config_changed.emit(self.config)

    def update_hide_capsule_idle_state(self, hide: bool):
        if hasattr(self, "cb_hide_idle"):
            self.cb_hide_idle.blockSignals(True)
            self.cb_hide_idle.setChecked(hide)
            self.cb_hide_idle.blockSignals(False)

    def refresh_devices(self, active_mic_name: str = ""):
        """Dynamically re-populates the microphone dropdown upon hotplug events."""
        if not hasattr(self, "mic_combo"):
            return
        self.mic_devices = list_microphones()
        self.mic_combo.blockSignals(True)
        self.mic_combo.clear()

        def_title = f"Default System Microphone (Active: {active_mic_name})" if active_mic_name else "Default System Microphone"
        self.mic_combo.addItem(def_title, None)
        curr_dev = self.config.get("input_device_index")

        for dev in self.mic_devices:
            is_active = (active_mic_name and dev["name"] == active_mic_name)
            tag = " [ACTIVE]" if is_active else ""
            self.mic_combo.addItem(f"{dev['name']}{tag} (Ch: {dev['channels']})", dev["index"])
            if curr_dev == dev["index"]:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        self.mic_combo.blockSignals(False)

        if hasattr(self, "active_mic_lbl") and active_mic_name:
            self.active_mic_lbl.setText(f"Active Input: {active_mic_name}")

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

        hw_info = hardware.detect()
        gpu_label = hw_info.get("gpu_name") or ("NVIDIA GPU" if hw_info.get("cuda_ok") else "CPU / Local Hardware")
        reasons = [
            ("No usage limits", f"Runs 100% locally on your computer with your {gpu_label}. No monthly minute quotas or tier limits."),
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

    def _create_about_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        # Header card
        header_card = QFrame(self)
        header_card.setProperty("class", "Card")
        h_layout = QHBoxLayout(header_card)
        h_layout.setContentsMargins(18, 18, 18, 18)
        h_layout.setSpacing(16)

        logo_path = get_asset_path("app_icon_square.png")
        if not os.path.exists(logo_path):
            logo_path = get_asset_path("logo.jpg")
        logo_label = QLabel(header_card)
        if os.path.exists(logo_path):
            logo_label.setPixmap(get_squircle_pixmap(logo_path, size=52, radius=12.0))
        h_layout.addWidget(logo_label)

        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        try:
            from .. import __version__
        except (ImportError, ValueError):
            from __init__ import __version__
        app_title = QLabel(f"OpenFlow <span style='font-size: 13px; color: #55ff99; font-weight: normal;'>v{__version__}</span>", header_card)
        app_title.setStyleSheet("font-size: 20px; font-weight: 600; color: #ffffff;")
        app_sub = QLabel("Private, unlimited voice dictation & speech-to-writing system · 100% On-Device AI", header_card)
        app_sub.setStyleSheet(f"font-size: 13px; color: {COLORS['text_secondary']};")
        title_col.addWidget(app_title)
        title_col.addWidget(app_sub)
        h_layout.addLayout(title_col, 1)

        layout.addWidget(header_card)

        # Developer & Contact Card
        dev_card = QFrame(self)
        dev_card.setProperty("class", "Card")
        d_layout = QVBoxLayout(dev_card)
        d_layout.setContentsMargins(18, 18, 18, 18)
        d_layout.setSpacing(12)

        dev_title = QLabel("Developer & Contact", dev_card)
        dev_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff;")
        d_layout.addWidget(dev_title)

        dev_desc = QLabel(
            "Developed with passion by <b>Sachidananda</b>.<br>"
            "OpenFlow is designed as a genuine, 100% private and offline alternative to cloud speech tools like Wispr Flow. "
            "Dictate naturally into any application with zero cloud latency and no subscriptions.",
            dev_card
        )
        dev_desc.setStyleSheet(f"font-size: 13px; color: {COLORS['text_secondary']}; line-height: 1.5;")
        dev_desc.setWordWrap(True)
        d_layout.addWidget(dev_desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_gh = QPushButton("GitHub Repository", dev_card)
        btn_gh.setObjectName("SecondaryButton")
        btn_gh.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_gh.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/Sachin1724/OpenFlow")))
        btn_row.addWidget(btn_gh)

        btn_web = QPushButton("Project Website", dev_card)
        btn_web.setObjectName("SecondaryButton")
        btn_web.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_web.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://sachin1724.github.io/OpenFlow/")))
        btn_row.addWidget(btn_web)

        btn_mail = QPushButton("Contact / Report Issue", dev_card)
        btn_mail.setObjectName("PrimaryButton")
        btn_mail.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_mail.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("mailto:fakesachin.19@gmail.com?subject=OpenFlow%20Feedback%20%2F%20Issue%20Report")))
        btn_row.addWidget(btn_mail)

        btn_row.addStretch()
        d_layout.addLayout(btn_row)
        layout.addWidget(dev_card)

        # Privacy Policy & Local Guarantee Card
        priv_card = QFrame(self)
        priv_card.setProperty("class", "Card")
        p_layout = QVBoxLayout(priv_card)
        p_layout.setContentsMargins(18, 18, 18, 18)
        p_layout.setSpacing(10)

        priv_title = QLabel("Privacy Policy & Local Security Guarantee", priv_card)
        priv_title.setStyleSheet("font-size: 15px; font-weight: 600; color: #ffffff;")
        p_layout.addWidget(priv_title)

        guarantees = [
            ("100% On-Device Transcription", "Every word is processed locally in RAM/VRAM via Whisper & CTranslate2. Zero audio bytes ever leave your device."),
            ("Zero Cloud Telemetry", "OpenFlow contains no cloud tracking, analytics, or external API dependencies."),
            ("Local SQLite Database", "Your transcription history and custom vocabulary reside strictly on your PC in %USERPROFILE%\\.openflow\\openflow.db."),
            ("Complete User Control", "Delete downloaded models, purge vocabulary, or clear your history at any time with a single click.")
        ]
        for g_title, g_desc in guarantees:
            lbl = QLabel(f"<b>{g_title}</b> — {g_desc}", priv_card)
            lbl.setStyleSheet(f"font-size: 12px; color: {COLORS['text_secondary']};")
            lbl.setWordWrap(True)
            p_layout.addWidget(lbl)

        layout.addWidget(priv_card)
        layout.addStretch()
        return widget
