from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QStackedWidget, QScrollArea, QButtonGroup,
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
    from .floating_pill import Switch
except (ImportError, ValueError):
    from config import load_config, save_config, get_asset_path
    from database import Database
    from engine import hardware, model_manager
    from engine.audio_recorder import list_microphones
    from engine.meeting import render_meeting_html
    from ui.styles import main_qss, COLORS
    from ui.floating_pill import Switch


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
            QFrame#HotkeyBox { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.10); border-radius: 8px; }
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


def _no_wheel(cls):
    """Control that only takes the mouse wheel once focused, so scrolling a page never edits a value."""
    class Guarded(cls):
        def __init__(self, *a):
            super().__init__(*a)
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        def wheelEvent(self, e):
            super().wheelEvent(e) if self.hasFocus() else e.ignore()  # ignored: the page scrolls instead
    return Guarded


NoWheelCombo, NoWheelSlider, NoWheelSpin = _no_wheel(QComboBox), _no_wheel(QSlider), _no_wheel(QDoubleSpinBox)


class Group(QFrame):
    """Inset-grouped list: rounded block of rows with hairline separators."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Group")
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(0)
        self._n = 0

    def _sep(self):
        if self._n:
            inset = QWidget(self)
            lay = QHBoxLayout(inset)
            lay.setContentsMargins(16, 0, 0, 0)
            line = QFrame(inset)
            line.setObjectName("Sep")
            lay.addWidget(line)
            self._v.addWidget(inset)
        self._n += 1

    def add(self, label: str = "", control: QWidget = None, sub: str = ""):
        """Row: label (and optional secondary text) left, control right. Returns the sub-label."""
        self._sep()
        row = QWidget(self)
        row.setMinimumHeight(44)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(2)
        if label:
            lbl = QLabel(label, row)
            lbl.setObjectName("RowLabel")
            lbl.setWordWrap(True)
            text.addWidget(lbl)
        sub_lbl = QLabel(sub, row)
        sub_lbl.setObjectName("RowSub")
        sub_lbl.setWordWrap(True)
        sub_lbl.setVisible(bool(sub))
        text.addWidget(sub_lbl)
        lay.addLayout(text, 1)
        if control is not None:
            lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self._v.addWidget(row)
        return sub_lbl

    def add_widget(self, w: QWidget):
        self._sep()
        self._v.addWidget(w)

    def clear(self):
        while self._v.count():
            w = self._v.takeAt(0).widget()
            if w:
                w.deleteLater()
        self._n = 0


def _btn(text: str, kind: str = "", small: bool = False, slot=None) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        b.setObjectName({"primary": "PrimaryButton", "danger": "DangerButton"}[kind])
    if small:
        b.setProperty("small", "true")
    if slot:
        b.clicked.connect(slot)
    return b


def _logo_label(height: int, parent=None):
    """The bare logo mark (transparent PNG): no tile, no border. None if the asset is missing."""
    path = get_asset_path("logo_mark.png")
    if not os.path.exists(path):
        return None
    ratio = 2.0  # sharp on high-DPI screens
    pm = QPixmap(path).scaledToHeight(round(height * ratio), Qt.TransformationMode.SmoothTransformation)
    pm.setDevicePixelRatio(ratio)
    lbl = QLabel(parent)
    lbl.setPixmap(pm)
    return lbl


def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def _badge(text: str, kind: str = "") -> QLabel:
    b = QLabel(text)
    b.setProperty("badge", kind or "plain")
    return b


def _panel(*widgets) -> QFrame:
    """Plain rounded block for a table or list."""
    f = QFrame()
    f.setObjectName("Group")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    for w in widgets:
        lay.addWidget(w)
    return f


def _style_table(t: QTableWidget):
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(40)
    t.setShowGrid(False)
    t.setWordWrap(False)
    t.setTextElideMode(Qt.TextElideMode.ElideRight)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    t.horizontalHeader().setHighlightSections(False)
    t.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)


NAV = [("Dictate", [("History", 0), ("Meeting Notes", 1), ("Vocabulary", 2)]),
       ("Library", [("Model Library", 3)]), ("Preferences", [("Settings", 4)]), ("Insights", [("Analytics", 5)])]
COL_W = 760  # content column; wider windows keep it readable instead of stretching rows


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
        self.setMinimumSize(760, 560)
        self.resize(1000, 720)
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

    # -- shell: sidebar + pages ---------------------------------------------

    def _init_ui(self):
        central = QWidget(self)
        central.setObjectName("Content")
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.stack = QStackedWidget(self)
        for page in (self._create_history_tab(), self._create_meetings_tab(), self._create_dictionary_tab(),
                     self._create_models_tab(), self._create_settings_tab(), self._create_stats_tab(),
                     self._create_about_tab()):
            self.stack.addWidget(page)
        outer.addWidget(self._build_sidebar())

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        # Model download progress (hidden unless a model is downloading)
        self.dl_box = QWidget(self)
        dl_lay = QHBoxLayout(self.dl_box)
        dl_lay.setContentsMargins(28, 12, 28, 0)
        dl_lay.setSpacing(12)
        self.dl_label = QLabel("", self)
        self.dl_label.setObjectName("PageSub")
        self.dl_bar = QProgressBar(self)
        self.dl_bar.setRange(0, 100)
        self.dl_bar.setTextVisible(False)
        dl_lay.addWidget(self.dl_label)
        dl_lay.addWidget(self.dl_bar, 1)
        self.dl_box.hide()
        right.addWidget(self.dl_box)
        right.addWidget(self.stack, 1)
        outer.addLayout(right, 1)
        self.select_page(0)

    def _build_sidebar(self) -> QFrame:
        bar = QFrame(self)
        bar.setObjectName("Sidebar")
        bar.setFixedWidth(200)
        v = QVBoxLayout(bar)
        v.setContentsMargins(12, 20, 12, 12)
        v.setSpacing(2)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 6, 8)
        brand.setSpacing(10)
        logo = _logo_label(18, bar)
        if logo:
            brand.addWidget(logo)
        brand.addWidget(_label("OpenFlow", "AppName"))
        brand.addStretch()
        v.addLayout(brand)

        self._nav_group = QButtonGroup(self)
        self._nav_btns = {}

        def nav(text, idx):
            b = QPushButton(text, bar)
            b.setProperty("nav", "true")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, i=idx: self.select_page(i))
            self._nav_group.addButton(b)
            self._nav_btns[idx] = b
            v.addWidget(b)

        for caption, items in NAV:
            v.addWidget(_label(caption.upper(), "NavCaption"))
            for text, idx in items:
                nav(text, idx)
        v.addStretch()
        nav("About", 6)
        self.hotkey_badge_text = _label("", "HotkeyHint")
        self._update_hotkey_badge()
        v.addWidget(self.hotkey_badge_text)
        return bar

    def select_page(self, i: int):
        self.stack.setCurrentIndex(i)
        self._nav_btns[i].setChecked(True)
        self.stack.currentWidget().setFocus()

    def _page(self, title: str, sub: str = "", actions=(), scroll: bool = True):
        """Page = fixed title row + (scrolling) body. Returns (root, body layout, subtitle label)."""
        root = QWidget()
        root.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # takes focus on page change, so no field starts with a ring
        v = QVBoxLayout(root)
        v.setContentsMargins(28, 28, 28, 0 if scroll else 24)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.setContentsMargins(0, 0, 14 if scroll else 0, 0)  # scrollbar track width, so edges line up
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(_label(title, "PageTitle"))
        sub_lbl = _label(sub, "PageSub", wrap=True)
        sub_lbl.setVisible(bool(sub))
        col.addWidget(sub_lbl)
        head.addLayout(col, 1)
        for a in actions:
            head.addWidget(a, 0, Qt.AlignmentFlag.AlignTop)
        v.addLayout(head)
        v.addSpacing(16)
        if not scroll:
            return root, v, sub_lbl
        area = QScrollArea(root)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        inner = QWidget()
        inner.setMaximumWidth(COL_W)
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 0, 32)
        body.setSpacing(24)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)
        area.setWidget(inner)
        v.addWidget(area, 1)
        return root, body, sub_lbl

    def _section(self, body, header: str = "", footer: str = "", action: QWidget = None):
        """Header + Group + footer note. Returns (group, footer label)."""
        box = QVBoxLayout()
        box.setSpacing(6)
        if header or action:
            row = QHBoxLayout()
            row.addWidget(_label(header.upper(), "SectionHeader"))
            row.addStretch()
            if action:
                row.addWidget(action)
            box.addLayout(row)
        g = Group()
        box.addWidget(g)
        foot = _label(footer, "SectionFooter", wrap=True)
        foot.setVisible(bool(footer))
        box.addWidget(foot)
        body.addLayout(box)
        return g, foot

    # -- history ------------------------------------------------------------

    def _create_history_tab(self) -> QWidget:
        root, body, _ = self._page("History", "Everything you have dictated, newest first.", scroll=False)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.history_search = QLineEdit(self)
        self.history_search.setPlaceholderText("Search history")
        self.history_search.setClearButtonEnabled(True)
        self.history_search.textChanged.connect(self.refresh_history)
        bar.addWidget(self.history_search, 1)
        bar.addWidget(_btn("Refresh", small=True, slot=self.refresh_history))
        bar.addWidget(_btn("Clear All", "danger", small=True, slot=self._clear_history))
        body.addLayout(bar)
        body.addSpacing(12)

        self.history_table = QTableWidget(0, 5, self)
        self.history_table.setHorizontalHeaderLabels(["Time", "App", "Words", "Speed", "Text"])
        hh = self.history_table.horizontalHeader()
        for c, w in enumerate((106, 100, 68, 84)):  # fixed so the text column keeps the rest of the width
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Fixed)
            hh.resizeSection(c, w)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        _style_table(self.history_table)
        self.history_table.cellDoubleClicked.connect(self._copy_history_row)
        self.history_empty = _label("", "Empty")
        self.history_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(_panel(self.history_table, self.history_empty), 1)
        body.addSpacing(8)
        body.addWidget(_label("Double-click a row to copy its text.", "SectionFooter"))
        return root

    def refresh_history(self):
        query = self.history_search.text().strip() if hasattr(self, "history_search") else ""
        rows = self.db.get_history(limit=150, query=query)
        self.history_table.setRowCount(len(rows))
        self.history_table.setVisible(bool(rows))
        self.history_empty.setVisible(not rows)
        self.history_empty.setText("No matches." if query else "Nothing dictated yet.\nHold your hotkey in any app and start talking.")

        for idx, row in enumerate(rows):
            ts = row["timestamp"][5:16].replace("T", " ")
            app = row["target_app"] or "Desktop"
            words = str(row["word_count"] or len(row["formatted_text"].split()))
            latency = f"{row['latency_ms']} ms" if row["latency_ms"] else "-"
            text = row["formatted_text"]
            for col, val in enumerate((ts, app, words, latency, text)):
                item = QTableWidgetItem(val)
                if col == 4:
                    item.setToolTip(text)
                self.history_table.setItem(idx, col, item)

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

    # -- meeting notes ------------------------------------------------------

    def _create_meetings_tab(self) -> QWidget:
        root, body, _ = self._page("Meeting Notes", "Captions and notes from calls and anything your speakers play.", scroll=False)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        for label, slot in [("Rename Speaker", self._rename_speaker), ("Copy Markdown", self._copy_meeting),
                            ("Export .md", self._export_meeting), ("Refresh", self.refresh_meetings)]:
            bar.addWidget(_btn(label, small=True, slot=slot))
        bar.addStretch(1)
        bar.addWidget(_btn("Delete", "danger", small=True, slot=self._delete_meeting))
        body.addLayout(bar)
        body.addSpacing(12)

        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)
        self.meeting_list = QListWidget(self)
        self.meeting_list.setMinimumWidth(190)
        self.meeting_list.currentItemChanged.connect(self._show_meeting)
        self.meeting_view = QTextBrowser(self)
        self.meeting_view.setOpenExternalLinks(True)
        split.addWidget(self.meeting_list)
        split.addWidget(self.meeting_view)
        split.setSizes([220, 460])
        self.meeting_empty = _label("No meeting notes yet.\nStart one from the capsule menu or when a call uses your microphone.", "Empty")
        self.meeting_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.meeting_split = split
        body.addWidget(_panel(split, self.meeting_empty), 1)
        body.addSpacing(8)
        body.addWidget(_label("When a call is using your mic, the capsule offers to take notes.", "SectionFooter"))
        self.refresh_meetings()
        return root

    def refresh_meetings(self):
        self._meetings = {n["id"]: n for n in self.db.get_meeting_notes()}
        self.meeting_list.clear()
        for n in self._meetings.values():
            mins = int((n["duration_seconds"] or 0) // 60)
            item = QListWidgetItem(f"{n['title']}\n{n['timestamp'][:16].replace('T', ' ')} · {mins} min")
            item.setData(Qt.ItemDataRole.UserRole, n["id"])
            self.meeting_list.addItem(item)
        self.meeting_split.setVisible(bool(self.meeting_list.count()))
        self.meeting_empty.setVisible(not self.meeting_list.count())
        if self.meeting_list.count():
            self.meeting_list.setCurrentRow(0)

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

    # -- vocabulary ---------------------------------------------------------

    def _create_dictionary_tab(self) -> QWidget:
        root, body, _ = self._page("Vocabulary", "Add names, acronyms and terms. OpenFlow corrects them as you speak.", scroll=False)

        form = Group()
        self.dict_phrase = QLineEdit(self)
        self.dict_phrase.setPlaceholderText("e.g. pi torch")
        self.dict_replace = QLineEdit(self)
        self.dict_replace.setPlaceholderText("e.g. PyTorch")
        for e in (self.dict_phrase, self.dict_replace):
            e.setMinimumWidth(240)
        self.dict_case = Switch("", self)
        form.add("When I say", self.dict_phrase)
        form.add("Write", self.dict_replace)
        form.add("Match case", self.dict_case)
        body.addWidget(form)
        add_row = QHBoxLayout()
        add_row.addStretch()
        add_row.addWidget(_btn("Add Word", "primary", slot=self._add_dictionary_word))
        body.addSpacing(8)
        body.addLayout(add_row)
        body.addSpacing(16)

        self.dict_table = QTableWidget(0, 4, self)
        self.dict_table.setHorizontalHeaderLabels(["ID", "When I say", "Write", "Match case"])
        hh = self.dict_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        _style_table(self.dict_table)
        self.dict_table.hideColumn(0)  # id stays in the table for delete
        self.dict_empty = _label("No words yet.\nAdd one above and it applies to your next dictation.", "Empty")
        self.dict_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(_panel(self.dict_table, self.dict_empty), 1)
        body.addSpacing(12)
        del_row = QHBoxLayout()
        del_row.addStretch()
        del_row.addWidget(_btn("Delete Selected", "danger", small=True, slot=self._delete_dictionary_word))
        body.addLayout(del_row)
        return root

    def refresh_dictionary(self):
        rows = self.db.get_dictionary()
        self.dict_table.setRowCount(len(rows))
        self.dict_table.setVisible(bool(rows))
        self.dict_empty.setVisible(not rows)
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

    # -- model library ------------------------------------------------------

    def _create_models_tab(self) -> QWidget:
        root, body, self.lbl_model_status_info = self._page(
            "Model Library", "", scroll=True,
            actions=[_btn("Show Cache", small=True, slot=self._open_cache_folder),
                     _btn("Clean Up", small=True, slot=self._clean_temp_blobs)])
        self.btn_open_cache = None
        self.models_group, _ = self._section(
            body, "Speech and AI models",
            "Models run 100% on this PC. Picking a model never downloads it; use the Download button.")
        return root

    def _model_row(self, m: dict) -> QWidget:
        row = QWidget()
        g = QGridLayout(row)
        g.setContentsMargins(16, 12, 16, 12)
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(4)
        g.setColumnStretch(0, 1)

        title = QHBoxLayout()
        title.setSpacing(8)
        name = _label(m["name"], "RowLabel")
        name.setStyleSheet("font-weight: 600;")
        title.addWidget(name)
        if m["is_active"]:
            title.addWidget(_badge("Active", "active"))
        if m.get("recommended"):
            title.addWidget(_badge("Recommended", "accent"))
        title.addStretch()
        g.addLayout(title, 0, 0)
        g.addWidget(_label(m["description"], "RowSub", wrap=True), 1, 0)
        size = m["disk_size_str"] if m["is_downloaded"] else m["expected_size_str"]
        meta = _label(f"Speed {m['speed']}  ·  Accuracy {m['accuracy']}  ·  {size}", "RowSub")
        meta.setStyleSheet("color: rgba(235,235,245,0.38);")
        g.addWidget(meta, 2, 0)

        acts = QHBoxLayout()
        acts.setSpacing(8)
        mid = m["id"]
        if m["is_active"]:
            b = _btn("In use", small=True)
            b.setEnabled(False)
            acts.addWidget(b)
        elif m["is_downloaded"]:
            acts.addWidget(_btn("Use", "primary", True, lambda _=False, i=mid: self._on_switch_model(i)))
            acts.addWidget(_btn("Delete", "danger", True, lambda _=False, i=mid, n=m["name"]: self._on_delete_model(i, n)))
        else:
            acts.addWidget(_btn("Download", "primary", True, lambda _=False, i=mid: self._on_download_model(i)))
        g.addLayout(acts, 0, 1, 3, 1, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)

        bar = QProgressBar()  # hidden until a download starts
        bar.setRange(0, 100)
        bar.setTextVisible(False)
        bar.hide()
        g.addWidget(bar, 3, 0, 1, 2)
        self._model_progress_bars[mid] = bar
        return row

    def refresh_models(self):
        if not hasattr(self, "models_group"):
            return
        self.models_group.clear()
        self._model_progress_bars = {}
        curr_model = self.config.get("model_size", "base").replace(".en", "").lower()
        hw = hardware.detect()
        self.lbl_model_status_info.setText(f"Active: <b>{curr_model.title()}</b>  ·  Running on <b>{hw.get('device', 'cpu').upper()}</b>")
        self.lbl_model_status_info.show()
        for m in model_manager.list_available_models(active_model=curr_model):
            self.models_group.add_widget(self._model_row(m))

    def set_download(self, percent: int, model: str):
        """Shows or hides the download bar under the header and in the model card."""
        clean_name = model.replace(".en", "").lower()
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

    def _open_cache_folder(self):
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

    # -- settings -----------------------------------------------------------

    @staticmethod
    def _combo(items, current, width: int = 232) -> QComboBox:
        c = NoWheelCombo()
        for label, key in items:
            c.addItem(label, key)
        for i in range(c.count()):
            if c.itemData(i) == current:
                c.setCurrentIndex(i)
                break
        c.setFixedWidth(width)
        return c

    def _switch(self, g: Group, label: str, key: str, default: bool, sub: str = "") -> Switch:
        s = Switch("", self)
        s.setChecked(self.config.get(key, default))
        g.add(label, s, sub)
        return s

    def _create_settings_tab(self) -> QWidget:
        save = _btn("Save Settings", "primary", slot=self._save_settings)
        root, body, _ = self._page("Settings", "Changes to the hotkey and capsule opacity apply at once; the rest on Save.",
                                   actions=[save])
        hw = hardware.detect()

        # Speech
        g, foot = self._section(body, "Speech", hw["note"])
        self.hw_note = foot
        self.model_combo = self._combo([
            (f"Automatic ({hw['model_size']})", "auto"), ("Tiny · fastest (~39 MB)", "tiny"),
            ("Base · balanced (~74 MB)", "base"), ("Small · accurate (~244 MB)", "small"),
            ("Medium · best, wants a GPU (~769 MB)", "medium")], self.config.get("model_size", "auto").replace(".en", ""))
        g.add("Speech model", self.model_combo)
        devices = [("Automatic", "auto")]
        if importlib.util.find_spec("openvino_genai"):
            devices.append(("NPU (Intel AI Boost)", "npu"))
        devices += [("GPU (NVIDIA CUDA)", "cuda"), ("CPU", "cpu")]
        self.device_combo = self._combo(devices, self.config.get("device", "auto"))
        g.add("Run on", self.device_combo)

        self.btn_refresh_stack = _btn("Refresh", small=True, slot=self._refresh_system_stack)
        self.stack_group, _ = self._section(body, "Hardware", action=self.btn_refresh_stack)
        self._refresh_system_stack()

        # Capsule
        g, _ = self._section(body, "Capsule")
        self.capsule_style_combo = self._combo([
            ("Compact (148 px)", "compact"), ("Standard (360 px)", "standard"),
            ("Micro (88 px)", "micro"), ("Dynamic Island (top notch)", "island")], self.config.get("capsule_style", "compact"))
        g.add("Style", self.capsule_style_combo)
        self.island_pos_combo = self._combo([("Top (tucks up when idle)", "top"), ("Bottom", "bottom")],
                                            self.config.get("island_position", "top"))
        g.add("Island position", self.island_pos_combo)

        self.opacity_slider = NoWheelSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(30, 100)  # below 30% the capsule is easy to lose
        self.opacity_slider.setValue(round(float(self.config.get("capsule_opacity", 1.0)) * 100))
        self.opacity_slider.setFixedWidth(176)
        self.opacity_label = _label(f"{self.opacity_slider.value()}%", "RowValue")
        self.opacity_label.setFixedWidth(40)
        self.opacity_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        pair = QWidget()
        pl = QHBoxLayout(pair)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(8)
        pl.addWidget(self.opacity_slider)
        pl.addWidget(self.opacity_label)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        self.opacity_slider.sliderReleased.connect(lambda: save_config(self.config))
        g.add("Opacity", pair)
        self.cb_follow_mouse = self._switch(g, "Follow the cursor", "follow_mouse_screen", True, "Moves the capsule to the screen you are working on.")
        self.cb_realtime = self._switch(g, "Live preview", "realtime_preview", True, "Shows words above the capsule while you speak.")
        self.cb_hide_idle = self._switch(g, "Hide when idle", "hide_capsule_when_idle", False, "No resting pill on the desktop.")

        # Audio
        self.mic_combo = NoWheelCombo()
        self.mic_combo.setFixedWidth(280)
        self.mic_devices = []
        g, self.active_mic_lbl = self._section(body, "Audio", "Active input: Default System Microphone")
        g.add("Microphone", self.mic_combo)
        self.refresh_devices()
        self.silence_spin = NoWheelSpin()
        self.silence_spin.setRange(0.6, 3.5)
        self.silence_spin.setSingleStep(0.1)
        self.silence_spin.setSuffix(" s")
        self.silence_spin.setValue(float(self.config.get("silence_duration", 1.1)))
        self.silence_spin.setFixedWidth(88)
        self.silence_spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        g.add("Pause before writing", self.silence_spin)
        self.cb_autowrite = self._switch(g, "Write when I pause", "auto_write_on_silence", True)
        self.cb_sound = self._switch(g, "Sound feedback", "sound_feedback", True, "Short tones on start and finish.")
        self.cb_voice_edits = self._switch(g, "Voice edits", "voice_edits", False,
                                           "Select text and say \"make this formal\". Downloads a 1.5 GB writing model once.")

        # Output
        g, _ = self._section(body, "Output")
        self.hotkey_input = HotkeyRecorder(self.config.get("hotkey", "ctrl+shift"))
        self.hotkey_input.setFixedHeight(32)
        self.hotkey_input.setMinimumWidth(168)
        self.hotkey_input.sig_recording.connect(self.sig_hotkey_recording.emit)
        self.hotkey_input.sig_changed.connect(self._on_hotkey_recorded)
        g.add("Hotkey", self.hotkey_input, "Click, then press the shortcut you want.")
        self.inj_combo = self._combo([("Instant paste (clipboard)", "clipboard"), ("Type-in effect (word by word)", "typein"),
                                      ("Direct typing (no clipboard)", "type")], self.config.get("injection_method", "clipboard"))
        g.add("Writing method", self.inj_combo)
        self.tone_combo = self._combo([
            ("Auto (matches the app)", "auto"), ("Smart Clean", "smart_clean"), ("Developer / Code", "developer"),
            ("Email & Professional", "email"), ("Bullet Points", "bullets"), ("Raw Verbatim", "verbatim")],
            self.config.get("tone_preset", "auto"))
        g.add("Formatting", self.tone_combo)
        self.cb_restore_clip = self._switch(g, "Restore clipboard", "restore_clipboard", True, "Puts your previous clipboard back after pasting.")

        # System & updates
        try:
            from .. import __version__
        except (ImportError, ValueError):
            from __init__ import __version__
        g, _ = self._section(body, "System")
        self.cb_autostart = self._switch(g, "Open at login", "autostart", False)
        self.btn_check_update = _btn("Check for Updates", small=True, slot=self._on_check_update_clicked)
        self.btn_install_update = _btn("Install", "primary", True, lambda: self.sig_request_install_update.emit())
        self.btn_install_update.hide()
        buttons = QWidget()
        bl = QHBoxLayout(buttons)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(8)
        bl.addWidget(self.btn_install_update)
        bl.addWidget(self.btn_check_update)
        self.update_status_label = g.add(f"Version {__version__}", buttons)
        self.update_status_label.setText("")
        self.ver_label = None
        return root

    def _refresh_system_stack(self):
        g = self.stack_group
        g.clear()
        stack = hardware.get_system_stack(self.config)
        ok, info, off = "#30d158", "#0a84ff", "rgba(235,235,245,0.38)"

        def value(text, color):
            lbl = _label(text, "RowValue")
            lbl.setStyleSheet(f"color: {color};")
            return lbl

        g.add("Active engine", _badge(stack["pipeline"], "active"))
        gpu = stack["gpu"]
        g.add("GPU", value(gpu["status"], ok if gpu["is_active"] else (info if gpu["cuda_available"] else off)),
              f"{gpu['name']} · {gpu['vram_gb']} GB VRAM · {gpu['backend']}")
        npu = stack["npu"]
        g.add("NPU", value(npu["status"], ok if npu["is_active"] else (info if npu["detected"] else off)),
              f"{npu['name']} · {npu['acceleration']}")
        cpu = stack["cpu"]
        g.add("CPU", value(cpu["status"], ok if cpu["is_active"] else off),
              f"{cpu['processor']} · {cpu['cores']} cores · {cpu['ram_gb']} GB RAM")

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
        self.mic_combo.addItem("Default system microphone", None)
        curr_dev = self.config.get("input_device_index")
        for dev in self.mic_devices:
            tag = "  ● Active" if active_mic_name and dev["name"] == active_mic_name else ""
            self.mic_combo.addItem(f"{dev['name']}{tag}", dev["index"])
            if curr_dev == dev["index"]:
                self.mic_combo.setCurrentIndex(self.mic_combo.count() - 1)
        self.mic_combo.blockSignals(False)
        if hasattr(self, "active_mic_lbl") and active_mic_name:
            self.active_mic_lbl.setText(f"Active input: {active_mic_name}")
            self.active_mic_lbl.show()

    # -- analytics ----------------------------------------------------------

    def _create_stats_tab(self) -> QWidget:
        root, body, _ = self._page("Analytics", "Your dictation so far, kept on this PC.")
        grid = QGridLayout()
        grid.setSpacing(12)
        self.card_dictations = self._make_metric_card("Dictations", "0")
        self.card_words = self._make_metric_card("Words spoken", "0")
        self.card_saved = self._make_metric_card("Typing time saved", "0 hrs")
        self.card_speed = self._make_metric_card("Effective speed", "150 WPM")
        for i, c in enumerate((self.card_dictations, self.card_words, self.card_saved, self.card_speed)):
            grid.addWidget(c, i // 2, i % 2)
        body.addLayout(grid)

        hw_info = hardware.detect()
        gpu_label = hw_info.get("gpu_name") or ("NVIDIA GPU" if hw_info.get("cuda_ok") else "CPU / Local Hardware")
        g, _ = self._section(body, "Why OpenFlow")
        for title, detail in [
            ("No usage limits", f"Runs 100% locally on your computer with your {gpu_label}. No monthly minute quotas or tier limits."),
            ("Fully private", "Zero audio or clipboard data is sent over the internet. Everything stays on your local disk."),
            ("Low latency", "Using faster-whisper CTranslate2 float16, dictation finishes in about 100-200 milliseconds."),
            ("Free", "No subscriptions, credit card prompts, or paywalls."),
        ]:
            g.add(title, None, detail)
        return root

    def _make_metric_card(self, title: str, value: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName("Group")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(4)
        lay.addWidget(_label(title, "RowSub"))
        lay.addWidget(_label(value, "MetricValue"))
        return card

    def refresh_stats(self):
        stats = self.db.get_stats()
        self.card_dictations.findChild(QLabel, "MetricValue").setText(str(stats["total_dictations"]))
        self.card_words.findChild(QLabel, "MetricValue").setText(f"{stats['total_words']:,}")
        self.card_saved.findChild(QLabel, "MetricValue").setText(f"{stats['time_saved_hours']} hrs")

    # -- updates ------------------------------------------------------------

    def _on_check_update_clicked(self):
        self.show_update_checking()
        self.sig_request_check_update.emit()

    def show_update_checking(self):
        self.update_status_label.setText("Checking for updates...")
        self.update_status_label.show()
        self.btn_check_update.setEnabled(False)

    def show_update_available(self, version: str, notes: str = ""):
        self.btn_check_update.setEnabled(True)
        self.update_status_label.setText(f"Update available: <b>v{version}</b>")
        self.update_status_label.show()
        self.btn_install_update.setText(f"Install v{version}")
        self.btn_install_update.show()

    def show_up_to_date(self, version: str = ""):
        self.btn_check_update.setEnabled(True)
        self.update_status_label.setText("OpenFlow is up to date.")
        self.update_status_label.show()
        self.btn_install_update.hide()

    def show_update_error(self, message: str):
        self.btn_check_update.setEnabled(True)
        self.update_status_label.setText(f"Update check: {message}")
        self.update_status_label.show()

    # -- about --------------------------------------------------------------

    def _create_about_tab(self) -> QWidget:
        try:
            from .. import __version__
        except (ImportError, ValueError):
            from __init__ import __version__
        root, body, _ = self._page("About")

        head = QHBoxLayout()
        head.setSpacing(16)
        logo = _logo_label(34)
        if logo:
            head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = _label(f"OpenFlow  <span style='font-size:13px; color:rgba(235,235,245,0.6); font-weight:400;'>v{__version__}</span>", "PageTitle")
        name.setStyleSheet("font-size: 20px;")
        col.addWidget(name)
        col.addWidget(_label("Private, unlimited voice dictation and speech-to-writing. 100% on-device AI.", "PageSub", wrap=True))
        head.addLayout(col, 1)
        body.addLayout(head)

        def link(url):
            return lambda: QDesktopServices.openUrl(QUrl(url))

        g, _ = self._section(
            body, "Developer",
            "Developed by Sachidananda as a private, offline alternative to cloud dictation tools: "
            "dictate into any app with no cloud latency and no subscription.")
        g.add("GitHub repository", _btn("Open", small=True, slot=link("https://github.com/Sachin1724/OpenFlow")))
        g.add("Project website", _btn("Open", small=True, slot=link("https://sachin1724.github.io/OpenFlow/")))
        g.add("Contact or report an issue", _btn("Email", "primary", True, link(
            "mailto:fakesachin.19@gmail.com?subject=OpenFlow%20Feedback%20%2F%20Issue%20Report")))

        g, _ = self._section(body, "Privacy")
        for title, detail in [
            ("On-device transcription", "Every word is processed locally via Whisper and CTranslate2. No audio leaves your device."),
            ("No telemetry", "OpenFlow has no cloud tracking, analytics, or external API dependencies."),
            ("Local database", "Your history and vocabulary live on this PC in %USERPROFILE%\\.openflow\\openflow.db."),
            ("You are in control", "Delete models, purge vocabulary, or clear your history at any time."),
        ]:
            g.add(title, None, detail)
        return root
