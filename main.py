import sys
import os
import threading
import time
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot, Qt, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor

from .config import load_config, save_config
from .database import Database
from .engine.audio_recorder import AudioRecorder
from .engine.transcriber import Transcriber
from .engine.formatter import TextFormatter
from .engine.injector import WindowInjector
from .engine.hotkey_manager import GlobalHotkeyManager
from .engine.sound_effects import play_start_sound, play_stop_sound, play_paste_sound
from .engine.context_detector import get_active_app_context, build_initial_prompt, AppContext
from .engine.refiner import LocalRefiner
from .engine.updater import AppUpdater
from .ui.floating_pill import FloatingPill, ui_font_family
from .ui.main_window import MainWindow
from .ui.setup_dialog import SetupDialog
from .autostart import set_autostart
from .engine import hardware
from . import __version__

_BOOT_T0 = time.perf_counter()


def _boot(msg: str):
    """Boot timeline in the log, so a slow start can be pinned on one phase."""
    print(f"[OpenFlow] boot +{time.perf_counter() - _BOOT_T0:5.1f}s  {msg}")


def create_tray_icon_pixmap() -> QPixmap:
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Cyan gradient circle
    painter.setBrush(QColor(255, 255, 255))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, 28, 28)

    # Inner mic capsule
    painter.setBrush(QColor(0, 0, 0))
    painter.drawRoundedRect(12, 8, 8, 12, 4, 4)
    painter.drawRect(15, 20, 2, 4)
    painter.drawRect(12, 23, 8, 2)
    painter.end()
    return pixmap


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


class OpenFlowApp(QObject):
    def __init__(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        super().__init__()
        self.app.setQuitOnLastWindowClosed(False)  # type: ignore[attr-defined]

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

        # Local text refiner — auto-selects model tier based on hardware
        # Runs in background thread; HUD progress shown via existing sig_download signal
        hw = hardware.detect()
        self.refiner = LocalRefiner(
            cuda_ok=hw["cuda_ok"],
            cpu_cores=hw["cpu_cores"],
            ram_gb=hw["ram_gb"],
            vram_gb=hw.get("vram_gb", 0.0),
            on_status=self.bridge.sig_status.emit,
            on_progress=self.bridge.sig_download.emit,
        )

        _boot("refiner created")
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
        self.floating_pill = FloatingPill(current_mic_name=initial_mic, current_language=self.config.get("language", "en"))
        self.floating_pill.sig_mic_changed.connect(self._on_capsule_mic_changed)
        self.floating_pill.sig_language_changed.connect(self._on_capsule_language_changed)
        self.floating_pill.sig_tone_changed.connect(self._on_capsule_tone_changed)
        self.floating_pill.sig_open_dashboard.connect(self.show_dashboard)

        _boot("capsule built")
        self.main_window = MainWindow(self.db, self.config)
        self.main_window.config_changed.connect(self._on_config_changed)
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

        # Housekeeping: detect sleep/resume, unload model when idle
        self._last_tick = self._last_activity = time.monotonic()
        self._housekeeping = QTimer(self)
        self._housekeeping.timeout.connect(self._housekeep)
        self._housekeeping.start(5000)

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self.app)
        self.tray.setIcon(QIcon(create_tray_icon_pixmap()))
        self.tray.setToolTip("OpenFlow — Hold Ctrl+Shift to Speak")

        menu = QMenu()
        act_hud = menu.addAction("Show Capsule HUD")
        act_hud.triggered.connect(lambda: self.floating_pill.show_message("OpenFlow Active · Hold Ctrl+Shift to Speak", duration_ms=3500))

        act_expand = menu.addAction("Capsule Settings (Expand HUD)")
        act_expand.triggered.connect(self.floating_pill.expand_to_hud)

        act_open = menu.addAction("Show Dashboard")
        act_open.triggered.connect(self.show_dashboard)

        act_update = menu.addAction("Check for Updates...")
        act_update.triggered.connect(lambda: self.updater.check_for_updates_async(notify_if_current=True))

        act_toggle = menu.addAction("Dictate Now")
        act_toggle.triggered.connect(self._toggle_dictation_manual)

        menu.addSeparator()
        tone_menu = menu.addMenu("Formatting Tone")
        for key, label in [
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
            self.floating_pill.show_message("OpenFlow Active · Hold Ctrl+Shift to Speak", duration_ms=3500)
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

    def _on_capsule_mic_changed(self, device_idx):
        self.config["input_device_index"] = device_idx
        save_config(self.config)
        self.audio_recorder.set_device(device_idx)
        friendly = self.audio_recorder.get_current_device_name()
        self.floating_pill.update_connected_mic(friendly)
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

    def _on_config_changed(self, new_cfg: dict):
        self.config = new_cfg
        self.hotkey_mgr.update_config(new_cfg.get("hotkey", "ctrl+shift"), new_cfg.get("trigger_mode", "push_to_talk"))
        self.audio_recorder.set_device(new_cfg.get("input_device_index"))
        set_autostart(new_cfg.get("autostart", False))
        self.audio_recorder.set_auto_silence_duration(float(new_cfg.get("silence_duration", 1.1)))
        self._reload_transcriber_async()
        self.formatter.set_dictionary(self.db.get_dictionary())

    IDLE_UNLOAD_SEC = 600

    def _housekeep(self):
        now = time.monotonic()
        if now - self._last_tick > 30:  # a 5s timer that slept >30s means system sleep/resume
            print("[OpenFlow] Resumed from sleep: restarting hotkey")
            self.hotkey_mgr.stop()
            self.hotkey_mgr.start()
        self._last_tick = now
        busy = self._is_processing or self.audio_recorder.is_recording
        if not busy and self.transcriber.model is not None and now - self._last_activity > self.IDLE_UNLOAD_SEC:
            print("[OpenFlow] Idle: unloading model")
            self.transcriber.unload()

    def _toggle_dictation_manual(self):
        if not self.audio_recorder.is_recording:
            self._start_dictating()
        else:
            self._stop_and_process()

    def _on_hotkey_press(self):
        mode = self.config.get("trigger_mode", "auto_silence")
        if mode == "push_to_talk":
            self._start_dictating()
        else: # "auto_silence" or "toggle"
            if not self.audio_recorder.is_recording:
                self._start_dictating()
            else:
                self._stop_and_process()

    def _on_hotkey_release(self):
        mode = self.config.get("trigger_mode", "auto_silence")
        if mode == "push_to_talk" and self.audio_recorder.is_recording:
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
        if not self.config.get("realtime_preview", True) or not self.audio_recorder.is_recording:
            return
        partial_text = self.transcriber.transcribe_partial(audio_chunk)
        if partial_text:
            self.bridge.sig_realtime_text.emit(partial_text)

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

        # 3. Process in worker thread
        threading.Thread(target=self._process_worker, args=(audio_data,), daemon=True).start()

    def _process_worker(self, audio_data):
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

            # Refresh dictionary
            self.formatter.set_dictionary(self.db.get_dictionary())
            dict_entries = self.db.get_dictionary()
            custom_vocab = [e["replace_with"] for e in dict_entries]  # preferred spellings

            # Build context-aware initial_prompt for vocabulary biasing
            lang = self.config.get("language", "auto")
            initial_prompt = build_initial_prompt(
                context=self._app_context,
                custom_vocab=custom_vocab,
                language=lang,
            )
            if initial_prompt:
                print(f"[OpenFlow] Prompt ({len(initial_prompt)} chars): {initial_prompt[:80]}...")

            # Transcribe full audio with Whisper GPU
            raw_text, duration_sec, latency_ms, detected_lang = self.transcriber.transcribe(
                audio_data,
                language=lang,
                initial_prompt=initial_prompt,
            )

            if not raw_text.strip():
                self.bridge.sig_error.emit("Didn't catch that")
                return

            # Format speech (clean fillers, dev syntax, email, etc.)
            tone = self.config.get("tone_preset", "smart_clean")

            # Stage 1: Local SLM refiner — self-corrections, filler removal, punctuation
            # Falls back to raw_text automatically if LLM is not ready or too slow
            if self.refiner.is_ready and tone != "verbatim":
                refined_text = self.refiner.refine(raw_text)
            else:
                refined_text = raw_text

            # Stage 2: Regex formatter — developer syntax, email structure, bullet points
            formatted = self.formatter.format(refined_text, tone_preset=tone, language=detected_lang)
            word_count = len(formatted.split())

            # Automatically write text into the target window
            target_hwnd = self.target_window_info.get("hwnd", 0)
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
                target_app=self.target_window_info.get("process", ""),
                target_window=self.target_window_info.get("title", ""),
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
            self.floating_pill.show_message(message)

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
        print("[OpenFlow] Started! Hold Ctrl+Shift anywhere to speak — release to paste.")
        # Immediately display the floating capsule HUD so user sees OpenFlow is ready
        self.floating_pill.show_message("OpenFlow Ready · Hold Ctrl+Shift to Speak", duration_ms=4500)
        self.tray.showMessage(
            "OpenFlow Ready",
            "Hold CTRL + SHIFT anywhere to speak. Release to write instantly!",
            QSystemTrayIcon.MessageIcon.Information,
            3500
        )
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
            app.floating_pill.show_message("OpenFlow Active \u00b7 Hold Ctrl+Shift to Speak", duration_ms=3500)
            app.show_dashboard()

    server.newConnection.connect(on_second_launch)

    app = OpenFlowApp()
    holder["app"] = app
    if "--background" not in sys.argv:  # opened by hand (not at sign-in): show the dashboard
        QTimer.singleShot(400, app.show_dashboard)
    app.run()


if __name__ == "__main__":
    main()
