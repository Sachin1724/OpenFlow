"""
conversational_cues.py — Natural Human Conversational Backchannel & Filler Audio Manager
========================================================================================
Provides zero-latency, non-blocking audio cues for Odia conversational voice agents:
1. Active Listening Backchannels ("Audio Nods"): "ହଁ...", "ଆଚ୍ଛା...", "ଠିକ୍ ଅଛି..."
2. Pre-warmed Cognitive Thinking Fillers: "ଆଚ୍ଛା, ଶୁଣନ୍ତୁ..." (masks SLM latency to 0ms)
"""

import os
import random
import threading
from typing import Optional, Dict, Tuple
import numpy as np

try:
    import soundfile as sf
    import sounddevice as sd
    _AUDIO_SUPPORT = True
except ImportError:
    _AUDIO_SUPPORT = False

# Resolve assets directory relative to this module
_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_ASSETS_DIR = os.path.normpath(os.path.join(_MODULE_DIR, "..", "assets", "conversational_audio"))


class ConversationalCueManager:
    """Manages memory-cached Odia conversational audio cues for human-like voice communication."""

    def __init__(self, assets_dir: Optional[str] = None):
        self.assets_dir = assets_dir or _ASSETS_DIR
        self._cues: Dict[str, Tuple[np.ndarray, int]] = {}
        self._is_playing = False
        self._lock = threading.Lock()
        self._load_all_cues()

    def _load_all_cues(self):
        if not _AUDIO_SUPPORT or not os.path.exists(self.assets_dir):
            return

        cue_files = {
            "haan_soft": "haan_soft.wav",
            "achha_soft": "achha_soft.wav",
            "thik_achhi": "thik_achhi.wav",
            "filler_thinking": "filler_thinking.wav",
        }

        for cue_name, fname in cue_files.items():
            fpath = os.path.join(self.assets_dir, fname)
            if os.path.exists(fpath):
                try:
                    data, sr = sf.read(fpath, dtype="float32")
                    # If stereo, convert to mono
                    if len(data.shape) > 1:
                        data = data.mean(axis=1)
                    self._cues[cue_name] = (data, sr)
                except Exception as e:
                    print(f"Warning: Failed to load cue {cue_name}: {e}")

    def play_backchannel(self, cue_type: Optional[str] = None, volume: float = 0.45) -> bool:
        """
        Plays a soft, non-intrusive listening nod while the user is talking.
        Types: 'haan', 'achha', 'thik', or None (randomized natural variation).
        """
        if not _AUDIO_SUPPORT or not self._cues:
            return False

        if cue_type == "haan":
            key = "haan_soft"
        elif cue_type == "achha":
            key = "achha_soft"
        elif cue_type == "thik":
            key = "thik_achhi"
        else:
            # Weighted random: 'haan' 60%, 'achha' 25%, 'thik' 15%
            choices = ["haan_soft", "haan_soft", "achha_soft", "thik_achhi"]
            key = random.choice([k for k in choices if k in self._cues])

        return self._play_waveform(key, volume=volume)

    def play_thinking_filler(self, volume: float = 0.85) -> bool:
        """
        Plays an immediate conversational filler ("ଆଚ୍ଛା, ଶୁଣନ୍ତୁ...")
        the exact millisecond the user stops talking, completely masking
        the language model's computation time.
        """
        if "filler_thinking" not in self._cues:
            return False
        return self._play_waveform("filler_thinking", volume=volume)

    def _play_waveform(self, key: str, volume: float = 1.0) -> bool:
        if key not in self._cues or not _AUDIO_SUPPORT:
            return False

        data, sr = self._cues[key]
        attenuated = data * max(0.0, min(1.5, volume))

        def _worker():
            with self._lock:
                self._is_playing = True
            try:
                sd.play(attenuated, sr)
                sd.wait()
            except Exception as e:
                pass
            finally:
                with self._lock:
                    self._is_playing = False

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def stop_all(self):
        """Immediately silences any active cues."""
        if _AUDIO_SUPPORT:
            try:
                sd.stop()
            except Exception:
                pass
        with self._lock:
            self._is_playing = False

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._is_playing

    def list_available_cues(self) -> Dict[str, float]:
        """Returns dict of loaded cues and their duration in seconds."""
        res = {}
        for k, (data, sr) in self._cues.items():
            res[k] = round(len(data) / sr, 3)
        return res


# Global singleton instance
_cue_manager: Optional[ConversationalCueManager] = None

def get_cue_manager() -> ConversationalCueManager:
    global _cue_manager
    if _cue_manager is None:
        _cue_manager = ConversationalCueManager()
    return _cue_manager

