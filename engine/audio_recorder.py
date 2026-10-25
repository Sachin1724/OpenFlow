import time
import re
import threading
import numpy as np
import sounddevice as sd
from typing import Callable, Optional, List, Dict

SAMPLE_RATE = 16000

# Pre-roll: keep this many samples in a ring buffer so the first
# syllable is never clipped when the user presses Ctrl+Shift.
PREROLL_SAMPLES = int(SAMPLE_RATE * 0.25)  # 250 ms @ 16 kHz


def clean_device_name(raw: str) -> str:
    """Extract clean friendly name from raw Windows Bluetooth/Audio GUID strings."""
    if not raw:
        return "Microphone"
    # Match Bluetooth parenthesis name like ;(CMF Buds 2 Plus))
    m = re.search(r"\(([^()]+)\)", raw)
    if m and "Realtek" not in raw and "Windows" not in raw:
        return m.group(1).replace(";", "").strip()
    # Clean Realtek names
    raw = re.sub(r"@System32.*?;", "", raw)
    raw = re.sub(r"\(R\)", "", raw)
    # Strip long driver suffixes
    if "Realtek" in raw:
        return "Realtek Audio Array"
    return raw.split("(")[0].strip() or raw[:28].strip()


class AudioRecorder:
    def __init__(
        self,
        device_index: Optional[int] = None,
        on_amplitude: Optional[Callable[[float], None]] = None,
        on_auto_silence: Optional[Callable[[], None]] = None,
        on_stream_chunk: Optional[Callable[[np.ndarray], None]] = None,
        auto_silence_duration: float = 1.1,
    ):
        self.device_index = device_index
        self.on_amplitude = on_amplitude
        self.on_auto_silence = on_auto_silence
        self.on_stream_chunk = on_stream_chunk
        self.auto_silence_duration = auto_silence_duration

        self._is_recording = False
        self._stream: Optional[sd.InputStream] = None
        self._audio_chunks = []
        self._lock = threading.Lock()

        # 250 ms pre-roll ring buffer - always collecting even before Ctrl+Shift
        # so the first syllable is never clipped when the user presses the hotkey.
        self._preroll: np.ndarray = np.zeros(PREROLL_SAMPLES, dtype=np.float32)
        self._preroll_lock = threading.Lock()

        # VAD & Auto-write tracking
        self._has_spoken = False
        self._last_speech_time = 0.0
        self._last_chunk_emit_time = 0.0
        self._speech_energy_threshold = 0.04
        self._silence_triggered = False

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def set_device(self, device_index: Optional[int]):
        self.device_index = device_index

    def get_current_device_name(self) -> str:
        if self.device_index is None:
            try:
                d = sd.query_devices(kind="input")
                return clean_device_name(d.get("name", "Default Mic"))
            except Exception:
                return "Default Mic"
        try:
            d = sd.query_devices(self.device_index)
            return clean_device_name(d.get("name", f"Mic {self.device_index}"))
        except Exception:
            return "Microphone"

    def set_auto_silence_duration(self, duration: float):
        self.auto_silence_duration = max(0.6, duration)

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            pass

        mono_data = indata[:, 0].copy() if indata.ndim > 1 else indata.copy()

        # Always update the pre-roll ring buffer, even before recording starts.
        # This ensures the 250 ms before Ctrl+Shift is captured.
        with self._preroll_lock:
            n = len(mono_data)
            if n >= PREROLL_SAMPLES:
                self._preroll = mono_data[-PREROLL_SAMPLES:].copy()
            else:
                self._preroll = np.roll(self._preroll, -n)
                self._preroll[-n:] = mono_data

        if not self._is_recording:
            return

        with self._lock:
            self._audio_chunks.append(mono_data)

        # RMS calculation
        rms = float(np.sqrt(np.mean(mono_data ** 2)))
        level = min(1.0, rms * 9.0)

        now = time.time()

        # Send amplitude for UI visualizer
        if self.on_amplitude:
            try:
                self.on_amplitude(level)
            except Exception:
                pass

        # VAD Detection
        if rms >= self._speech_energy_threshold:
            self._has_spoken = True
            self._last_speech_time = now

        # Periodic real-time streaming preview (every ~0.65s of speech)
        if self._has_spoken and self.on_stream_chunk and (now - self._last_chunk_emit_time > 0.65):
            self._last_chunk_emit_time = now
            with self._lock:
                accumulated = np.concatenate(self._audio_chunks, axis=0) if self._audio_chunks else None
            if accumulated is not None and len(accumulated) > 8000:
                try:
                    self.on_stream_chunk(accumulated)
                except Exception:
                    pass

        # Auto-Silence Detection
        if (
            self._has_spoken
            and not self._silence_triggered
            and self.on_auto_silence
            and (now - self._last_speech_time >= self.auto_silence_duration)
        ):
            self._silence_triggered = True
            threading.Thread(target=self.on_auto_silence, daemon=True).start()

    def start_recording(self):
        with self._lock:
            # Seed audio_chunks with pre-roll so the 250 ms before key-press is included
            with self._preroll_lock:
                self._audio_chunks = [self._preroll.copy()]
            self._is_recording = True
            self._has_spoken = False
            self._silence_triggered = False
            self._last_speech_time = time.time()
            self._last_chunk_emit_time = time.time()

        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="float32",
                device=self.device_index,
                callback=self._audio_callback,
                blocksize=1024,
            )
            self._stream.start()
        except Exception as e:
            self._is_recording = False
            raise RuntimeError(f"Failed to start audio stream: {e}")

    def stop_recording(self) -> np.ndarray:
        self._is_recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        with self._lock:
            if not self._audio_chunks:
                return np.empty((0,), dtype=np.float32)
            audio_data = np.concatenate(self._audio_chunks, axis=0)
            self._audio_chunks = []
            return audio_data


def list_microphones() -> List[Dict]:
    devices = []
    seen_names = set()
    try:
        all_devs = sd.query_devices()
        for idx, dev in enumerate(all_devs):
            if dev.get("max_input_channels", 0) > 0:
                raw_name = dev.get("name", "")
                friendly = clean_device_name(raw_name)
                # Skip duplicate names to avoid confusing the user
                if friendly in seen_names and "Realtek" in raw_name:
                    continue
                seen_names.add(friendly)
                devices.append({
                    "index": idx,
                    "name": friendly,
                    "raw_name": raw_name,
                    "channels": dev.get("max_input_channels"),
                    "default_samplerate": dev.get("default_samplerate")
                })
    except Exception as e:
        print(f"[OpenFlow] Error querying devices: {e}")
    return devices
