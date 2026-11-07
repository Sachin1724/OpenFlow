"""
f5_engine.py - F5-TTS Zero-Shot Voice Cloning Engine for OpenFlow.
Features:
- Diffusion Transformer (DiT) Flow-Matching non-autoregressive speech synthesis.
- Fast Euler ODE solver (16 or 32 NFE steps).
- Zero-shot voice cloning from 3-10s reference prompt audio.
- Seamless persona conditioning (Smita Mohanty female voice, Kishore male voice).
- Cross-lingual phoneme transfer support.
- Broadcast peak normalization to 0.890 (-1 dBFS).
"""
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import soundfile as sf
import torch

from openflow.engine.phonetic_translit import odia_to_devanagari


class F5VoiceEngine:
    """F5-TTS Flow-Matching zero-shot voice cloning engine."""

    DEFAULT_PERSONAS = {
        "smita": {
            "wav": Path("openflow/models/female_voice_reference.wav"),
            "text": "ନମସ୍କାର ଭାଇ ! ମୁଁ ମୀରା, ଆପଣଙ୍କ ଓଡ଼ିଆ ସାଥୀ ।",
        },
        "kishore": {
            "wav": Path("openflow/scratch/mira_alm_kishore_expressive.wav"),
            "text": "ନମସ୍କାର ଆଜ୍ଞା, ମୁଁ କିଶୋର ।",
        },
    }

    def __init__(self, model_name: str = "F5TTS_v1_Base", device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model_name
        self.sample_rate = 24000
        self.f5_api = None
        self._load_model()

    def _load_model(self):
        """Initializes F5TTS API wrapper."""
        print(f"[F5VoiceEngine] Initializing F5TTS ({self.model_name}) on {self.device}...")
        from f5_tts.api import F5TTS
        self.f5_api = F5TTS(model=self.model_name, device=self.device)
        self.sample_rate = getattr(self.f5_api, "target_sample_rate", 24000)
        print(f"[F5VoiceEngine] F5TTS loaded successfully! (sample_rate={self.sample_rate})")

    def contains_odia(self, text: str) -> bool:
        """Checks if text contains Odia Unicode codepoints."""
        return any('\u0B00' <= ch <= '\u0B7F' for ch in text)

    def synthesize(
        self,
        gen_text: str,
        ref_file: Optional[str] = None,
        ref_text: Optional[str] = None,
        persona: str = "smita",
        nfe_step: int = 16,
        speed: float = 1.0,
        cfg_strength: float = 2.0,
        use_phonetic_bridge: bool = True,
    ) -> Tuple[np.ndarray, int, float]:
        """
        Synthesizes speech using F5-TTS flow matching.
        
        Args:
            gen_text: The sentence to synthesize.
            ref_file: Path to reference audio clip (3-12s).
            ref_text: Exact transcript of the reference audio clip.
            persona: Preconfigured persona ("smita" or "kishore").
            nfe_step: Number of Euler integration steps (16 for low latency, 32 for max quality).
            speed: Playback speed scaling factor.
            cfg_strength: Classifier-free guidance strength (default 2.0).
            use_phonetic_bridge: If True and text is Odia, passes Devanagari transliteration.
            
        Returns:
            audio_np: float32 numpy array at 24kHz.
            sample_rate: 24000.
            rtf: Real-Time Factor.
        """
        t0 = time.perf_counter()

        # Resolve reference audio and text
        if not ref_file or not ref_text:
            p_data = self.DEFAULT_PERSONAS.get(persona, self.DEFAULT_PERSONAS["smita"])
            ref_file = ref_file or str(p_data["wav"])
            ref_text = ref_text or p_data["text"]

        # Ensure ref_file exists
        if not Path(ref_file).exists():
            raise FileNotFoundError(f"Reference audio not found: {ref_file}")

        # Phonetic transliteration bridge for cross-lingual script support
        text_to_generate = gen_text
        ref_text_to_use = ref_text
        if use_phonetic_bridge:
            if self.contains_odia(gen_text):
                text_to_generate = odia_to_devanagari(gen_text)
            if self.contains_odia(ref_text):
                ref_text_to_use = odia_to_devanagari(ref_text)

        # Run F5-TTS inference
        wav, sr, _ = self.f5_api.infer(
            ref_file=ref_file,
            ref_text=ref_text_to_use,
            gen_text=text_to_generate,
            nfe_step=nfe_step,
            speed=speed,
            cfg_strength=cfg_strength,
            target_rms=0.1,
            cross_fade_duration=0.10,
        )

        audio_np = np.asarray(wav, dtype=np.float32).squeeze()

        # Broadcast peak normalization to 0.890 (-1 dBFS)
        peak = np.max(np.abs(audio_np))
        if peak > 1e-4:
            audio_np = (audio_np / peak) * 0.890

        elapsed = time.perf_counter() - t0
        dur_s = len(audio_np) / sr
        rtf = elapsed / dur_s if dur_s > 0 else 0.0

        return audio_np, sr, rtf

    def synthesize_to_file(
        self,
        gen_text: str,
        out_path: str,
        ref_file: Optional[str] = None,
        ref_text: Optional[str] = None,
        persona: str = "smita",
        nfe_step: int = 16,
        speed: float = 1.0,
    ) -> float:
        """Synthesizes speech to WAV file."""
        wav, sr, rtf = self.synthesize(
            gen_text=gen_text,
            ref_file=ref_file,
            ref_text=ref_text,
            persona=persona,
            nfe_step=nfe_step,
            speed=speed,
        )
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(out_path, wav, sr)
        dur = len(wav) / sr
        print(f"[F5VoiceEngine] Saved {dur:.2f}s audio to {out_path} (RTF={rtf:.4f})")
        return dur

