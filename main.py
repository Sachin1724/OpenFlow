import sys
import os
import datetime
import threading
import time
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QTimer, QRectF
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPainterPath, QPen, QBrush

try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenFlow.VoiceToText.App.1.0")
except Exception:
    pass

try:
    from .config import load_config, save_config, get_asset_path
    from .database import Database
    from .engine.audio_recorder import (
        AudioRecorder, list_microphones, hardware_input_count,
        get_live_hardware_microphones, clean_device_name
    )
    from .engine.transcriber import Transcriber, engine_model_name, StreamingSession
    from .engine.formatter import TextFormatter
    from .engine.injector import WindowInjector
    from .engine.hotkey_manager import GlobalHotkeyManager
    from .engine.sound_effects import play_start_sound, play_stop_sound, play_paste_sound
    from .engine.context_detector import get_active_app_context, build_initial_prompt, AppContext
    from .engine.updater import AppUpdater
    from .engine.meeting import MeetingSession, active_meeting_app, format_meeting_notes, transcript_text, watch_mic
    from .ui.floating_pill import FloatingPill, MeetingBar, ui_font_family
    from .ui.main_window import MainWindow
    from .ui.setup_dialog import SetupDialog
    from .autostart import set_autostart
    from .engine import hardware, model_manager
    from . import __version__
except (ImportError, ValueError):
    from config import load_config, save_config, get_asset_path
    from database import Database
    from engine.audio_recorder import (
        AudioRecorder, list_microphones, hardware_input_count,
        get_live_hardware_microphones, clean_device_name
    )
    from engine.transcriber import Transcriber, engine_model_name, StreamingSession
    from engine.formatter import TextFormatter
    from engine.injector import WindowInjector
    from engine.hotkey_manager import GlobalHotkeyManager
    from engine.sound_effects import play_start_sound, play_stop_sound, play_paste_sound
    from engine.context_detector import get_active_app_context, build_initial_prompt, AppContext
    from engine.updater import AppUpdater
    from engine.meeting import MeetingSession, active_meeting_app, format_meeting_notes, transcript_text, watch_mic
    from ui.floating_pill import FloatingPill, MeetingBar, ui_font_family
    from ui.main_window import MainWindow
    from ui.setup_dialog import SetupDialog
    from autostart import set_autostart
    from engine import hardware, model_manager
    try:
        from __init__ import __version__
    except ImportError:
        __version__ = "1.1.5"

_BOOT_T0 = time.perf_counter()


def _boot(msg: str):
    """Boot timeline in the log, so a slow start can be pinned on one phase."""
    print(f"[OpenFlow] boot +{time.perf_counter() - _BOOT_T0:5.1f}s  {msg}")


def create_tray_icon_pixmap() -> QPixmap:
    size = 32
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    icon_path = get_asset_path("app_icon_square.png")
    if not os.path.exists(icon_path):
        icon_path = get_asset_path("logo.jpg")
    if os.path.exists(icon_path):
        src = QPixmap(icon_path).scaled(
            size, size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = (size - src.width()) // 2
        y = (size - src.height()) // 2
        painter.drawPixmap(x, y, src)
        painter.end()
        return pixmap

    # Fallback vector icon
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(255, 255, 255))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)
    painter.setBrush(QColor(0, 0, 0))
    painter.drawRoundedRect(12, 8, 8, 12, 4, 4)
    painter.drawRect(15, 20, 2, 4)
    painter.drawRect(12, 23, 8, 2)
    painter.end()
    return pixmap


def hotkey_label(cfg: dict) -> str:
    """'ctrl+shift' -> 'Ctrl+Shift' for user-facing text."""
    return "+".join(k.upper() if k[:1] == "f" and k[1:].isdigit() else k.capitalize()
                    for k in cfg.get("hotkey", "ctrl+shift").split("+"))


class AppBridge(QObject):
    """Qt signal bridge between background threads and UI."""
    sig_start_recording = pyqtSignal()
    sig_stop_recording = pyqtSignal()
    sig_amplitude = pyqtSignal(float)
    sig_realtime_text = pyqtSignal(str)
    sig_transcription_complete = pyqtSignal(str, int, int) # (formatted_text, word_count, latency_ms)
    sig_error = pyqtSignal(str)   # short message shown in the capsule
    sig_status = pyqtSignal(str)  # model download/load messages
    sig_download = pyqtSignal(int, str)  # (percent, model name)
    sig_update_available = pyqtSignal(str, str, str, str)  # (version, release_url, download_url, notes)
    sig_update_ready = pyqtSignal(str)                     # (installer_path)
    sig_meeting_line = pyqtSignal(str, str)                # (speaker, text) live caption
    sig_meeting_saved = pyqtSignal(str)                    # note title, "" when nothing was said
    sig_mic_changed = pyqtSignal()                         # some app started/stopped using a mic


class OpenFlowApp(QObject):
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        super().__init__()
        self.app.setQuitOnLastWindowClosed(False)  # type: ignore[attr-defined]

        # Set application brand icon globally
        app_icon_path = get_asset_path("app_icon_square.png")
        if not os.path.exists(app_icon_path):
            app_icon_path = get_asset_path("logo.jpg")
        if os.path.exists(app_icon_path):
            self.app.setWindowIcon(QIcon(app_icon_path))

        # Sanitize Windows HF model symlinks to eliminate WinError 448 (untrusted mount points)
        try:
            model_manager.sanitize_all_cached_models()
        except Exception:
            pass

        ui_font_family()



        # Config & DB
        self.config = load_config()
        if not self.config.get("setup_done"):
            dlg = SetupDialog(self.config)
            if not dlg.exec():
                sys.exit(0)
            save_config(self.config)
            set_autostart(self.config["autostart"])
        self.db = Database()
        _boot("database ready")

        # Target window + app context (snapshotted on hotkey press)
        self.target_window_info = {"hwnd": 0, "title": "", "process": ""}
        self._app_context: AppContext = get_active_app_context()  # type: ignore[assignment]
        self._is_processing = False
        _boot("app context detected")

        # Bridge
        self.bridge = AppBridge()
        self.bridge.sig_start_recording.connect(self._handle_ui_start)
        self.bridge.sig_stop_recording.connect(self._handle_ui_stop)
        self.bridge.sig_amplitude.connect(self._handle_ui_amplitude)
        self.bridge.sig_error.connect(self._handle_ui_error)
        self.bridge.sig_download.connect(self._handle_ui_download)
        self.bridge.sig_realtime_text.connect(self._handle_ui_realtime_text)
        self.bridge.sig_transcription_complete.connect(self._handle_ui_complete)
        self.bridge.sig_status.connect(self._handle_status)

        # Engine Components
        self.injector = WindowInjector()
        self.formatter = TextFormatter(self.db.get_dictionary())
        rt = hardware.resolve(self.config)
        self.transcriber = Transcriber(
            model_size=rt["model_size"],
            device=rt["device"],
            compute_type=rt["compute_type"],
            language=self.config.get("language", "en"),
            preload=False,  # loaded in the background below so a missing model never freezes startup
        )
        print(f"[OpenFlow] {rt['hw']['note']} Model: {rt['model_size']}")
        self.transcriber.on_status = self.bridge.sig_status.emit
        self.transcriber.on_progress = self.bridge.sig_download.emit

        silence_sec = float(self.config.get("silence_duration", 1.1))
        self.audio_recorder = AudioRecorder(
            device_index=self.config.get("input_device_index"),
            on_amplitude=lambda lvl: self.bridge.sig_amplitude.emit(lvl),
            on_auto_silence=self._on_auto_silence,
            on_stream_chunk=self._on_stream_chunk,
            auto_silence_duration=silence_sec,
        )

        # Hotkey Manager
        self.hotkey_mgr = GlobalHotkeyManager(
            hotkey_str=self.config.get("hotkey", "ctrl+shift"),
            mode=self.config.get("trigger_mode", "push_to_talk"),
            on_start=self._on_hotkey_press,
            on_stop=self._on_hotkey_release,
        )

        # UI Components
        _boot("recorder + hotkey objects created")
        initial_mic = self.audio_recorder.get_current_device_name()
        _boot("microphone queried")
        self._known_mics = {d["name"]: d for d in list_microphones()}
        self._hw_mic_count = hardware_input_count()
        self._known_live_mics = set(get_live_hardware_microphones())
        recents = self.config.get("recent_mics", [])
        if initial_mic and initial_mic not in recents:
            recents.insert(0, initial_mic)
            self.config["recent_mics"] = recents[:5]
            save_config(self.config)

        curr_model = self.config.get("model_size", "base")
        self.floating_pill = FloatingPill(
            current_mic_name=initial_mic,
            current_language=self.config.get("language", "en"),
            current_model=curr_model,
            hide_when_idle=self.config.get("hide_capsule_when_idle", False),
        )
        self.floating_pill.populate_mics(recents)
        self.floating_pill.populate_models(curr_model)
        self.floating_pill.sig_mic_changed.connect(self._on_capsule_mic_changed)
        self.floating_pill.sig_language_changed.connect(self._on_capsule_language_changed)
        self.floating_pill.sig_tone_changed.connect(self._on_capsule_tone_changed)
        self.floating_pill.sig_model_changed.connect(self._on_capsule_model_changed)
        self.floating_pill.sig_hide_idle_changed.connect(self._on_capsule_hide_idle_changed)
        self.floating_pill.sig_open_dashboard.connect(self.show_dashboard)

        _boot("capsule built")
        self.main_window = MainWindow(self.db, self.config)
        self.main_window.refresh_devices(initial_mic)
        self.main_window.config_changed.connect(self._on_config_changed)
        self.main_window.sig_model_switch_requested.connect(self._on_request_switch_model)
        self.main_window.sig_model_download_requested.connect(self._on_request_download_model)
        self.main_window.sig_model_delete_requested.connect(self._on_request_delete_model)
        # pause the global hotkey while the settings box records a new one
        self.main_window.sig_hotkey_recording.connect(
            lambda on: self.hotkey_mgr.stop() if on else self.hotkey_mgr.start())
        _boot("dashboard built")

        # In-App Auto-Updater
        self.updater = AppUpdater(current_version=__version__, repo="Sachin1724/OpenFlow", parent=self)
        self.updater.sig_update_available.connect(self._on_update_available)
        self.updater.sig_no_update.connect(self._on_no_update)
        self.updater.sig_progress.connect(self._handle_ui_download)
        self.updater.sig_ready.connect(self._on_update_ready)
        self.updater.sig_error.connect(self._on_update_error)

        self.floating_pill.sig_update_requested.connect(lambda: self.updater.start_download_async())
        self.main_window.sig_request_check_update.connect(lambda: self.updater.check_for_updates_async(notify_if_current=True))
        self.main_window.sig_request_install_update.connect(lambda: self.updater.start_download_async())

        # Check for updates in background 8 seconds after startup
        QTimer.singleShot(8000, lambda: self.updater.check_for_updates_async(notify_if_current=False))

        # System Tray
        self._init_tray()
        _boot("tray ready")

        # Start hotkey listening
        self.hotkey_mgr.start()
        self._reload_transcriber_async()
        try:
            self.audio_recorder.open_stream()  # warm mic so the first word is never clipped
        except Exception as e:
            print(f"[OpenFlow] Microphone not available yet ({e}); will retry on first dictation")

        # Housekeeping: detect sleep/resume, unload model when idle
        self._last_tick = self._last_activity = time.monotonic()
        self._housekeeping = QTimer(self)
        self._housekeeping.timeout.connect(self._housekeep)
        self._housekeeping.start(5000)

        # Dedicated mic hotplug poller (runs every 1500 ms for immediate responsiveness)
        self._mic_poll_timer = QTimer(self)
        self._mic_poll_timer.timeout.connect(self._check_mic_hotplug)
        self._mic_poll_timer.start(1500)

        # Meeting mode: offer to take notes while a call app is using the mic
        self._meeting = None
        self._meeting_app = None
        self._meeting_dismissed = None
        self._meeting_gone = None  # monotonic time the call app let go of the mic
        self.meeting_bar = MeetingBar()
        self.meeting_bar.sig_start.connect(self._start_meeting)
        self.meeting_bar.sig_stop.connect(self._stop_meeting)
        self.meeting_bar.sig_dismiss.connect(lambda: setattr(self, "_meeting_dismissed", self._meeting_app))
        self.bridge.sig_meeting_line.connect(self._on_meeting_line)
        self.bridge.sig_meeting_saved.connect(self._on_meeting_saved)
        # Instant: Windows tells us the moment any app grabs or drops a mic.
        # The timer is the fallback and drives the end-of-call grace period.
        self.bridge.sig_mic_changed.connect(self._check_meeting)
        watch_mic(self.bridge.sig_mic_changed.emit)
        self._meeting_timer = QTimer(self)
        self._meeting_timer.timeout.connect(self._check_meeting)
        self._meeting_timer.start(3000)

    def _active_msg(self) -> str:
        return f"OpenFlow Active · Hold {hotkey_label(self.config)} to Speak"

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self.app)
        self.tray.setIcon(QIcon(create_tray_icon_pixmap()))
        self.tray.setToolTip(f"OpenFlow — Hold {hotkey_label(self.config)} to Speak")

        menu = QMenu()
        act_hud = menu.addAction("Show Capsule HUD")
        act_hud.triggered.connect(lambda: self.floating_pill.show_message(self._active_msg(), duration_ms=3500))

        act_expand = menu.addAction("Capsule Settings (Expand HUD)")
        act_expand.triggered.connect(self.floating_pill.expand_to_hud)

        self.act_hide_idle = menu.addAction("Hide Minimized Capsule on Desktop")
        self.act_hide_idle.setCheckable(True)
        self.act_hide_idle.setChecked(self.config.get("hide_capsule_when_idle", False))
        self.act_hide_idle.triggered.connect(self._on_tray_toggle_hide_idle)

        act_open = menu.addAction("Show Dashboard")
        act_open.triggered.connect(self.show_dashboard)

        act_update = menu.addAction("Check for Updates...")
        act_update.triggered.connect(lambda: self.updater.check_for_updates_async(notify_if_current=True))

        act_toggle = menu.addAction("Dictate Now")
        act_toggle.triggered.connect(self._toggle_dictation_manual)

        menu.addSeparator()
        tone_menu = menu.addMenu("Formatting Tone")
        for key, label in [
            ("auto", "Auto (match app)"),
            ("smart_clean", "Smart Clean"),
            ("developer", "Developer / Code"),
            ("email", "Email & Formal"),
            ("bullets", "Bullet Points"),
            ("verbatim", "Raw Verbatim"),
        ]:
            act = tone_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.config.get("tone_preset") == key)
            act.triggered.connect(lambda checked, k=key: self._set_tone_preset(k))

        menu.addSeparator()
        act_quit = menu.addAction("Quit OpenFlow")
        act_quit.triggered.connect(self.quit_app)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.floating_pill.show_message(self._active_msg(), duration_ms=3500)
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_dashboard()


    def show_dashboard(self):
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _set_tone_preset(self, preset: str):
        self.config["tone_preset"] = preset
        save_config(self.config)
        self.main_window.refresh_stats()

    def _on_capsule_hide_idle_changed(self, hide: bool):
        self.config["hide_capsule_when_idle"] = hide
        save_config(self.config)
        if hasattr(self, "main_window"):
            self.main_window.update_hide_capsule_idle_state(hide)
        if hasattr(self, "act_hide_idle"):
            self.act_hide_idle.blockSignals(True)
            self.act_hide_idle.setChecked(hide)
            self.act_hide_idle.blockSignals(False)

    def _on_tray_toggle_hide_idle(self, checked: bool):
        self.config["hide_capsule_when_idle"] = checked
        save_config(self.config)
        if hasattr(self, "floating_pill"):
            self.floating_pill.set_hide_when_idle(checked)
        if hasattr(self, "main_window"):
            self.main_window.update_hide_capsule_idle_state(checked)

    def _on_capsule_mic_changed(self, device_idx):
        self.config["input_device_index"] = device_idx
        self.audio_recorder.set_device(device_idx)
        friendly = self.audio_recorder.get_current_device_name()
        recents = self.config.get("recent_mics", [])
        if friendly in recents:
            recents.remove(friendly)
        recents.insert(0, friendly)
        self.config["recent_mics"] = recents[:5]
        save_config(self.config)
        self.floating_pill.update_connected_mic(friendly)
        self.floating_pill.populate_mics(recents)
        if hasattr(self, "main_window"):
            self.main_window.refresh_devices()
        print(f"[OpenFlow] Switched microphone to: {friendly}")

    def _on_capsule_language_changed(self, lang_code):
        self.config["language"] = lang_code
        save_config(self.config)
        self._reload_transcriber_async(language=lang_code)
        print(f"[OpenFlow] Switched language to: {lang_code}")

    def _reload_transcriber_async(self, language=None):
        """Model swap can download hundreds of MB; never block the UI thread."""
        cfg = self.config
        rt = hardware.resolve(cfg)
        threading.Thread(
            target=lambda: self.transcriber.reload(
                model_size=rt["model_size"],
                device=rt["device"],
                compute_type=rt["compute_type"],
                language=language or cfg.get("language", "en"),
            ),
            daemon=True,
        ).start()

    def _on_capsule_tone_changed(self, tone):
        self.config["tone_preset"] = tone
        save_config(self.config)
        print(f"[OpenFlow] Switched tone to: {tone}")

    def _on_capsule_model_changed(self, model_id: str):
        self._on_request_switch_model(model_id)

    def _on_request_switch_model(self, model_id: str):
        self.config["model_size"] = model_id
        save_config(self.config)
        self._reload_transcriber_async()
        if hasattr(self, "main_window"):
            self.main_window.refresh_models()
        if hasattr(self, "floating_pill"):
            self.floating_pill.populate_models(model_id)
            self.floating_pill.show_message(f"Model: {model_id.title()} Active", duration_ms=3000)
        print(f"[OpenFlow] Switched active model to: {model_id}")

    def _on_request_download_model(self, model_id: str):
        def _bg_dl():
            try:
                self.bridge.sig_status.emit(f"Downloading {model_id} model...")
                # fetch the variant this language actually loads (base.en for English)
                model_manager.download(
                    engine_model_name(model_id, self.config.get("language", "en"), self.transcriber.device),
                    on_progress=lambda pct: self.bridge.sig_download.emit(pct, model_id)
                )
                # When download completes, automatically make this model active!
                self.config["model_size"] = model_id
                save_config(self.config)
                self._reload_transcriber_async()
                self.bridge.sig_status.emit(f"Model {model_id} downloaded and active!")
                if hasattr(self, "main_window"):
                    self.main_window.refresh_models()
                if hasattr(self, "floating_pill"):
                    self.floating_pill.populate_models(model_id)
                    self.floating_pill.show_message(f"Model {model_id.title()} Ready & Active", duration_ms=4000)
            except Exception as e:
                print(f"[OpenFlow] Download {model_id} failed: {e}")
                self.bridge.sig_status.emit(f"Download failed: {e}")
                self.bridge.sig_error.emit(f"Download failed: {e}")

        threading.Thread(target=_bg_dl, daemon=True).start()

    def _on_request_delete_model(self, model_id: str):
        curr = self.config.get("model_size", "base").replace(".en", "").lower()
        if curr == model_id:
            fallback = "base" if model_id != "base" else "tiny"
            self.config["model_size"] = fallback
            save_config(self.config)
            self.transcriber.unload()
            self._reload_transcriber_async()
        ok = model_manager.delete_model(model_id)
        if hasattr(self, "main_window"):
            self.main_window.refresh_models()
        if hasattr(self, "floating_pill"):
            self.floating_pill.populate_models(self.config.get("model_size", "base"))
            self.floating_pill.show_message(f"Model {model_id} Deleted", duration_ms=2500)
        if ok:
            self.bridge.sig_status.emit(f"Model {model_id} deleted.")

    def _on_config_changed(self, new_cfg: dict):
        self.config = new_cfg
        self.hotkey_mgr.update_config(new_cfg.get("hotkey", "ctrl+shift"), new_cfg.get("trigger_mode", "push_to_talk"))
        if hasattr(self, "tray"):
            self.tray.setToolTip(f"OpenFlow — Hold {hotkey_label(new_cfg)} to Speak")
        self.audio_recorder.set_device(new_cfg.get("input_device_index"))
        set_autostart(new_cfg.get("autostart", False))
        self.audio_recorder.set_auto_silence_duration(float(new_cfg.get("silence_duration", 1.1)))
        self._reload_transcriber_async()
        self.formatter.set_dictionary(self.db.get_dictionary())
        if hasattr(self, "floating_pill"):
            self.floating_pill.set_hide_when_idle(new_cfg.get("hide_capsule_when_idle", False))
        if hasattr(self, "act_hide_idle"):
            self.act_hide_idle.blockSignals(True)
            self.act_hide_idle.setChecked(new_cfg.get("hide_capsule_when_idle", False))
            self.act_hide_idle.blockSignals(False)

    IDLE_UNLOAD_SEC = 600

    def _housekeep(self):
        now = time.monotonic()
        if now - self._last_tick > 30:  # a 5s timer that slept >30s means system sleep/resume
            print("[OpenFlow] Resumed from sleep: restarting hotkey")
            self.audio_recorder.close_stream()  # the old stream can be dead after sleep; reopened on next use
            self.hotkey_mgr.stop()
            self.hotkey_mgr.start()
        self._last_tick = now
        busy = self._is_processing or self.audio_recorder.is_recording
        if not busy:
            self._check_mic_hotplug()
        self._gpu_tick = getattr(self, "_gpu_tick", 0) + 1
        if self._gpu_tick % 6 == 0 and not busy and self.config.get("device", "auto") == "auto":
            threading.Thread(target=self._check_gpu, daemon=True).start()  # every ~30 s
        if not busy and self.transcriber.model is not None and now - self._last_activity > self.IDLE_UNLOAD_SEC:
            print("[OpenFlow] Idle: unloading model, releasing microphone")
            self.transcriber.unload()
            self.audio_recorder.close_stream()

    def _check_meeting(self):
        app = active_meeting_app()
        if self._meeting is not None:
            # The call app lets go of the mic when the call ends; stop after 12 s without it
            # (time-based: mic events make checks arrive at irregular intervals)
            if app:
                self._meeting_gone = None
            elif self._meeting_gone is None:
                self._meeting_gone = time.monotonic()
            elif time.monotonic() - self._meeting_gone >= 12:
                self._stop_meeting()
            return
        if app == self._meeting_app:
            return
        self._meeting_app = app
        if app and app != self._meeting_dismissed:
            self.meeting_bar.show_prompt(app, self.floating_pill.geometry())
        elif not app:
            self.meeting_bar.hide()
            self._meeting_dismissed = None

    def _start_meeting(self):
        # Calls mix languages: English settings switch to auto-detect; translate or a fixed language is kept
        lang = self.config.get("language", "auto")
        if lang in ("en", "en-in"):
            lang = "auto"
        session = MeetingSession(self.transcriber, lang, self.bridge.sig_meeting_line.emit,
                                 mic_device=self.audio_recorder.device_index)
        try:
            session.start()
        except Exception as e:
            print(f"[OpenFlow Meeting] Could not start: {e}")
            self.floating_pill.show_message("Couldn't start meeting notes")
            return
        self._meeting, self._meeting_gone = session, None
        self.meeting_bar.show_recording(self.floating_pill.geometry())

    def _stop_meeting(self):
        session, self._meeting = self._meeting, None
        if session is None:
            return
        app = self._meeting_app or "Meeting"
        self._meeting_dismissed = app  # don't offer again for the call that just ended
        self.meeting_bar.finish()
        self.floating_pill.show_message("Writing meeting notes…", duration_ms=4000)

        def work():
            lines = session.stop()
            if not lines:
                self.bridge.sig_meeting_saved.emit("")
                return
            raw = transcript_text(lines)
            title = f"{app} · {datetime.datetime.now():%d %b %H:%M}"
            self.db.add_meeting_note(title, app, raw, format_meeting_notes(raw, app), time.time() - session.started)
            self.bridge.sig_meeting_saved.emit(title)

        threading.Thread(target=work, daemon=True).start()

    def _on_meeting_line(self, who: str, text: str):
        self._last_activity = time.monotonic()  # keep the model loaded for the whole call
        self.meeting_bar.add_line(who, text)

    def _on_meeting_saved(self, title: str):
        self.floating_pill.show_message("Meeting notes saved" if title else "No speech recorded in the meeting")
        if title and hasattr(self, "main_window"):
            self.main_window.refresh_meetings()

    def _check_mic_hotplug(self):
        """Detect microphone connect / disconnect events in real time from Windows kernel and alert via pseudo-capsule."""
        try:
            curr_live = set(get_live_hardware_microphones())
            known_live = getattr(self, "_known_live_mics", None)
            if known_live is None:
                self._known_live_mics = curr_live
                return

            if curr_live != known_live:
                added = [n for n in curr_live if n not in known_live]
                removed = [n for n in known_live if n not in curr_live]
                self._known_live_mics = curr_live

                # Refresh PortAudio so internal device cache is synchronized
                if not self.audio_recorder.is_recording:
                    self.audio_recorder.refresh_devices()

                if added:
                    for name in added:
                        print(f"[OpenFlow] New microphone connected: {name}")
                        self.floating_pill.show_mic_event(name, "connected")
                        recents = self.config.get("recent_mics", [])
                        if name not in recents:
                            recents.insert(0, name)
                            self.config["recent_mics"] = recents[:5]
                            save_config(self.config)
                    self.floating_pill.populate_mics(self.config.get("recent_mics", []))
                    if hasattr(self, "main_window"):
                        curr_active = self.audio_recorder.get_current_device_name()
                        self.main_window.refresh_devices(curr_active)

                if removed:
                    for name in removed:
                        print(f"[OpenFlow] Microphone unplugged: {name}")
                        curr_active = self.audio_recorder.get_current_device_name()
                        if name == curr_active or curr_active not in curr_live:
                            print("[OpenFlow] Active microphone unplugged; switching to system default.")
                            self.config["input_device_index"] = None
                            save_config(self.config)
                            self.audio_recorder.set_device(None)
                            new_name = self.audio_recorder.get_current_device_name()
                            self.floating_pill.show_mic_event(new_name, "switched")
                            self.floating_pill.update_connected_mic(new_name)
                        else:
                            self.floating_pill.show_mic_event(name, "disconnected")
                    self.floating_pill.populate_mics(self.config.get("recent_mics", []))
                    if hasattr(self, "main_window"):
                        curr_active = self.audio_recorder.get_current_device_name()
                        self.main_window.refresh_devices(curr_active)
        except Exception as e:
            print(f"[OpenFlow] Hotplug detection error: {e}")

    def _check_gpu(self):
        """Follow the GPU being switched on/off while running (nvidia-smi probe, ~0.1 s)."""
        if hardware.gpu_changed():
            print(f"[OpenFlow] {hardware.detect()['note']} Reloading the speech model.")
            self._reload_transcriber_async()

    def _toggle_dictation_manual(self):
        if not self.audio_recorder.is_recording:
            self._start_dictating()
        else:
            self._stop_and_process()

    def _on_hotkey_press(self):
        mode = self.config.get("trigger_mode", "push_to_talk")
        if mode == "push_to_talk":
            self._start_dictating()
        else: # "auto_silence" or "toggle"
            if not self.audio_recorder.is_recording:
                self._start_dictating()
            else:
                self._stop_and_process()

    def _on_hotkey_release(self):
        mode = self.config.get("trigger_mode", "push_to_talk")
        if (mode in ("push_to_talk", "toggle")) and self.audio_recorder.is_recording:
            self._stop_and_process()

    def _start_dictating(self):
        if self._is_processing or self.audio_recorder.is_recording:
            return

        self._last_activity = time.monotonic()
        if self.transcriber.model is None:  # warm up while the user speaks
            self._reload_transcriber_async()

        # 1. Capture the exact active target window immediately
        self.target_window_info = self.injector.get_foreground_window()

        # 1b. Snapshot active app context for prompt biasing
        self._app_context = get_active_app_context()
        print(f"[OpenFlow] Context: {self._app_context['category']} | {self._app_context['process']} | '{self._app_context['title'][:60]}'")

        # 1c. Build the vocabulary prompt now so phrases can be transcribed while the user talks
        lang = self.config.get("language", "auto")
        dict_entries = self.db.get_dictionary()
        self.formatter.set_dictionary(dict_entries)
        initial_prompt = build_initial_prompt(
            context=self._app_context,
            custom_vocab=[e["replace_with"] for e in dict_entries],  # preferred spellings
            language=lang,
        )
        if initial_prompt:
            print(f"[OpenFlow] Prompt ({len(initial_prompt)} chars): {initial_prompt[:80]}...")
        self._stream_session = StreamingSession(self.transcriber, lang, initial_prompt)

        # 2. Pleasant start sound
        if self.config.get("sound_feedback", True):
            play_start_sound()

        # 3. Start audio stream, then notify capsule UI
        try:
            self.audio_recorder.start_recording()
        except Exception as e:
            print(f"[OpenFlow] Error starting audio: {e}")
            self.bridge.sig_error.emit("Microphone unavailable")
            return
        self.bridge.sig_start_recording.emit()

    def _on_stream_chunk(self, audio_chunk):
        """Called periodically during speech to provide real-time live preview words."""
        if not self.audio_recorder.is_recording:
            return
        if self.config.get("realtime_preview", True):
            partial_text = self.transcriber.transcribe_partial(audio_chunk)
            if partial_text:
                self.bridge.sig_realtime_text.emit(partial_text)
        session = getattr(self, "_stream_session", None)
        if session is not None:
            session.feed(audio_chunk)  # commit finished phrases so release only decodes the tail

    def _on_auto_silence(self):
        """Automatically triggered when user stops speaking for silence_duration."""
        if self.config.get("auto_write_on_silence", True) and self.audio_recorder.is_recording:
            print("[OpenFlow] Auto-silence detected: automatically writing text!")
            self._stop_and_process()

    def _stop_and_process(self):
        if not self.audio_recorder.is_recording or self._is_processing:
            return

        self._is_processing = True

        # 1. Update capsule UI to writing state
        self.bridge.sig_stop_recording.emit()

        # 2. Stop audio recorder
        audio_data = self.audio_recorder.stop_recording()
        session, self._stream_session = self._stream_session, None

        # 3. Process in worker thread
        threading.Thread(target=self._process_worker, args=(audio_data, session), daemon=True).start()

    def _process_worker(self, audio_data, session):
        try:
            if len(audio_data) < 3000: # Less than 0.2s of audio
                self.bridge.sig_error.emit("Too short")
                return

            peak = float(abs(audio_data).max())
            print(f"[OpenFlow] Captured {len(audio_data) / 16000:.1f}s of audio, peak level {peak:.3f}")
            if peak < 0.004:  # near-digital silence: wrong input device or Windows microphone privacy block
                print("[OpenFlow] Microphone is silent. Check Windows Settings > Privacy > Microphone and the input device.")
                self.bridge.sig_error.emit("No sound from mic")
                return

            # Phrases spoken before the last pause are already transcribed; decode only the tail
            raw_text, duration_sec, latency_ms, detected_lang = session.finish(audio_data)

            if not raw_text.strip():
                self.bridge.sig_error.emit("Didn't catch that")
                return

            # Format speech (speech-to-writing: self-corrections, fillers, tech casing, context)
            tone = self.config.get("tone_preset", "auto")
            context_cat = self._app_context.get("category", "general") if isinstance(self._app_context, dict) else "general"
            if tone == "auto":
                tone = self._app_context.get("tone_suggestion", "smart_clean") if isinstance(self._app_context, dict) else "smart_clean"

            formatted = self.formatter.format(
                raw_text,
                tone_preset=tone,
                language=detected_lang,
                context_category=context_cat,
            )
            word_count = len(formatted.split())

            # Automatically write text into the target window
            target_hwnd = self.target_window_info.get("hwnd", 0) or 0
            target_app = self.target_window_info.get("process", "") or ""
            target_title = self.target_window_info.get("title", "") or ""
            method = self.config.get("injection_method", "clipboard")
            restore_clip = self.config.get("restore_clipboard", True)

            self.injector.inject_text(
                formatted,
                target_hwnd=target_hwnd,
                method=method,
                restore_clipboard=restore_clip
            )

            # Play success chime
            if self.config.get("sound_feedback", True):
                play_paste_sound()

            # Record in SQLite history
            self.db.add_history_entry(
                raw_text=raw_text,
                formatted_text=formatted,
                target_app=target_app,
                target_window=target_title,
                duration_seconds=duration_sec,
                word_count=word_count,
                tone_preset=tone,
                model_used=self.transcriber.model_size,
                device_used=self.transcriber.device,
                latency_ms=latency_ms
            )

            # Signal UI complete
            self.bridge.sig_transcription_complete.emit(formatted, word_count, latency_ms)

        except Exception as e:
            print(f"[OpenFlow] Error in processing worker: {e}")
            self.bridge.sig_error.emit("Something went wrong")
        finally:
            self._is_processing = False

    @pyqtSlot()
    def _handle_ui_start(self):
        if self.config.get("show_floating_pill", True):
            tone_name = self.config.get("tone_preset", "smart_clean").replace("_", " ").title()
            self.floating_pill.show_listening(tone_name)

    @pyqtSlot()
    def _handle_ui_stop(self):
        if self.config.get("show_floating_pill", True):
            self.floating_pill.show_processing()

    @pyqtSlot(str)
    def _handle_status(self, message: str):
        # status can arrive during startup, before the tray icon exists
        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.showMessage("OpenFlow", message, QSystemTrayIcon.MessageIcon.Information, 3000)
        print(f"[OpenFlow] {message}")

    @pyqtSlot(int, str)
    def _handle_ui_download(self, percent: int, model: str):
        self.main_window.set_download(percent, model)
        self.floating_pill.show_download(percent, model)

    @pyqtSlot(str)
    def _handle_ui_error(self, message: str):
        if self.config.get("show_floating_pill", True):
            # Short 850ms notice on empty speech / too short so the capsule doesn't stay lingering
            duration = 850 if message in ("Didn't catch that", "Too short", "No sound from mic") else 1800
            self.floating_pill.show_message(message, duration_ms=duration)

    @pyqtSlot(float)
    def _handle_ui_amplitude(self, level: float):
        if self.config.get("show_floating_pill", True):
            self.floating_pill.set_amplitude(level)

    @pyqtSlot(str)
    def _handle_ui_realtime_text(self, text: str):
        if self.config.get("show_floating_pill", True):
            self.floating_pill.update_realtime_text(text)

    @pyqtSlot(str, int, int)
    def _handle_ui_complete(self, text: str, words: int, latency: int):
        if self.config.get("show_floating_pill", True):
            self.floating_pill.show_pasted(words, latency)
        self.main_window.refresh_history()
        self.main_window.refresh_stats()

    def _on_update_available(self, version: str, rel_url: str, dl_url: str, notes: str):
        self.main_window.show_update_available(version, notes)
        self.floating_pill.show_update_available(version)
        self.tray.showMessage(
            "OpenFlow Update Available",
            f"Version {version} is available. Click to download and install.",
            QSystemTrayIcon.MessageIcon.Information,
            5000
        )

    def _on_no_update(self, version: str):
        self.main_window.show_up_to_date(version)
        self.tray.showMessage(
            "OpenFlow",
            f"OpenFlow is up to date (v{version}).",
            QSystemTrayIcon.MessageIcon.Information,
            2500
        )

    def _on_update_ready(self, installer_path: str):
        self.floating_pill.show_message("Update ready · Restarting...")
        self.tray.showMessage(
            "OpenFlow",
            "Update downloaded. Launching installer and restarting...",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )
        # Clean exit and launch installer after short pause to display notice
        QTimer.singleShot(1500, lambda: self.updater.install_and_restart(installer_path, silent=False))

    def _on_update_error(self, message: str):
        self.main_window.show_update_error(message)

    def quit_app(self):
        self.hotkey_mgr.stop()
        self.app.quit()

    def run(self):
        print(f"[OpenFlow] Started! Hold {hotkey_label(self.config)} anywhere to speak — release to paste.")
        # the capsule is the app; the dashboard opens only from the tray or the capsule menu
        self.floating_pill.show_message(f"OpenFlow Ready · Hold {hotkey_label(self.config)} to Speak", duration_ms=4500)
        sys.exit(self.app.exec())


SINGLE_INSTANCE_KEY = "openflow-single-instance"


def _already_running() -> bool:
    """Ask a running instance to show its dashboard; True if one answered."""
    sock = QLocalSocket()
    sock.connectToServer(SINGLE_INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        return True
    return False


class _LogTee:
    """Mirrors stdout/stderr into ~/.openflow/openflow.log (the installed exe has no console)."""

    encoding = "utf-8"

    def __init__(self, stream, fh):
        self._stream, self._fh = stream, fh

    def isatty(self):
        return False

    def write(self, s):
        try:
            self._fh.write(s)
            self._fh.flush()
        except Exception:
            pass
        if self._stream is not None:
            try:
                self._stream.write(s)
            except Exception:
                pass

    def flush(self):
        if self._stream is not None:
            try:
                self._stream.flush()
            except Exception:
                pass


def _setup_logging():
    try:
        d = os.path.join(os.path.expanduser("~"), ".openflow")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "openflow.log")
        if os.path.exists(path) and os.path.getsize(path) > 1_000_000:
            os.replace(path, path + ".old")
        fh = open(path, "a", encoding="utf-8", buffering=1)
        fh.write(f"\n--- OpenFlow {__version__} started {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        sys.stdout = _LogTee(sys.stdout, fh)
        sys.stderr = _LogTee(sys.stderr, fh)
    except Exception:
        pass


def _acquire_instance_lock():
    """Atomic single-instance lock (named Windows mutex). Returns (is_first, handle)."""
    if sys.platform != "win32":
        return True, None
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\OpenFlowSingleInstance")
    return ctypes.get_last_error() != 183, handle  # 183 = ERROR_ALREADY_EXISTS


def _ask_running_instance_to_show() -> bool:
    """The first copy may still be booting; retry for a while until its socket is up."""
    for _ in range(12):
        if _already_running():
            return True
        time.sleep(0.25)
    return False


def main():
    _setup_logging()
    qt_app = QApplication.instance() or QApplication(sys.argv)
    first, _mutex = _acquire_instance_lock()  # keep _mutex referenced for the process lifetime
    if not first:
        if _ask_running_instance_to_show():
            print("[OpenFlow] OpenFlow is already running in another window/process. Activated existing instance.")
            return
        print("[OpenFlow] Prior instance mutex detected but unresponsive; continuing startup.")


    # listen right away so a second launch during boot can already reach us
    holder = {}
    server = QLocalServer()
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)
    server.listen(SINGLE_INSTANCE_KEY)

    def on_second_launch():
        server.nextPendingConnection()
        app = holder.get("app")
        if app is not None:
            app.floating_pill.show_message(app._active_msg(), duration_ms=3500)

    server.newConnection.connect(on_second_launch)

    app = OpenFlowApp()
    holder["app"] = app
    app.run()


if __name__ == "__main__":
    main()
