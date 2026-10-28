"""
indic_asr.py — Odia speech-to-text with AI4Bharat IndicConformer (CTC, ONNX)
============================================================================
Whisper has no Odia token, so Odia drifts into Bengali or Latin script. This runs
AI4Bharat's Odia IndicConformer (~120M params, CC-BY-4.0) through onnxruntime,
which faster-whisper already installs: no torch, no librosa.

Features follow the model card exactly: pre-emphasis 0.97, 80 Slaney log-mels
(n_fft 512, hop 160, win 400), per-bin normalisation, greedy CTC decode.
"""

import json
import os
import numpy as np

SR, N_FFT, HOP, WIN, N_MELS = 16000, 512, 160, 400, 80


def _hz_to_mel(f):
    f = np.asarray(f, dtype=np.float64)
    m = f / (200.0 / 3)
    log = f >= 1000.0
    return np.where(log, 15.0 + np.log(np.maximum(f, 1e-10) / 1000.0) / (np.log(6.4) / 27.0), m)


def _mel_to_hz(m):
    m = np.asarray(m, dtype=np.float64)
    f = m * (200.0 / 3)
    log = m >= 15.0
    return np.where(log, 1000.0 * np.exp((np.log(6.4) / 27.0) * (m - 15.0)), f)


def mel_filters(sr=SR, n_fft=N_FFT, n_mels=N_MELS, fmin=0.0, fmax=8000.0) -> np.ndarray:
    """Slaney mel filterbank, same as librosa.filters.mel(norm='slaney', htk=False)."""
    hz = _mel_to_hz(np.linspace(_hz_to_mel(fmin), _hz_to_mel(fmax), n_mels + 2))
    ramps = hz[:, None] - np.linspace(0, sr / 2, 1 + n_fft // 2)[None, :]
    fdiff = np.diff(hz)
    lower = -ramps[:-2] / fdiff[:-1, None]
    upper = ramps[2:] / fdiff[1:, None]
    w = np.maximum(0, np.minimum(lower, upper))
    return (w * (2.0 / (hz[2:] - hz[:-2]))[:, None]).astype(np.float32)


_FILTERS = mel_filters()
_WINDOW = np.zeros(N_FFT, dtype=np.float32)  # periodic Hann of 400, centred in 512 (librosa's padding)
_WINDOW[(N_FFT - WIN) // 2:(N_FFT - WIN) // 2 + WIN] = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(WIN) / WIN)


def features(audio: np.ndarray) -> np.ndarray:
    """float32 16 kHz mono -> normalised log-mel [80, T]."""
    y = audio.astype(np.float32, copy=False)
    y = np.append(y[:1], y[1:] - 0.97 * y[:-1])
    y = np.pad(y, N_FFT // 2)  # center=True, zero padding
    n = 1 + (len(y) - N_FFT) // HOP
    frames = y[np.arange(N_FFT)[None, :] + HOP * np.arange(n)[:, None]] * _WINDOW
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    logmel = np.log(_FILTERS @ power.T + 2 ** -24)
    return (logmel - logmel.mean(1, keepdims=True)) / (logmel.std(1, ddof=1, keepdims=True) + 1e-5)


def ctc_greedy(ids: np.ndarray, vocab: list) -> str:
    """Collapse repeats, drop blanks (blank = len(vocab)), '▁' marks word starts."""
    blank, out, prev = len(vocab), [], -1
    for t in ids:
        t = int(t)
        if t != prev and t < blank:
            out.append(vocab[t])
        prev = t
    return "".join(out).replace("▁", " ").strip()


class IndicCTC:
    """One IndicConformer language folder (model.onnx + vocab.json)."""

    def __init__(self, folder: str, threads: int = 4):
        import onnxruntime as ort
        with open(os.path.join(folder, "vocab.json"), encoding="utf-8") as f:
            self.vocab = json.load(f)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        avail = ort.get_available_providers()
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
        self.sess = ort.InferenceSession(os.path.join(folder, "model.onnx"), opts, providers=providers)

    def text(self, audio: np.ndarray) -> str:
        if len(audio) < 1600:  # under 0.1 s
            return ""
        x = features(audio)[None].astype(np.float32)
        logits = self.sess.run(None, {"audio_signal": x, "length": np.array([x.shape[2]], dtype=np.int64)})[0][0]
        return ctc_greedy(logits.argmax(-1), self.vocab)


if __name__ == "__main__":
    # Self-check: CTC collapse rules, and features match librosa when it happens to be installed.
    assert ctc_greedy(np.array([0, 0, 3, 1, 1, 3, 2]), ["▁କ", "ା", "ମ"]) == "କାମ"
    audio = np.random.default_rng(0).standard_normal(16000).astype(np.float32) * 0.1
    f = features(audio)
    assert f.shape == (80, 101), f.shape
    try:
        import librosa
        ref = librosa.feature.melspectrogram(y=np.append(audio[:1], audio[1:] - 0.97 * audio[:-1]), sr=SR,
                                             n_fft=N_FFT, hop_length=HOP, win_length=WIN, n_mels=N_MELS,
                                             fmin=0, fmax=8000, norm="slaney", power=2.0)
        ref = np.log(ref + 2 ** -24)
        ref = (ref - ref.mean(1, keepdims=True)) / (ref.std(1, ddof=1, keepdims=True) + 1e-5)
        assert np.abs(ref - f).max() < 1e-3, np.abs(ref - f).max()
        print("features match librosa")
    except ImportError:
        print("librosa not installed; skipped feature comparison")
    print("ok")
