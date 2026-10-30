"""Engine child process: starts on demand, answers calls, is fully released by unload()."""
import os
import numpy as np
import psutil
from engine.remote_transcriber import RemoteTranscriber


def test_engine_process_lifecycle():
    t = RemoteTranscriber("base.en", "cpu", "int8", "en")
    assert t.model is None and not t._alive()
    assert t.transcribe_partial(np.zeros(16000, dtype=np.float32)) == ""  # no model: no process started
    assert not t._alive()
    t._call("reset_preview_budget", (), 60)  # forces the spawn and one round trip
    pid = t._proc.pid
    assert t._alive() and pid != os.getpid()
    print(f"engine child {psutil.Process(pid).memory_info().rss >> 20} MB, app {psutil.Process().memory_info().rss >> 20} MB")
    t.unload()
    assert not psutil.pid_exists(pid) and t.model is None
    t._call("reset_preview_budget", (), 60)  # respawns cleanly after unload
    assert t._proc.pid != pid
    t.unload()


if __name__ == "__main__":
    test_engine_process_lifecycle()
    print("ok")
