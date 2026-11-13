"""
cloned_voice.py — Parameterized Zero-Shot Voice Cloning & Studio Synthesis Engine
=================================================================================
Features:
1. Continuous Latent Speaker Injection:
   - Injects enrolled 64-dimensional speaker vectors directly into MultiCondMatcha:
     c = [e_lang(32) || e_cloned_spk(64) || e_style(16)] in R^{1 x 112}
   - Bypasses discrete speaker lookup constraints for true zero-shot continuous voice reproduction.
2. Fine-Grained Acoustic Parameter Controls:
   - Temperature (0.1 to 1.2): Tunes Euler ODE flow-matching stochasticity.
     * 0.1 - 0.3: Deterministic, steady, calm cadence.
     * 0.67: Balanced conversational realism.
     * 0.9 - 1.2: Dynamic, expressive prosody with animated pitch inflections.
   - Speed (0.75 to 1.5): True duration scaling with context-aware blank clamping.
   - Expressiveness (0.5 to 1.5): Style conditioning vector weighting.
3. Paragraph Synthesis & Seamless Equal-Power Crossfading:
   - Chunk splitting at syntactic clause boundaries.
   - 1200-sample (50ms) equal-power crossfades preventing pauses or clicks.
   - Micro-acoustic room tone floor (-52 dBFS) ensuring zero dead digital dropouts.
4. Broadcast-Standard Peak Normalization to -1.0 dBFS (0.890).
"""

import os
import sys
import re
import json
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List, Union

import numpy as np
import soundfile as sf
import torch
import torchaudio.functional as AF

# Ensure openflow path resolution
_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MODULE_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.studio_voice import StudioVoiceEngine, get_studio_voice, _equal_power_crossfade, _split_sentences
from engine.enrollment import VoiceEnrollmentManager, get_enrollment_manager
from engine.phonetic_translit import prepare_text_for_tts
from engine.podcast_humanizer import humanize_to_podcast_style


class ClonedVoiceEngine:
    def __init__(self, studio_voice: Optional[StudioVoiceEngine] = None):
        """
        Initializes the Cloned Voice Engine on top of the 24kHz Studio Neural Voice.
        """
        self.studio = studio_voice or get_studio_voice()
        self.enrollment_mgr = get_enrollment_manager()
        self.sr = self.studio.sr # 24,000 Hz

        # Ensure model dependencies in sys.path
        if self.studio.model_dir not in sys.path:
            sys.path.insert(0, self.studio.model_dir)

    def _synthesize_continuous_cloned(
        self,
        ids: List[int],
        cond_spk_64: torch.Tensor,
        temperature: float = 0.45,
        length_scale: float = 1.0,
        expressiveness: float = 1.0,
        conv_mode: bool = False
    ) -> np.ndarray:
        """
        Synthesizes a single chunk using custom continuous speaker conditioning.
        """
        from indic_tiny_tts.infer import LANG_ID, STYLE_ID
        from indic_tiny_tts.model.acoustic import sequence_mask, fix_len_compatibility, generate_path

        dev = self.studio.tts.device
        acoustic = self.studio.tts.acoustic

        with torch.inference_mode():
            x = torch.tensor([ids], device=dev)
            x_lengths = torch.tensor([len(ids)], device=dev)

            # Build continuous conditioning vector c = [lang || cloned_spk || style]
            lang_t = torch.tensor([LANG_ID[self.studio.tts.lang]], device=dev)
            style_t = torch.tensor([STYLE_ID.get("conv", 1)], device=dev)

            lang_emb = acoustic.lang_emb(lang_t)
            style_emb = acoustic.style_emb(style_t) * float(expressiveness)
            spk_emb = cond_spk_64.to(device=dev, dtype=lang_emb.dtype)

            # Shape: [1, 32 + 64 + 16] = [1, 112]
            spks = torch.cat([lang_emb, spk_emb, style_emb], dim=-1)

            mu_x, logw, x_mask = acoustic.encoder(x, x_lengths, spks)
            mu_x, logw, x_mask = mu_x.float(), logw.float(), x_mask.float()
            w = torch.exp(logw) * x_mask

            if conv_mode:
                # Conversational pacing scale (1.65x natural unhurried human conversational warmth)
                # with seamless co-articulation word blending (eliminates choppy gaps and fast-forward feel):
                w_ceil = torch.ceil(w * (length_scale * 1.65))
                for i, tid in enumerate(ids):
                    if tid == 0:  # <blank>
                        w_ceil[0, 0, i] = 1.0  # 1 frame (10ms) throughout for continuous vocal flow
                    elif tid in {2, 8}:  # space or comma: seamless 3-frame (32ms) acoustic word bridge
                        w_ceil[0, 0, i] = 3.0
                    elif tid in {3, 10}:  # ! or ।: natural 10-frame (106ms) clause breath
                        w_ceil[0, 0, i] = 10.0
            else:
                w_ceil = torch.ceil(w) * length_scale

            y_lengths = torch.clamp_min(torch.sum(w_ceil, [1, 2]), 1).long()
            y_max_length = int(y_lengths.max())
            y_max_length_ = fix_len_compatibility(y_max_length, acoustic.n_down)

            y_mask = sequence_mask(y_lengths, y_max_length_).unsqueeze(1).to(x_mask.dtype)
            attn_mask = x_mask.unsqueeze(-1) * y_mask.unsqueeze(2)
            attn = generate_path(w_ceil.squeeze(1), attn_mask.squeeze(1))
            mu_y = torch.matmul(attn.transpose(1, 2), mu_x.transpose(1, 2)).transpose(1, 2)

            # 10 Euler ODE steps eliminates robotic metallic artifacts and recovers rich harmonic presence
            ode_steps = max(10, self.studio.tts.n_timesteps)
            dec = acoustic.decoder(mu_y, y_mask, ode_steps, float(temperature), spks).float()
            dec = dec[:, :, :y_max_length]
            mel = dec * acoustic.mel_std + acoustic.mel_mean
            mel = mel * sequence_mask(y_lengths, y_max_length).unsqueeze(1).to(mel.dtype)

            wav = self.studio.tts.vocoder.decode(mel.float()).squeeze(0).clamp(-1, 1).float().cpu().numpy()
            return wav

    def synthesize(
        self,
        text: str,
        speaker_id: Optional[str] = None,
        reference_audio: Optional[Union[str, Path, np.ndarray]] = None,
        temperature: float = 0.45,
        speed: float = 1.0,
        expressiveness: float = 1.0,
        humanize: bool = False,
        add_breath: bool = False,
        conv_mode: bool = False
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Synthesizes speech in the cloned voice of an enrolled speaker or reference audio.
        Returns: (audio_waveform_24k, metadata_dict)
        """
        # 1. Resolve speaker conditioning vector
        spk_meta = None
        if speaker_id:
            spk_meta = self.enrollment_mgr.get_speaker(speaker_id)
            if spk_meta is None:
                raise ValueError(f"Speaker '{speaker_id}' not found in enrolled speakers registry.")
            latent_list = spk_meta["latent_64"]
            cond_spk = torch.tensor([latent_list], dtype=torch.float32)
            speaker_name = spk_meta["name"]
        elif reference_audio is not None:
            # Temporary zero-shot enrollment
            temp_profile = self.enrollment_mgr.enroll_speaker(
                name="Temp Cloned Speaker",
                audio_input=reference_audio,
                speaker_id="_temp_cloned_session"
            )
            cond_spk = torch.tensor([temp_profile["latent_64"]], dtype=torch.float32)
            speaker_name = "Dynamic Cloned Audio"
            spk_meta = temp_profile
            # Clean up temp files
            self.enrollment_mgr.delete_speaker("_temp_cloned_session")
        else:
            # Default to studio female baseline (Row 8)
            dev = self.studio.tts.device
            spk_t = torch.tensor([self.studio.tts.speaker_rows["or_F"]], device=dev)
            cond_spk = self.studio.tts.acoustic.spk_emb(spk_t)
            speaker_name = "MIRA Studio Baseline (Female)"

        # 2. Text preprocessing & humanization
        raw_input = text
        if humanize:
            raw_input = humanize_to_podcast_style(raw_input)

        clean_text = prepare_text_for_tts(raw_input)
        if not clean_text.strip():
            return np.zeros(0, dtype=np.float32), {"duration_s": 0.0, "speaker": speaker_name}

        # 3. Pacing & length scale
        base_len_scale = float(self.studio.tts.length_scale.get("or_F", 1.0158))
        effective_speed = max(0.5, min(2.0, speed))
        length_scale = base_len_scale / effective_speed
        clamped_temp = max(0.05, min(1.5, temperature))

        norm = self.studio.tts.normalize(clean_text)

        # 4. Multi-sentence paragraph synthesis with continuous crossfading
        if len(norm) <= 300:
            ids = self.studio.tts._ids(norm)
            if not ids:
                return np.zeros(0, dtype=np.float32), {"duration_s": 0.0, "speaker": speaker_name}
            raw_wav = self._synthesize_continuous_cloned(
                ids, cond_spk, temperature=clamped_temp, length_scale=length_scale,
                expressiveness=expressiveness, conv_mode=conv_mode
            )
        else:
            chunks = _split_sentences(norm, cap=260)
            audio_pieces = []
            for c in chunks:
                ids = self.studio.tts._ids(c)
                if not ids:
                    continue
                sub_wav = self._synthesize_continuous_cloned(
                    ids, cond_spk, temperature=clamped_temp, length_scale=length_scale,
                    expressiveness=expressiveness, conv_mode=conv_mode
                )
                if len(sub_wav) > 0:
                    audio_pieces.append(sub_wav)

            if not audio_pieces:
                return np.zeros(0, dtype=np.float32), {"duration_s": 0.0, "speaker": speaker_name}

            raw_wav = audio_pieces[0]
            for next_piece in audio_pieces[1:]:
                raw_wav = _equal_power_crossfade(raw_wav, next_piece, fade_len=1200)

        # 5. Natural Pitch Adaptation: match enrolled speaker's vocal pitch register
        pitch_shift_st = 0.0
        if spk_meta:
            if "pitch_semitones" in spk_meta:
                pitch_shift_st = float(spk_meta["pitch_semitones"])
            elif "f0_median" in spk_meta and spk_meta["f0_median"] > 50.0:
                base_f0 = 220.0 if spk_meta.get("gender") == "female" else 162.2
                ratio = float(spk_meta["f0_median"] / base_f0)
                pitch_shift_st = float(np.clip(12.0 * np.log2(max(0.5, min(2.0, ratio))), -5.0, 5.0))

        if abs(pitch_shift_st) > 0.35 and len(raw_wav) > 0:
            t_wav = torch.tensor(raw_wav, dtype=torch.float32).unsqueeze(0)
            raw_wav = AF.pitch_shift(t_wav, self.sr, n_steps=pitch_shift_st).squeeze(0).numpy()

        # 6. Room acoustic tone floor (-52 dBFS)
        noise_floor = np.random.normal(0, 0.0006, len(raw_wav)).astype(np.float32)
        full_audio = raw_wav + noise_floor

        # 7. Optional breath
        if add_breath:
            full_audio = _equal_power_crossfade(self.studio.breath_audio, full_audio, fade_len=600)

        # 8. Peak normalize to 0.890 (-1.0 dBFS)
        max_val = np.max(np.abs(full_audio))
        if max_val > 1e-4:
            full_audio = (full_audio / max_val) * 0.890

        dur = len(full_audio) / self.sr
        meta = {
            "speaker_name": speaker_name,
            "speaker_id": speaker_id or "custom",
            "duration_s": round(dur, 2),
            "sample_rate": self.sr,
            "temperature": clamped_temp,
            "speed": effective_speed,
            "expressiveness": expressiveness
        }
        return full_audio, meta

    def save_wav(self, audio: np.ndarray, path: Union[str, Path]):
        """Saves 24kHz studio audio to disk."""
        self.studio.save_wav(audio, path)


_GLOBAL_CLONED_ENGINE = None

def get_cloned_voice_engine() -> ClonedVoiceEngine:
    global _GLOBAL_CLONED_ENGINE
    if _GLOBAL_CLONED_ENGINE is None:
        _GLOBAL_CLONED_ENGINE = ClonedVoiceEngine()
    return _GLOBAL_CLONED_ENGINE


if __name__ == "__main__":
    engine = get_cloned_voice_engine()
    print("ClonedVoiceEngine ready on 24kHz HD studio voice!")

