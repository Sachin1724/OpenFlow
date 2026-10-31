import os
import re
import time
import threading
import gc
import contextlib
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from typing import Tuple, Optional


ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def contains_arabic_script(text: str) -> bool:
    """Returns True if the string contains any Perso-Arabic/Urdu unicode characters."""
    return bool(ARABIC_SCRIPT_RE.search(text))


_ARABIC_CHAR_MAP = {
    '\u0627': 'a', '\u0622': 'aa', '\u0628': 'b', '\u067e': 'p', '\u062a': 't', '\u0679': 't', '\u062b': 's',
    '\u062c': 'j', '\u0686': 'ch', '\u062d': 'h', '\u062e': 'kh', '\u062f': 'd', '\u0688': 'd', '\u0630': 'z',
    '\u0631': 'r', '\u0691': 'r', '\u0632': 'z', '\u0698': 'zh', '\u0633': 's', '\u0634': 'sh', '\u0635': 's',
    '\u0636': 'z', '\u0637': 't', '\u0638': 'z', '\u0639': 'a', '\u063a': 'gh', '\u0641': 'f', '\u0642': 'q',
    '\u06a9': 'k', '\u0643': 'k', '\u06af': 'g', '\u0644': 'l', '\u0645': 'm', '\u0646': 'n', '\u06ba': 'n',
    '\u0648': 'o', '\u06c1': 'h', '\u06be': 'h', '\u0629': 'h', '\u0649': 'y', '\u064a': 'y', '\u06cc': 'i',
    '\u06d2': 'e', '\u0626': 'e', '\u0621': '', '\u064b': 'an', '\u064c': 'un', '\u064d': 'in', '\u064e': 'a',
    '\u064f': 'u', '\u0650': 'i', '\u0651': '', '\u0652': '',
}


def clean_arabic_script(text: str) -> str:
    """Safely transliterate any residual Perso-Arabic/Urdu script to Latin letters."""
    if not text or not contains_arabic_script(text):
        return text
    converted = ''.join(_ARABIC_CHAR_MAP.get(c, c) for c in text)
    return re.sub(r'\s+', ' ', converted).strip()


class _LazyFW:
    """faster_whisper pulls in ctranslate2 (several seconds); import it only when a model loads."""

    def __getattr__(self, name):
        import faster_whisper as fw
        return getattr(fw, name)


faster_whisper = _LazyFW()

from . import model_manager


class _OpenVINOWhisper:
    """Whisper on the Intel NPU via openvino_genai, shaped like faster_whisper.WhisperModel
    (transcribe() -> (segments, info)) so the rest of Transcriber stays the same."""

    def __init__(self, model_path: str, device: str = "NPU"):
        import openvino_genai
        cache = Path.home() / ".openflow" / "cache" / "openvino"  # NPU compiles once; later loads are fast
        cache.mkdir(parents=True, exist_ok=True)
        self._pipe = openvino_genai.WhisperPipeline(model_path, device, CACHE_DIR=str(cache))

    def transcribe(self, audio: np.ndarray, language=None, task="transcribe", initial_prompt=None,
                   vad_filter=False, **_ignored):
        if vad_filter:  # same Silero VAD faster-whisper uses; without it silence comes out as "you"
            from faster_whisper.vad import get_speech_timestamps, VadOptions
            spans = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=300, threshold=0.65))
            if not spans:
                return [], SimpleNamespace(language=language or "")
            audio = np.concatenate([audio[c["start"]:c["end"]] for c in spans])
        kw = {"task": task}
        if language:
            kw["language"] = f"<|{language}|>"
        if initial_prompt:
            kw["initial_prompt"] = initial_prompt
        res = self._pipe.generate(audio.astype(np.float32, copy=False), **kw)
        return [SimpleNamespace(text=t) for t in res.texts], SimpleNamespace(language=language or "")


# Languages NVIDIA Parakeet V3 knows; anything else (Hindi, auto-detect, translate...) goes to Whisper.
PARAKEET_LANGS = {
    "en", "en-in", "bg", "hr", "cs", "da", "nl", "et", "fi", "fr", "de", "el", "hu", "it",
    "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk",
}


# Settings that mean Odia speech; the "odia" model runs AI4Bharat IndicConformer for these.
ODIA_LANGS = {"or", "odia", "or-en", "or-mix"}  # "or-en": main.py translates to English; "or-mix": English words in English letters


def resolve_model_name(base_model: str, language: str) -> str:
    """English (US/UK) -> fast .en model. Indian English, multilingual, auto, or regional -> multilingual model."""
    if language in ODIA_LANGS:  # Whisper has no Odia: it writes Bengali or romanised gibberish
        return "odia"
    if base_model == "parakeet":
        return "parakeet" if language in PARAKEET_LANGS else "base"
    if base_model == "odia":
        return "odia" if language in ODIA_LANGS else "base"
    clean = base_model.replace(".en", "")
    if clean.startswith("distil"):  # distilled models are English-only
        return clean if language == "en" else "medium"
    if language == "en":
        return f"{clean}.en" if clean in ["tiny", "base", "small", "medium"] else clean
    # For en-in, auto, hi, etc., use the multilingual model directly (base, small, medium)
    return clean



def engine_model_name(base_model: str, language: str, device: str) -> str:
    """Model files to load: the NPU runs OpenVINO builds of the multilingual weights ("base-ov")."""
    name = resolve_model_name(base_model, language)
    if device == "npu" and name not in ("parakeet", "odia"):  # ONNX engines stay on the CPU
        name = name.replace(".en", "") + "-ov"
    return name


def _physical_cores() -> int:
    try:
        import psutil
        return psutil.cpu_count(logical=False) or (os.cpu_count() or 4) // 2
    except Exception:
        return (os.cpu_count() or 4) // 2


# One thread per physical core: hyperthreads add nothing to int8 matmuls, while a 4-core/4-thread
# laptop got only 2 threads under the old "half the logical cores" rule (2 -> 4 threads: -35% latency).
_THREADS = min(8, max(2, _physical_cores()))
# A preview still decoding when the key is released makes the final pass wait for it
# (base on 2 cores: 1.8 s -> 3.3 s). Slower previews than this switch themselves off.
_PREVIEW_BUDGET_S = 0.4
_HUNG_S = 10.0  # a model call holding the lock this long never comes back (seen with CUDA)


def _whisper_args(lang: str) -> dict:
    """Maps an OpenFlow language setting to faster-whisper language/task arguments."""
    if lang == "translate":  # speak any language, get English text
        return {"language": None, "task": "translate"}
    if lang in ("auto", "") or lang in ODIA_LANGS:  # Odia runs via auto-detect + prompt biasing since Whisper has no 'or' token
        return {"language": None, "task": "transcribe"}
    return {"language": "en" if lang == "en-in" else lang, "task": "transcribe"}


def _too_many_words(text: str, seconds: float) -> bool:
    return len(text.split()) > 4 * seconds + 3


def _has_speech(audio: np.ndarray) -> bool:
    """False only for clear non-speech: silence or a dead microphone, and steady low-level noise (hiss, hum).
    Deliberately conservative: quiet speech must always pass (it has loud and soft moments; steady noise does not),
    and anything doubtful goes on to the model, whose own voice detector decides."""
    n = 320  # 20 ms frames
    if len(audio) < n * 4 or float(np.abs(audio).max()) < 0.003:  # shorter than 80 ms, or nothing above -50 dBFS
        return False
    rms = np.sqrt((audio[: len(audio) // n * n].reshape(-1, n) ** 2).mean(axis=1))
    loud, soft = float(np.percentile(rms, 95)), float(np.percentile(rms, 10))
    return not (loud < 0.02 and loud < 3.0 * soft)  # quiet AND flat: noise, not a voice


def _loop_at(text: str):
    """Word index where a repeated phrase starts looping (a word 4x, a 2-4 word phrase 3x in a row), else None."""
    w = [re.sub(r"\W+", "", x.lower()) for x in text.split()]
    for i in range(len(w)):
        for size in (1, 2, 3, 4):
            reps = 4 if size == 1 else 3
            chunk = w[i:i + size]
            if all(chunk) and len(chunk) == size and all(w[i + k * size:i + (k + 1) * size] == chunk for k in range(reps)):
                return i
    return None


def _drop_loop(text: str) -> str:
    """Keeps the words before a loop plus its first pass; a text that is only a loop is a hallucination: ''."""
    at = _loop_at(text)
    if at is None:
        return text
    if at == 0:
        return ""
    words = text.split()
    w = [re.sub(r"\W+", "", x.lower()) for x in words]
    size = next(sz for sz in (1, 2, 3, 4) if w[at:at + sz] and w[at:at + sz] == w[at + sz:at + 2 * sz])
    return " ".join(words[:at + size]).strip()


class Transcriber:
    def __init__(self, model_size: str = "base.en", device: str = "cuda", compute_type: str = "float16", language: str = "en", preload: bool = True):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.model: Optional["faster_whisper.WhisperModel"] = None
        self._current_loaded_name = ""
        self._substitute = {}           # wanted model -> downloaded model used instead (no auto-download)
        self._lock = threading.RLock()  # model swaps must not race transcription
        self._abandon_guard = threading.Lock()
        self._holder_loading = False
        self.on_status = None           # optional callback(str) for "downloading/ready" messages
        self._loaded_device = ""
        self._preview_slow = False      # this model/device can't preview without delaying the final text
        self._slow_preview_streak = 0
        self.on_progress = None         # optional callback(percent:int, model_name:str) while downloading
        self.is_loading = False
        if preload:
            self._load_model()

    def _load_model(self):
        if getattr(self, "is_loading", False):
            return
        self.is_loading = True
        try:
            with self._locked():
                self._holder_loading = True  # a download can hold the lock for minutes; that's no hang
                try:
                    self._load_model_locked()
                finally:
                    self._holder_loading = False
        finally:
            self.is_loading = False

    def _target(self, language: str) -> str:
        return engine_model_name(self.model_size, language, self.device)


    def _warmup_model(self):
        """Run a silent dummy transcription so CUDA/CTranslate2 JIT-compiles
        its kernels NOW instead of stalling the user's first dictation."""
        try:
            import numpy as _np
            silence = _np.zeros(8000, dtype=_np.float32)   # 0.5 s @ 16 kHz
            if hasattr(self.model, "transcribe"):
                # faster-whisper / OpenVINO path
                list(self.model.transcribe(silence, language="en")[0])
            # Odia / Parakeet have their own decode path; no warm-up needed
            print("[OpenFlow] Model warm-up complete — kernels ready.")
        except Exception as _e:
            print(f"[OpenFlow] Warm-up skipped ({_e})")

    def _load_model_locked(self):
        self._preview_slow = False  # re-judge preview speed for whatever gets loaded
        target_name = self._target(self.language)
        target_name = self._substitute.get(target_name, target_name)
        if target_name == self._current_loaded_name and self.model is not None and self._loaded_device == self.device:
            return
        model_path = model_manager.cached_path(target_name)
        # NPU builds and Odia were picked explicitly (Odia by its language): fetch them, no Whisper stand-in
        if model_path is None and not target_name.endswith("-ov") and target_name != "odia":
            # Only download what the user chose: use the other variant (base <-> base.en) or any
            # model already on disk; download only when nothing is cached at all (first run).
            names = model_manager.variants(target_name) + [
                v for m in model_manager.list_downloaded_models() for v in model_manager.variants(m)]
            fallback = next((n for n in names if model_manager.cached_path(n)), None)
            if fallback:
                wrong_lang = fallback.endswith(".en") and not target_name.endswith(".en")
                if (wrong_lang or fallback.replace(".en", "") != target_name.replace(".en", "")) and self.on_status:
                    self.on_status(f"{target_name} not downloaded · using {fallback}. Get it in Model Library")
                print(f"[OpenFlow] {target_name} not cached; using downloaded {fallback}")
                self._substitute[target_name] = fallback
                if fallback == self._current_loaded_name and self.model is not None and self._loaded_device == self.device:
                    return
                target_name = fallback
                model_path = model_manager.cached_path(fallback)
        if model_path is None:  # first use: download with progress
            if self.on_status:
                self.on_status(f"Downloading {target_name} model")
            cb = (lambda pct: self.on_progress(pct, target_name)) if self.on_progress else None
            try:
                model_path = model_manager.download(target_name, cb)
            except Exception as dl_err:
                print(f"[OpenFlow] Download {target_name} failed: {dl_err}")
                if self.on_status:
                    self.on_status(f"Download failed: {dl_err}")
                # Fallback to an existing local model so app remains functional
                for fb in ["base", "base.en", "tiny", "tiny.en", "small"]:
                    fb_p = model_manager.cached_path(fb)
                    if fb_p:
                        print(f"[OpenFlow] Falling back to existing cached model: {fb}")
                        target_name = fb
                        model_path = fb_p
                        break
                if model_path is None:
                    raise

        if target_name == "parakeet":
            self._load_parakeet(model_path)
            return

        if target_name == "odia":
            from .indic_asr import IndicCTC
            self.model = IndicCTC(os.path.join(model_path, "or"), threads=_THREADS)
            if self.model.lm is None:  # downloaded before the word LM shipped: fetch just that file
                threading.Thread(target=_fetch_odia_lm, args=(self.model,), daemon=True).start()
            self._current_loaded_name = "odia"
            self._loaded_device = self.device
            print("[OpenFlow] Odia IndicConformer loaded and ready.")
            if self.on_status:
                self.on_status("Model odia ready")
            return

        if target_name.endswith("-ov"):
            print(f"[OpenFlow] Loading {target_name} on the NPU (first run compiles, can take a minute)...")
            try:
                self.model = _OpenVINOWhisper(model_path, "NPU")
            except Exception as e:
                print(f"[OpenFlow] NPU load failed ({e}), falling back to CPU int8...")
                if self.on_status:
                    self.on_status("NPU unavailable · using CPU")
                self.device, self.compute_type = "cpu", "int8"
                model_manager.active_device = "cpu"
                self._load_model_locked()
                return
            self._current_loaded_name = target_name
            self._loaded_device = model_manager.active_device = "npu"
            print(f"[OpenFlow] Model {target_name} loaded and ready on the NPU.")
            if self.on_status:
                self.on_status(f"Model {target_name.removesuffix('-ov')} ready (NPU)")
            return

        print(f"[OpenFlow] Loading WhisperModel({target_name}, device={self.device}, compute_type={self.compute_type})...")
        try:
            self.model = faster_whisper.WhisperModel(
                model_path,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=_THREADS,
            )
            self._current_loaded_name = target_name
            self._loaded_device = model_manager.active_device = self.device
            print(f"[OpenFlow] Model {target_name} loaded and ready on {self.device}.")
            if self.on_status:
                self.on_status(f"Model {target_name} ready ({self.device})")
            self._warmup_model()
        except Exception as e:
            print(f"[OpenFlow] GPU load failed ({e}), falling back to CPU int8...")
            self.device = "cpu"
            self.compute_type = "int8"
            try:
                self.model = faster_whisper.WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=_THREADS)
            except Exception as e2:
                # Interrupted / corrupt weights: clean up and re-download once
                print(f"[OpenFlow] CPU load failed ({e2}), repairing {target_name}...")
                if self.on_status:
                    self.on_status(f"Repairing {target_name} model")
                cb = (lambda pct: self.on_progress(pct, target_name)) if self.on_progress else None
                model_path = model_manager.download(target_name, cb, force=True)
                self.model = faster_whisper.WhisperModel(model_path, device="cpu", compute_type="int8", cpu_threads=_THREADS)
            self._current_loaded_name = target_name
            self._loaded_device = model_manager.active_device = "cpu"
            print(f"[OpenFlow] CPU Model {target_name} loaded and ready.")
            if self.on_status:
                self.on_status(f"Model {target_name} ready (CPU)")
            self._warmup_model()

    def _load_parakeet(self, model_path: str):
        """Parakeet runs through sherpa-onnx on the CPU; self.model holds its recognizer."""
        import sherpa_onnx
        f = lambda n: os.path.join(model_path, n)
        self.model = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=f("encoder.int8.onnx"),
            decoder=f("decoder.int8.onnx"),
            joiner=f("joiner.int8.onnx"),
            tokens=f("tokens.txt"),
            num_threads=_THREADS,
            model_type="nemo_transducer",
            decoding_method="greedy_search",
        )
        self._current_loaded_name = "parakeet"
        self._loaded_device = self.device  # device doesn't apply; keeps the reload check quiet
        print("[OpenFlow] Parakeet loaded and ready (CPU).")
        if self.on_status:
            self.on_status("Model parakeet ready (CPU)")

    def _parakeet_text(self, audio: np.ndarray, beam: bool = True) -> str:
        assert self.model is not None
        if self._current_loaded_name == "odia":
            return self.model.text(audio, beam)
        stream = self.model.create_stream()
        stream.accept_waveform(16000, audio)
        self.model.decode_stream(stream)
        return stream.result.text.strip()

    @contextlib.contextmanager
    def _locked(self):
        lock = self._lock
        got = lock.acquire(timeout=_HUNG_S)
        if not got and self._holder_loading:
            got = lock.acquire()
        if not got:
            with self._abandon_guard:  # two waiters timing out together must swap the model once
                if self._lock is lock:
                    lock = self._abandon_hung_model()
                else:
                    lock = self._lock
                    lock.acquire()
        try:
            yield
        finally:
            lock.release()

    def _abandon_hung_model(self) -> threading.RLock:
        """A model call never returned and still holds the lock (a CUDA encode froze mid-preview).
        Leave that call and its model behind and carry on with a fresh model on the CPU."""
        print(f"[OpenFlow] {self.device.upper()} model stopped responding; continuing on the CPU")
        if self.on_status:
            self.on_status("GPU stopped responding · using CPU")
        if self.device == "cuda":
            try:
                from . import hardware
                hardware.CUDA_HUNG_MARK.parent.mkdir(parents=True, exist_ok=True)
                hardware.CUDA_HUNG_MARK.touch()
                hardware.detect.cache_clear()
            except OSError:
                pass
        self._lock = lock = threading.RLock()  # threads still waiting on the old lock stay parked there
        lock.acquire()
        self.model, self._current_loaded_name, self.is_loading = None, "", False
        self.device, self.compute_type = "cpu", "int8"
        try:
            self._load_model_locked()
        except Exception:
            lock.release()
            raise
        return lock

    def unload(self):
        """Free GPU/RAM while idle; transcribe() reloads lazily."""
        with self._locked():
            self.model = None
            self._current_loaded_name = ""
            gc.collect()

    def reload(self, model_size: str, device: str = "cuda", compute_type: str = "float16", language: Optional[str] = None):
        self.model_size = model_size
        self._substitute.clear()  # a model may have been downloaded since
        self.device = device
        self.compute_type = compute_type
        if language:
            self.language = language
        self._load_model()

    def reset_preview_budget(self):
        """Called at start of dictation so cold chunks or previous utterances don't permanently mute preview."""
        self._preview_slow = False

    def transcribe_partial(self, audio: np.ndarray) -> str:
        """Fast real-time preview (beam_size=1, greedy) for streaming into the capsule."""
        if self.model is None or self._preview_slow or len(audio) < 8000 or not _has_speech(audio[-16000 * 3:]):
            return ""
        lock = self._lock
        if not lock.acquire(blocking=False):  # model is swapping, skip preview
            return ""

        start = time.perf_counter()
        try:
            # Slicing the last 3.0 seconds (48,000 samples) instead of 8s keeps decode latency under 80ms
            sample = audio[-16000 * 3:]
            if self._current_loaded_name in ("parakeet", "odia"):
                return _drop_loop(self._parakeet_text(sample, beam=False))
            segments, _ = self.model.transcribe(
                sample,
                **_whisper_args(self.language),
                beam_size=1,
                without_timestamps=True,
                condition_on_previous_text=False,
                vad_filter=False
            )
            return _drop_loop(" ".join([s.text.strip() for s in segments]).strip())
        except Exception:
            return ""
        finally:
            took = time.perf_counter() - start
            if took > _PREVIEW_BUDGET_S:
                self._preview_slow = True
                print(f"[OpenFlow] Live preview took {took * 1000:.0f} ms; turning it off so final text isn't delayed")
            lock.release()

    def transcribe(
        self,
        audio: np.ndarray,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
    ) -> Tuple[str, float, int, str]:
        """
        Final high-accuracy transcription for pasting.

        Parameters
        ----------
        audio          : float32 mono numpy array at 16 kHz
        language       : ISO-639-1 code or None/auto for auto-detect
        initial_prompt : Pre-built context prompt from context_detector.
                         When provided, overrides the default English prompt.
                         Pass None to let transcribe() build a basic fallback.

        Returns
        -------
        (transcribed_text, duration_seconds, latency_ms, detected_language)
        """
        if len(audio) < 1600:
            return "", 0.0, 0, self.language
        if not _has_speech(audio):  # nothing was said: don't let the model make something up
            return "", len(audio) / 16000.0, 0, self.language

        if self.model is None:  # unloaded while idle
            self._load_model()
        if self.model is None:
            raise RuntimeError("Whisper model is not loaded.")

        duration_seconds = len(audio) / 16000.0
        start_time = time.perf_counter()

        lang = language or self.language
        whisper_args = _whisper_args(lang)

        # Make sure appropriate model is loaded if language changed
        target_name = self._target(lang)
        if self._substitute.get(target_name, target_name) != self._current_loaded_name:
            self.language = lang
            self._load_model()

        # Resolve prompt: caller-supplied > smart Indic/English fallback > basic fallback
        if initial_prompt is None:
            if lang in ("en", "en-in"):
                initial_prompt = "Indian English and Hinglish dictation in natural Latin/Roman script. Use standard punctuation."
            elif lang in ("auto", "") or lang in ODIA_LANGS:
                initial_prompt = (
                    "Indian English, Hinglish, Hindi, and Odia speech. "
                    "Accurately transcribe Hindi and Odia phrases in clean Latin/Roman script or Devanagari. "
                    "Common terms: kya, kyu, kaise, kuch, nahi, haan, theek, accha, bhai, yaar, kete, kan, kemiti, kichi, ghare, aama, bhala. "
                    "Never output Urdu or Arabic script."
                )
            elif lang == "hi":
                initial_prompt = "हिंदी भाषा डिक्टेशन। शुद्ध देवनागरी लिपि या रोमन में लिखें। उर्दू या अरबी लिपि का प्रयोग न करें।"

        def _run(vad: bool):
            assert self.model is not None
            # On CPU devices (like AMD Ryzen or Intel Core without NVIDIA GPU), beam_size=1 (greedy)
            # cuts latency by 65%+ and prevents thermal throttling. On GPU, beam_size=2 provides optimal quality.
            eff_beam = 1 if self.device == "cpu" else 2
            segments, info = self.model.transcribe(
                audio,
                beam_size=eff_beam,
                best_of=1 if self.device == "cpu" else eff_beam,
                temperature=0.0,  # avoid expensive multi-temperature fallback loops on low-end CPUs
                **whisper_args,
                vad_filter=vad,
                vad_parameters=dict(min_silence_duration_ms=300, threshold=0.65) if vad else None,
                condition_on_previous_text=False,
                repetition_penalty=1.1,  # discourages the phrase loops Whisper falls into on near-silence
                without_timestamps=True,  # we only join the text; skipping timestamp tokens is ~5% faster
                initial_prompt=initial_prompt,
            )
            return " ".join(seg.text.strip() for seg in segments).strip(), info

        if self._current_loaded_name in ("parakeet", "odia"):
            with self._locked():
                full_text = self._parakeet_text(audio)
                if lang == "or-mix":
                    from .odia_mix import to_mixed
                    full_text = to_mixed(full_text, getattr(self.model, "lm", None))
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return _drop_loop(full_text), duration_seconds, latency_ms, lang

        with self._locked():
            try:
                full_text, info = _run(vad=True)
            except ValueError as ve:
                if "onnxruntime" not in str(ve).lower() and "vad" not in str(ve).lower():
                    raise
                print(f"[OpenFlow] VAD filter error ({ve}), retrying without VAD filter...")
                full_text, info = _run(vad=False)
            except RuntimeError as re_err:
                if self.device not in ("cuda", "npu"):
                    raise
                # GPU/NPU went away mid-session (switched off, driver reset): finish this one on the CPU.
                print(f"[OpenFlow] {self.device.upper()} transcription failed ({re_err}), switching to CPU...")
                self.device, self.compute_type = "cpu", "int8"
                self._load_model_locked()
                full_text, info = _run(vad=True)

            # Whisper hallucinates loops ("1, 2, 3, 4, 1, 2, ...") on short clips, often seeded by the
            # prompt. Nobody says more than ~4 words a second: retry without the prompt, else drop it.
            if _too_many_words(full_text, duration_seconds) or _loop_at(full_text) is not None:
                print(f"[OpenFlow] Discarding hallucination: {full_text[:60]!r}")
                initial_prompt = None
                full_text, info = _run(vad=True)
                if _too_many_words(full_text, duration_seconds):
                    full_text = ""
            full_text = _drop_loop(full_text)

            # Check if Whisper mistook Hindi / Odia / Indian speech as Urdu, Arabic, Persian, or Pashto,
            # or if any Perso-Arabic unicode characters were produced:
            is_urdu_hallucination = (
                (info and getattr(info, "language", "") in ("ur", "ar", "fa", "ps", "sd")) or
                contains_arabic_script(full_text)
            )
            if is_urdu_hallucination and (lang in ("auto", "", "en-in", "en", "hi") or lang in ODIA_LANGS):
                det = getattr(info, "language", "unknown") if info else "unknown"
                print(f"[OpenFlow] Detected Urdu/Arabic script or misclassified language ('{det}'). Re-transcribing as Indic speech...")
                whisper_args = _whisper_args("hi" if lang == "hi" else "en")
                initial_prompt = (
                    "Indian English, Hinglish, Hindi, and Odia speech in Latin/Roman script or Devanagari. "
                    "Do not output Urdu or Arabic characters."
                )
                full_text, info = _run(vad=True)

            # Safety net: if any Perso-Arabic/Urdu characters still remain, transliterate them cleanly to Latin
            if contains_arabic_script(full_text):
                full_text = clean_arabic_script(full_text)

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        detected_lang = "en" if lang == "translate" else (getattr(info, "language", "") or lang)

        return full_text, duration_seconds, latency_ms, detected_lang


def find_pause(audio: np.ndarray, start: int, min_pending_s: float = 4.0, pause_s: float = 0.7,
               threshold: float = 0.008, block: int = 1024) -> Optional[int]:
    """Length from `start` to the middle of the latest pause, once enough audio is pending, else None.
    Same RMS threshold the recorder uses to decide someone is speaking. 0.7 s lands on sentence
    ends; 0.4 s also cut at commas and turned "After that, let's" into "After that. Let's"."""
    seg = audio[start:]
    if len(seg) < min_pending_s * 16000:
        return None
    n = len(seg) // block
    quiet = np.sqrt(np.mean(seg[:n * block].reshape(n, block) ** 2, axis=1)) < threshold
    need = int(np.ceil(pause_s * 16000 / block))
    run = 0
    for i in range(n - 1, -1, -1):  # latest pause first: commit as much as possible
        run = run + 1 if quiet[i] else 0
        if run >= need:
            end = i + run
            while end < n and quiet[end]:
                end += 1
            cut = (i + end) // 2 * block
            return cut if cut >= 16000 else None
    return None


def _fetch_odia_lm(model):
    """12.7 MB add-on to the Odia model the user already chose; decoding stays greedy until it lands."""
    try:
        from huggingface_hub import hf_hub_download
        from .indic_asr import WordLM
        path = hf_hub_download(model_manager._repo("odia"), "or/lm.npz")
        model.lm = WordLM(path)
        print("[OpenFlow] Odia word LM ready: beam search on")
    except Exception as e:
        print(f"[OpenFlow] Odia word LM unavailable ({e}); greedy decoding")


class StreamingSession:
    """Transcribes finished phrases while the user is still talking (cut at natural pauses), so
    releasing the hotkey only decodes the last few seconds instead of the whole dictation."""

    def __init__(self, transcriber: "Transcriber", language: str, initial_prompt: Optional[str]):
        self._t, self._lang, self._prompt = transcriber, language, initial_prompt
        self._texts = []
        self._done = 0              # samples already transcribed
        self._busy = threading.Lock()
        self._closed = False

    def feed(self, audio: np.ndarray):
        """Recorder's growing buffer (same start as the final one). Never blocks the caller for long."""
        if self._closed or not self._busy.acquire(blocking=False):
            return
        try:
            cut = None if self._closed else find_pause(audio, self._done)
            if cut is None:
                return
            text, *_ = self._t.transcribe(audio[self._done:self._done + cut], self._lang, self._prompt)
            if text:
                self._texts.append(text)
            self._done += cut
        except Exception as e:
            print(f"[OpenFlow] Streaming chunk failed ({e}); the final pass will cover it")
        finally:
            self._busy.release()

    def finish(self, audio: np.ndarray) -> Tuple[str, float, int, str]:
        """Same return shape as Transcriber.transcribe; latency is what the user waits after release."""
        start = time.perf_counter()
        self._closed = True
        free = self._busy.acquire(timeout=_HUNG_S)  # let an in-flight phrase finish
        try:
            if not free:  # that phrase is stuck: decode the whole recording instead
                self._texts, self._done = [], 0
            tail, _, _, lang = self._t.transcribe(audio[self._done:], self._lang, self._prompt)
        finally:
            if free:
                self._busy.release()
        text = " ".join(self._texts + ([tail] if tail else []))
        return text, len(audio) / 16000.0, int((time.perf_counter() - start) * 1000), lang
