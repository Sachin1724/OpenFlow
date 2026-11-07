"""
chatterbox_engine.py - Resemble AI Chatterbox 0.5B Conversational Speech Engine for OpenFlow.
Features:
- 0.5B Llama-backbone auto-regressive prosody modeling.
- Zero-shot voice cloning with prompt audio conditioning.
- Guided emotion and expressiveness exaggeration control.
- Cross-lingual Odia <-> Devanagari phonetic bridge for natural Odia conversational synthesis.
- Broadcast normalization to 0.890 peak (-1 dBFS).
"""
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import chatterbox
import numpy as np
import soundfile as sf
import torch

from openflow.engine.phonetic_translit import odia_to_devanagari, odia_to_roman


class ChatterboxEngine:
    """Chatterbox 0.5B ALM voice engine with zero-shot voice cloning and cross-lingual Odia support."""

    PERSONA_REFS = {
        "smita": Path("openflow/models/female_voice_reference.wav"),
        "kishore": Path("openflow/scratch/mira_alm_kishore_expressive.wav"),
        "gulua": Path("openflow/scratch/mira_alm_gulua_comedy.wav"),
        "sambalpuri": Path("openflow/scratch/mira_alm_sambalpuri_juhar.wav"),
    }

    def __init__(self, device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.sample_rate = 24000
        self._load_model()

    def _load_model(self):
        """Loads ChatterboxTTS weights."""
        print(f"[ChatterboxEngine] Initializing ChatterboxTTS on {self.device}...", flush=True)
        try:
            import chatterbox
            self.model = chatterbox.ChatterboxTTS.from_pretrained(device=self.device)
            print(f"[ChatterboxEngine] ChatterboxTTS loaded successfully on {self.device}!", flush=True)
        except Exception as e:
            print(f"[ChatterboxEngine] ERROR loading ChatterboxTTS: {e}", flush=True)
            import traceback
            traceback.print_exc()
            raise

    def contains_odia(self, text: str) -> bool:
        """Checks if text contains any Odia characters (Unicode 0x0B00-0x0B7F)."""
        return any('\u0B00' <= ch <= '\u0B7F' for ch in text)

    def synthesize(
        self,
        text: str,
        audio_prompt_path: Optional[str] = None,
        persona: Optional[str] = None,
        exaggeration: float = 0.5,
        cfg_weight: float = 0.5,
        temperature: float = 0.8,
    ) -> Tuple[np.ndarray, int, float]:
        """
        Synthesizes speech from text.
        If text is Odia, automatically applies phonetic transliteration to Devanagari
        for pronunciation via Chatterbox multilingual vocabulary.
        
        Returns:
            audio_np: float32 numpy array at 24kHz
            sample_rate: 24000
            rtf: Real-Time Factor (synthesis_time / audio_duration)
        """
        t0 = time.perf_counter()

        # Resolve voice prompt
        ref_path = None
        if audio_prompt_path and Path(audio_prompt_path).exists():
            ref_path = str(audio_prompt_path)
        elif persona and persona in self.PERSONA_REFS:
            candidate = self.PERSONA_REFS[persona]
            if candidate.exists():
                ref_path = str(candidate)

        # Phonetic bridge: if Odia, transliterate to Roman phonetics for English ALM vocabulary
        text_to_speak = text
        if self.contains_odia(text):
            text_to_speak = odia_to_roman(text)
            print(f"[ChatterboxEngine] Transliterated Odia -> Roman for ALM synthesis: {text_to_speak}")

        # Generate audio using Chatterbox
        with torch.inference_mode():
            audio_tensor = self.model.generate(
                text=text_to_speak,
                audio_prompt_path=ref_path,
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
                temperature=temperature,
            )

        # Convert to float32 numpy
        if isinstance(audio_tensor, torch.Tensor):
            audio_np = audio_tensor.detach().cpu().squeeze().numpy().astype(np.float32)
        else:
            audio_np = np.asarray(audio_tensor, dtype=np.float32).squeeze()

        # Equal-power peak normalization to 0.890 (-1 dBFS broadcast standard)
        peak = np.max(np.abs(audio_np))
        if peak > 1e-4:
            audio_np = (audio_np / peak) * 0.890

        elapsed = time.perf_counter() - t0
        dur_s = len(audio_np) / self.sample_rate
        rtf = elapsed / dur_s if dur_s > 0 else 0.0

        return audio_np, self.sample_rate, rtf

    def synthesize_to_file(
        self,
        text: str,
        out_path: str,
        audio_prompt_path: Optional[str] = None,
        persona: Optional[str] = "smita",
        exaggeration: float = 0.5,
    ) -> float:
        """Synthesizes speech and writes WAV file, returning duration."""
        wav, sr, rtf = self.synthesize(
            text=text,
            audio_prompt_path=audio_prompt_path,
            persona=persona,
            exaggeration=exaggeration,
        )
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        sf.write(out_path, wav, sr)
        dur = len(wav) / sr
        print(f"[ChatterboxEngine] Saved {dur:.2f}s audio to {out_path} (RTF={rtf:.4f})")
        return dur

