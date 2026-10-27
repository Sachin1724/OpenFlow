import os
import re
import time
import threading
import gc
import numpy as np
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


# Languages NVIDIA Parakeet V3 knows; anything else (Hindi, auto-detect, translate...) goes to Whisper.
PARAKEET_LANGS = {
    "en", "en-in", "bg", "hr", "cs", "da", "nl", "et", "fi", "fr", "de", "el", "hu", "it",
    "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru", "uk",
}


def resolve_model_name(base_model: str, language: str) -> str:
    """English (US/UK) -> fast .en model. Indian English, multilingual, auto, or regional -> multilingual model."""
    if base_model == "parakeet":
        return "parakeet" if language in PARAKEET_LANGS else "base"
    clean = base_model.replace(".en", "")
    if clean.startswith("distil"):  # distilled models are English-only
        return clean if language == "en" else "medium"
    if language == "en":
        return f"{clean}.en" if clean in ["tiny", "base", "small", "medium"] else clean
    # For en-in, auto, hi, etc., use the multilingual model directly (base, small, medium)
    return clean



_THREADS = min(8, max(2, (os.cpu_count() or 4) // 2))  # half the cores: fast without starving the PC


def _whisper_args(lang: str) -> dict:
    """Maps an OpenFlow language setting to faster-whisper language/task arguments."""
    if lang == "translate":  # speak any language, get English text
        return {"language": None, "task": "translate"}
    if lang in ("auto", "", "or", "odia"):  # Odia runs via auto-detect + prompt biasing since Whisper has no 'or' token
        return {"language": None, "task": "transcribe"}
    return {"language": "en" if lang == "en-in" else lang, "task": "transcribe"}


def _too_many_words(text: str, seconds: float) -> bool:
    return len(text.split()) > 4 * seconds + 3


class Transcriber:
    def __init__(self, model_size: str = "base.en", device: str = "cuda", compute_type: str = "float16", language: str = "en", preload: bool = True):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.model: Optional["faster_whisper.WhisperModel"] = None
        self._current_loaded_name = ""
        self._lock = threading.RLock()  # model swaps must not race transcription
        self.on_status = None           # optional callback(str) for "downloading/ready" messages
        self._loaded_device = ""
        self.on_progress = None         # optional callback(percent:int, model_name:str) while downloading
        if preload:
            self._load_model()

    def _load_model(self):
        with self._lock:
            self._load_model_locked()

    def _load_model_locked(self):
        target_name = resolve_model_name(self.model_size, self.language)
        if target_name == self._current_loaded_name and self.model is not None and self._loaded_device == self.device:
            return
        model_path = model_manager.cached_path(target_name)
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

        print(f"[OpenFlow] Loading WhisperModel({target_name}, device={self.device}, compute_type={self.compute_type})...")
        try:
            self.model = faster_whisper.WhisperModel(
                model_path,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=_THREADS,
            )
            self._current_loaded_name = target_name
            self._loaded_device = self.device
            print(f"[OpenFlow] Model {target_name} loaded and ready on {self.device}.")
            if self.on_status:
                self.on_status(f"Model {target_name} ready ({self.device})")
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
            self._loaded_device = "cpu"
            print(f"[OpenFlow] CPU Model {target_name} loaded and ready.")
            if self.on_status:
                self.on_status(f"Model {target_name} ready (CPU)")

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

    def _parakeet_text(self, audio: np.ndarray) -> str:
        assert self.model is not None
        stream = self.model.create_stream()
        stream.accept_waveform(16000, audio)
        self.model.decode_stream(stream)
        return stream.result.text.strip()

    def unload(self):
        """Free GPU/RAM while idle; transcribe() reloads lazily."""
        with self._lock:
            self.model = None
            self._current_loaded_name = ""
            gc.collect()

    def reload(self, model_size: str, device: str = "cuda", compute_type: str = "float16", language: Optional[str] = None):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        if language:
            self.language = language
        self._load_model()

    def transcribe_partial(self, audio: np.ndarray) -> str:
        """Fast real-time preview (beam_size=1, greedy) for streaming into the capsule."""
        if self.model is None or len(audio) < 8000:
            return ""
        if not self._lock.acquire(blocking=False):  # model is swapping, skip preview
            return ""

        try:
            sample = audio[-16000 * 8:]
            if self._current_loaded_name == "parakeet":
                return self._parakeet_text(sample)
            segments, _ = self.model.transcribe(
                sample,
                **_whisper_args(self.language),
                beam_size=1,
                without_timestamps=True,
                condition_on_previous_text=False,
                vad_filter=False
            )
            return " ".join([s.text.strip() for s in segments]).strip()
        except Exception:
            return ""
        finally:
            self._lock.release()

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

        if self.model is None:  # unloaded while idle
            self._load_model()
        if self.model is None:
            raise RuntimeError("Whisper model is not loaded.")

        duration_seconds = len(audio) / 16000.0
        start_time = time.perf_counter()

        lang = language or self.language
        whisper_args = _whisper_args(lang)

        # Make sure appropriate model is loaded if language changed
        target_name = resolve_model_name(self.model_size, lang)
        if target_name != self._current_loaded_name:
            self.language = lang
            self._load_model()

        # Resolve prompt: caller-supplied > smart Indic/English fallback > basic fallback
        if initial_prompt is None:
            if lang in ("en", "en-in"):
                initial_prompt = "Indian English and Hinglish dictation in natural Latin/Roman script. Use standard punctuation."
            elif lang in ("auto", "", "or", "odia"):
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
            segments, info = self.model.transcribe(
                audio,
                beam_size=5,  # greedy loses short words/names, and isn't measurably faster on CPU
                **whisper_args,
                vad_filter=vad,
                vad_parameters=dict(min_silence_duration_ms=300) if vad else None,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt,
            )
            return " ".join(seg.text.strip() for seg in segments).strip(), info

        if self._current_loaded_name == "parakeet":
            with self._lock:
                full_text = self._parakeet_text(audio)
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return full_text, duration_seconds, latency_ms, lang

        with self._lock:
            try:
                full_text, info = _run(vad=True)
            except ValueError as ve:
                if "onnxruntime" not in str(ve).lower() and "vad" not in str(ve).lower():
                    raise
                print(f"[OpenFlow] VAD filter error ({ve}), retrying without VAD filter...")
                full_text, info = _run(vad=False)
            except RuntimeError as re_err:
                if self.device != "cuda":
                    raise
                # GPU went away mid-session (switched off, driver reset): finish this one on the CPU.
                print(f"[OpenFlow] GPU transcription failed ({re_err}), switching to CPU...")
                self.device, self.compute_type = "cpu", "int8"
                self._load_model_locked()
                full_text, info = _run(vad=True)

            # Whisper hallucinates loops ("1, 2, 3, 4, 1, 2, ...") on short clips, often seeded by the
            # prompt. Nobody says more than ~4 words a second: retry without the prompt, else drop it.
            if _too_many_words(full_text, duration_seconds):
                print(f"[OpenFlow] Discarding hallucination: {full_text[:60]!r}")
                initial_prompt = None
                full_text, info = _run(vad=True)
                if _too_many_words(full_text, duration_seconds):
                    full_text = ""

            # Check if Whisper mistook Hindi / Odia / Indian speech as Urdu, Arabic, Persian, or Pashto,
            # or if any Perso-Arabic unicode characters were produced:
            is_urdu_hallucination = (
                (info and getattr(info, "language", "") in ("ur", "ar", "fa", "ps", "sd")) or
                contains_arabic_script(full_text)
            )
            if is_urdu_hallucination and lang in ("auto", "", "en-in", "en", "hi", "or", "odia"):
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
        detected_lang = "en" if lang == "translate" else (info.language if info else lang)

        return full_text, duration_seconds, latency_ms, detected_lang
