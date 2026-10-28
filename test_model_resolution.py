"""Self-check: a cached base.en counts as "base", so auto never picks a bigger model to download.
Run from the repo's parent: python -m openflow.test_model_resolution"""
from openflow.engine import hardware, model_manager as mm


def test_only_base_en_cached():
    real = mm.cached_path
    mm.cached_path = lambda name: "/fake/base.en" if name == "base.en" else None
    try:
        assert mm.variants("base") == ["base", "base.en"]
        assert mm.variants("parakeet") == ["parakeet"]
        assert mm.is_model_downloaded("base")
        assert not mm.is_model_downloaded("small")
        assert mm.list_downloaded_models() == ["base"]
        assert mm.any_cached_path("base") == "/fake/base.en"
        assert hardware.resolve({"model_size": "auto", "device": "cpu"})["model_size"] == "base"
    finally:
        mm.cached_path = real


def test_slow_preview_turns_itself_off():
    import time
    import numpy as np
    from openflow.engine import transcriber as tr

    class SlowModel:
        calls = 0
        def transcribe(self, audio, **kw):
            SlowModel.calls += 1
            time.sleep(tr._PREVIEW_BUDGET_S + 0.05)
            return [], None

    t = tr.Transcriber(preload=False)
    t.model = SlowModel()
    audio = np.zeros(16000, np.float32)
    t.transcribe_partial(audio)
    t.transcribe_partial(audio)
    assert SlowModel.calls == 1, "slow preview kept running and would delay the final text"
    assert tr._THREADS >= 2


def test_streaming_cuts_at_pauses():
    import numpy as np
    from openflow.engine import transcriber as tr
    loud, gap = np.full(16000 * 3, 0.1, np.float32), np.zeros(16000, np.float32)
    audio = np.concatenate([loud, gap, loud])  # 3 s speech, 1 s pause, 3 s speech
    cut = tr.find_pause(audio, 0)
    assert 16000 * 3 < cut < 16000 * 4, cut               # inside the pause
    assert tr.find_pause(audio[:16000 * 3], 0) is None    # too little pending audio
    assert tr.find_pause(np.concatenate([loud, loud]), 0) is None  # no pause, no cut

    class Fake:
        def transcribe(self, audio, language=None, initial_prompt=None):
            return f"<{len(audio) // 16000}s>", 0, 0, "en"
    s = tr.StreamingSession(Fake(), "en", None)
    s.feed(audio)
    text, dur, _, _ = s.finish(audio)
    assert text == "<3s> <3s>" and dur == 7.0, text


if __name__ == "__main__":
    test_streaming_cuts_at_pauses()
    test_only_base_en_cached()
    test_slow_preview_turns_itself_off()
    print("ok")
