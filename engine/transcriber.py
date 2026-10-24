import time
import threading
import gc
import numpy as np
from typing import Tuple, Optional
import faster_whisper

from . import model_manager


def resolve_model_name(base_model: str, language: str) -> str:
    """English -> fast .en model. Any other language (or auto) -> multilingual model,
    at least 'small' because tiny/base are poor outside English."""
    clean = base_model.replace(".en", "")
    if language == "en":
        return f"{clean}.en" if clean in ["tiny", "base", "small", "medium"] else clean
    return "small" if clean in ["tiny", "base"] else clean


class Transcriber:
    def __init__(self, model_size: str = "base.en", device: str = "cuda", compute_type: str = "float16", language: str = "en", preload: bool = True):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.model: Optional[faster_whisper.WhisperModel] = None
        self._current_loaded_name = ""
        self._lock = threading.RLock()  # model swaps must not race transcription
        self.on_status = None           # optional callback(str) for "downloading/ready" messages
        self.on_progress = None         # optional callback(percent:int, model_name:str) while downloading
        if preload:
            self._load_model()

    def _load_model(self):
        with self._lock:
            self._load_model_locked()

    def _load_model_locked(self):
        target_name = resolve_model_name(self.model_size, self.language)
        if target_name == self._current_loaded_name and self.model is not None:
            return
        model_path = model_manager.cached_path(target_name)
        if model_path is None:  # first use: download with progress
            if self.on_status:
                self.on_status(f"Downloading {target_name} model")
            cb = (lambda pct: self.on_progress(pct, target_name)) if self.on_progress else None
            model_path = model_manager.download(target_name, cb)

        print(f"[OpenFlow] Loading WhisperModel({target_name}, device={self.device}, compute_type={self.compute_type})...")
        try:
            self.model = faster_whisper.WhisperModel(
                model_path,
                device=self.device,
                compute_type=self.compute_type,
                cpu_threads=4,
            )
            self._current_loaded_name = target_name
            print(f"[OpenFlow] Model {target_name} loaded and ready on {self.device}.")
        except Exception as e:
            print(f"[OpenFlow] GPU load failed ({e}), falling back to CPU int8...")
            self.device = "cpu"
            self.compute_type = "int8"
            self.model = faster_whisper.WhisperModel(
                model_path,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
            )
            self._current_loaded_name = target_name
            print(f"[OpenFlow] CPU Model {target_name} loaded and ready.")

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
            lang = None if self.language in ["auto", ""] else self.language
            segments, _ = self.model.transcribe(
                sample,
                language=lang,
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

    def transcribe(self, audio: np.ndarray, language: Optional[str] = None) -> Tuple[str, float, int, str]:
        """
        Final high-accuracy transcription for pasting.
        Returns: (transcribed_text, duration_seconds, latency_ms, detected_language)
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
        whisper_lang = None if lang in ["auto", ""] else lang

        # Make sure appropriate model is loaded if language changed
        target_name = resolve_model_name(self.model_size, lang)
        if target_name != self._current_loaded_name:
            self.language = lang
            self._load_model()

        # English gets a punctuation hint; the English prompt would bias other languages.
        prompt = "Use standard punctuation, commas, periods, and capitalization." if lang == "en" else None

        with self._lock:
            segments, info = self.model.transcribe(
                audio,
                beam_size=5,
                language=whisper_lang,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=300),
                condition_on_previous_text=False,
                initial_prompt=prompt,
            )
            full_text = " ".join([seg.text.strip() for seg in segments]).strip()

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        detected_lang = info.language if info else lang

        return full_text, duration_seconds, latency_ms, detected_lang
