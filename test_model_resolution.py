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


def test_odia_routes_to_indicconformer():
    from openflow.engine import transcriber as tr
    assert tr.resolve_model_name("odia", "or") == "odia"
    assert tr.resolve_model_name("odia", "en") == "base"  # other languages keep Whisper
    assert tr.resolve_model_name("small", "or") == "odia"  # Odia speech never goes to Whisper
    assert tr.resolve_model_name("small", "or-en") == "odia"
    assert tr.resolve_model_name("small", "or-mix") == "odia"

    assert tr.engine_model_name("odia", "or", "npu") == "odia"  # never an "-ov" build
    assert mm.variants("odia") == ["odia"]
    assert mm._weights_file("odia") == "or/model.onnx"


def test_hung_gpu_call_falls_back_to_cpu():
    import threading
    import time
    import numpy as np
    from openflow.engine import transcriber as tr

    stuck = threading.Event()

    class HungModel:  # a CUDA encode that never returns, as seen in the field
        def transcribe(self, audio, **kw):
            stuck.wait()
            return [], None

    class CpuModel:
        def transcribe(self, audio, **kw):
            return [type("S", (), {"text": "hello"})()], None

    t = tr.Transcriber(preload=False)
    t.device = "cuda"
    t.model, t._current_loaded_name, t._loaded_device = HungModel(), "small", "cuda"
    t._target = lambda lang: "small"

    def load():
        t.model, t._current_loaded_name, t._loaded_device = CpuModel(), "small", t.device
    t._load_model_locked = load
    real_hung = tr._HUNG_S
    tr._HUNG_S = 0.2
    try:
        threading.Thread(target=t.transcribe_partial, args=(np.zeros(16000, np.float32),), daemon=True).start()
        time.sleep(0.05)
        session = tr.StreamingSession(t, "en", None)
        text = session.finish(np.zeros(32000, np.float32))[0]
    finally:
        tr._HUNG_S = real_hung
        stuck.set()
    assert text == "hello" and t.device == "cpu", (text, t.device)


def test_word_lm_picks_the_real_word():
    import os
    import tempfile
    import numpy as np
    from openflow.engine import indic_asr as ia

    vocab = ["▁କ", "ା", "ମ", "▁ଭ", "ଲ"]  # blank = 5
    words = ["ଭଲ", "କାମ"]
    path = os.path.join(tempfile.mkdtemp(), "lm.npz")
    np.savez(path, words="\n".join(words), uni=np.log([0.5, 0.5]).astype(np.float16),
             bi_keys=np.array([(0 << 22) | 1], np.int64), bi=np.log([0.9]).astype(np.float16), unk=-20.0)
    lm = ia.WordLM(path)

    def frames(*rows):  # each row: {token: prob}, the rest to blank
        out = np.full((len(rows), 6), 1e-6)
        for i, r in enumerate(rows):
            for t, p in r.items():
                out[i, t] = p
            out[i, 5] = max(1e-6, 1 - sum(r.values()))
        return np.log(out / out.sum(1, keepdims=True)).astype(np.float32)

    # "ଭଲ କ?ମ": the acoustics slightly prefer no vowel sign (କମ, unknown); the LM knows କାମ
    lp = frames({3: 0.9}, {4: 0.9}, {0: 0.9}, {1: 0.45}, {2: 0.9})
    assert ia.ctc_greedy(lp.argmax(-1), vocab) == "ଭଲ କମ"
    assert ia.ctc_beam_lm(lp, vocab, lm, alpha=0.5, beta=1.0) == "ଭଲ କାମ"
    assert ia.ctc_beam_lm(lp, vocab, lm, alpha=0.0, beta=0.0) == "ଭଲ କମ"


def test_odia_mix_keeps_odia_words():
    from openflow.engine.odia_mix import to_mixed
    assert to_mixed("ବିଜନେସ ଫ୍ରେଣ୍ଡଲି ନଥିଲା ଆଉ ମୋର ଫୁଲ ଅଫ ଦ ୱର୍ଲ୍ଡ") == "business friendly ନଥିଲା ଆଉ ମୋର ଫୁଲ of the world"
