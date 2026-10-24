import threading
import sys

def _play_tone_sync(freq: int, duration_ms: int):
    try:
        if sys.platform == "win32":
            import winsound
            winsound.Beep(freq, duration_ms)
    except Exception:
        pass


def play_start_sound():
    def _run():
        # Pleasant ascending two-tone chime (F#5 -> A5)
        _play_tone_sync(740, 70)
        _play_tone_sync(880, 90)
    threading.Thread(target=_run, daemon=True).start()


def play_stop_sound():
    def _run():
        # Soft single tone acknowledging stop
        _play_tone_sync(600, 80)
    threading.Thread(target=_run, daemon=True).start()


def play_paste_sound():
    def _run():
        # Quick crisp triple chime on successful paste completion (A5 -> C#6 -> E6)
        _play_tone_sync(880, 50)
        _play_tone_sync(1108, 60)
        _play_tone_sync(1318, 80)
    threading.Thread(target=_run, daemon=True).start()
