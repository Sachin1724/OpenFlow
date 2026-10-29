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


def odia_only(vocab: list) -> np.ndarray:
    """Additive mask: 0 for Odia pieces and blank, -inf for the other scripts in the shared Indic vocab."""
    ok = [all(c == "▁" or 0x0B00 <= ord(c) <= 0x0B7F for c in p) and p != "<unk>" for p in vocab] + [True]
    return np.where(ok, 0.0, -np.inf).astype(np.float32)


class WordLM:
    """Odia word bigram LM with stupid backoff (build_odia_lm.py), in plain numpy.
    Bigrams are int64 keys (w1 << 22 | w2) sorted for np.searchsorted; scores are natural logs."""

    BACKOFF = float(np.log(0.4))

    def __init__(self, path: str):
        d = np.load(path, allow_pickle=False)
        self.words = {w: i for i, w in enumerate(str(d["words"]).split("\n"))}
        self.uni = d["uni"].astype(np.float32)
        self.keys, self.bi = d["bi_keys"], d["bi"].astype(np.float32)
        self.unk = float(d["unk"])
        self._cache = {}

    def score(self, prev: str, word: str) -> float:
        k = (prev, word)
        if k not in self._cache:
            w = self.words.get(word)
            if w is None:
                s = self.unk
            else:
                s = self.BACKOFF + float(self.uni[w])
                p = self.words.get(prev)
                if p is not None:
                    key = (p << 22) | w
                    i = int(np.searchsorted(self.keys, key))
                    if i < len(self.keys) and self.keys[i] == key:
                        s = float(self.bi[i])
            self._cache[k] = s
        return self._cache[k]


def ctc_beam_lm(logp: np.ndarray, vocab: list, lm: WordLM, alpha: float = 0.5, beta: float = 1.0,
                beam: int = 16, prune: float = -8.0) -> str:
    """CTC prefix beam search; each finished word adds alpha * log P(word | previous word) + beta."""
    blank = len(vocab)
    NEG = -1e30
    # prefix (tuple of token ids) -> [log p_blank, log p_nonblank]; info -> (lm total, prev word, current word)
    beams = {(): [0.0, NEG]}
    info = {(): (0.0, "<s>", "")}

    def extend(prefix, c):
        new = prefix + (c,)
        if new not in info:
            lm_total, prev, cur = info[prefix]
            piece = vocab[c]
            if piece.startswith("▁"):
                if cur:
                    lm_total += alpha * lm.score(prev, cur) + beta
                    prev = cur
                cur = piece[1:]
            else:
                cur += piece
            info[new] = (lm_total, prev, cur)
        return new

    for row in logp:
        cand = [c for c in np.nonzero(row > prune)[0].tolist() if c != blank]
        nxt = {}
        for prefix, (pb, pnb) in beams.items():
            total = np.logaddexp(pb, pnb)
            e = nxt.setdefault(prefix, [NEG, NEG])
            e[0] = np.logaddexp(e[0], total + row[blank])
            last = prefix[-1] if prefix else -1
            for c in cand:
                p = row[c]
                new = extend(prefix, c)
                e2 = nxt.setdefault(new, [NEG, NEG])
                if c == last:
                    e2[1] = np.logaddexp(e2[1], pb + p)                   # c, blank, c: a new symbol
                    nxt[prefix][1] = np.logaddexp(nxt[prefix][1], pnb + p)  # repeat collapses
                else:
                    e2[1] = np.logaddexp(e2[1], total + p)
        beams = dict(sorted(nxt.items(), key=lambda kv: -(np.logaddexp(*kv[1]) + info[kv[0]][0]))[:beam])

    def final(prefix):
        lm_total, prev, cur = info[prefix]
        return np.logaddexp(*beams[prefix]) + lm_total + (alpha * lm.score(prev, cur) + beta if cur else 0)
    best = max(beams, key=final)
    return "".join(vocab[c] for c in best).replace("▁", " ").strip()


class IndicCTC:
    """One IndicConformer language folder (model.onnx + vocab.json, and lm.npz for beam search)."""

    # tuned on FLEURS Odia dev; on the 883 test clips WER 21.1% -> 20.1%, CER 5.8% -> 5.5%
    ALPHA, BETA, BEAM = 0.15, 1.0, 16

    def __init__(self, folder: str, threads: int = 4):
        import onnxruntime as ort
        with open(os.path.join(folder, "vocab.json"), encoding="utf-8") as f:
            self.vocab = json.load(f)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        avail = ort.get_available_providers()
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
        self.sess = ort.InferenceSession(os.path.join(folder, "model.onnx"), opts, providers=providers)
        lm_path = os.path.join(folder, "lm.npz")
        self.lm = WordLM(lm_path) if os.path.exists(lm_path) else None  # absent: greedy, as before
        self.mask = odia_only(self.vocab)

    def text(self, audio: np.ndarray, beam: bool = True) -> str:
        """beam=False is the greedy pass the live preview uses (~5 ms instead of ~80 ms)."""
        if len(audio) < 1600:  # under 0.1 s
            return ""
        x = features(audio)[None].astype(np.float32)
        out = self.sess.run(None, {"audio_signal": x, "length": np.array([x.shape[2]], dtype=np.int64)})
        logits = np.asarray(out[0])[0]
        logits = logits + self.mask
        if beam and self.lm is not None:
            return ctc_beam_lm(logits, self.vocab, self.lm, self.ALPHA, self.BETA, self.BEAM)
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
