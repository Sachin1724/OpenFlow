"""Self-check for the NPU engine path: python -m openflow.test_npu_engine (from the repo's parent).
Runs the same OpenVINO pipeline on the CPU device so it works on PCs without an NPU.
Downloads whisper-tiny-int8-ov (~40 MB) on first run."""
import numpy as np

from openflow.engine import hardware, transcriber as tr


def test_names_and_resolve():
    assert tr.engine_model_name("base", "en", "npu") == "base-ov"
    assert tr.engine_model_name("small", "hi", "npu") == "small-ov"
    assert tr.engine_model_name("parakeet", "en", "npu") == "parakeet"
    assert tr.engine_model_name("base", "en", "cpu") == "base.en"
    if not hardware.npu_name():  # explicit NPU on a PC without one must fall back, not crash
        assert hardware.resolve({"device": "npu", "model_size": "base"})["device"] in ("cuda", "cpu")


def test_pipeline_on_cpu_device(wav=None):
    real = tr._OpenVINOWhisper.__init__
    tr._OpenVINOWhisper.__init__ = lambda self, path, device="NPU": real(self, path, "CPU")
    try:
        t = tr.Transcriber(model_size="tiny", device="npu", compute_type="int8", language="en", preload=True)
        assert t._current_loaded_name == "tiny-ov", t._current_loaded_name
        silence = np.zeros(16000 * 2, np.float32)
        assert t.transcribe(silence)[0] == ""  # VAD drops silence instead of hallucinating "you"
        if wav is not None:
            text = t.transcribe(wav)[0].lower()
            assert "hello" in text and "test" in text, text
    finally:
        tr._OpenVINOWhisper.__init__ = real


if __name__ == "__main__":
    import sys, wave
    audio = None
    if len(sys.argv) > 1:  # optional 16 kHz mono 16-bit wav with "hello ... test" in it
        with wave.open(sys.argv[1]) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    test_names_and_resolve()
    test_pipeline_on_cpu_device(audio)
    print("ok")
