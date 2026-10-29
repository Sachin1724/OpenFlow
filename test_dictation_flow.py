"""Self-check for the hotkey -> record -> write flow: python -m openflow.test_dictation_flow (from the repo's parent)."""
import threading
import time
from types import SimpleNamespace

import numpy as np

from openflow.main import OpenFlowApp


class _Recorder:
    def __init__(self):
        self.is_recording = False

    def stop_recording(self):
        self.is_recording = False
        return np.zeros(16000, np.float32)


def _app(worker):
    app = OpenFlowApp.__new__(OpenFlowApp)  # skip the Qt/model setup; only the flow logic runs
    errors = []
    app.config = {"trigger_mode": "push_to_talk", "auto_write_on_silence": False}
    app.audio_recorder = _Recorder()
    app.hotkey_mgr = SimpleNamespace(_is_active=True)
    app.bridge = SimpleNamespace(sig_error=SimpleNamespace(emit=errors.append),
                                 sig_stop_recording=SimpleNamespace(emit=lambda: None))
    app._is_processing, app._job, app._stream_session = False, 0, None
    app._dictation_lock = threading.RLock()

    def start():
        app._dictate_start_monotonic = time.monotonic()
        app.audio_recorder.is_recording = True
    app._start_dictating = start
    app._process_worker = worker
    return app, errors


def test_tap_is_discarded():
    app, errors = _app(lambda *a: None)
    app._on_hotkey_press()
    app._on_hotkey_release()
    assert not app.audio_recorder.is_recording and not app._is_processing and errors == ["Hold to speak"]


def test_released_while_mic_opened():
    app, errors = _app(lambda *a: None)
    app.hotkey_mgr._is_active = False
    app._on_hotkey_press()
    assert not app.audio_recorder.is_recording and errors == ["Hold to speak"]


def test_hold_writes_and_stuck_worker_times_out():
    hang = threading.Event()
    app, errors = _app(lambda audio, session, job: hang.wait())
    app._on_hotkey_press()
    app._dictate_start_monotonic -= 1  # held for a second
    real_timer = threading.Timer
    threading.Timer = lambda secs, fn: real_timer(0.05, fn)  # don't wait the real 20 s
    try:
        app._on_hotkey_release()
        assert app._is_processing
        time.sleep(0.3)
    finally:
        threading.Timer = real_timer
        hang.set()
    assert not app._is_processing and errors == ["Took too long · try again"] and app._job == 2


if __name__ == "__main__":
    test_tap_is_discarded()
    test_released_while_mic_opened()
    test_hold_writes_and_stuck_worker_times_out()
    print("ok")
