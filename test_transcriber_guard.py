"""Silence and phrase loops must never reach the user as text."""
import numpy as np
from openflow.engine.transcriber import _has_speech, _loop_at, _drop_loop


def test_silence_and_steady_noise_are_not_speech():
    rng = np.random.default_rng(0)
    assert not _has_speech(np.zeros(16000 * 3, dtype=np.float32))
    assert not _has_speech((rng.standard_normal(16000 * 3) * 0.004).astype(np.float32))  # room hiss


def test_speech_burst_over_noise_is_speech():
    rng = np.random.default_rng(1)
    a = (rng.standard_normal(16000 * 3) * 0.004).astype(np.float32)
    a[16000:16000 + 8000] += (np.sin(np.arange(8000) * 0.1) * 0.2).astype(np.float32)  # half a second of voice
    assert _has_speech(a)


def test_loops_are_found_and_trimmed():
    assert _loop_at("Thank you. Thank you. Thank you. Thank you.") == 0
    assert _drop_loop("Thank you. Thank you. Thank you.") == ""          # only a loop: hallucination
    assert _drop_loop("send the file pura pura pura pura now") == "send the file pura"
    assert _drop_loop("this is a very very good plan") == "this is a very very good plan"  # real repeats stay
    assert _drop_loop("ok so one two three four five") == "ok so one two three four five"
