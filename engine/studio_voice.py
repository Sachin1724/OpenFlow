"""
studio_voice.py — Studio-Grade 24kHz HD Neural Voice Engine for Odia
=====================================================================
Features:
1. 24,000 Hz Studio Sample Rate (Broadcast-grade crisp presence, airiness, and clear consonants).
2. Native Studio Female and Male Voice Personas (Trained on AI4Bharat Rasa acoustic booth dataset).
3. Continuous Neural Speech Blending: Eliminates artificial pauses and fragmentation.
4. Conversational Duration Smoothing: Clamps excessive punctuation and blank token accumulation.
5. Integrated English Loanword Transliteration Engine (clean Odia pronunciation of English words).
6. Calibrated Human Micro-Breathing & Room Acoustic Floor (zero digital silence dropouts).
"""

import os
import sys
import re
import torch
import torchaudio.functional as AF
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, List
from huggingface_hub import snapshot_download

# Ensure openflow imports work
_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MODULE_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from engine.phonetic_translit import prepare_text_for_tts
from engine.podcast_humanizer import humanize_to_podcast_style

_SENT = re.compile(r'(?<=[।?!.])\s+')

# Per-persona pace calibration, applied on top of whatever `speed` the caller passes.
# The AI4Bharat Rasa booth speakers read slower than people talk. Measured with
# score_pronunciation.py against the harvested male podcast references (13.9-15.1 ch/s,
# median 14.3): the male booth voice renders 13.1 ch/s at speed=1.0, and 1.10 puts it at
# 14.4 ch/s with no rise in pronunciation error (CER 2.25% vs 2.17% over 3 runs each).
# Fine-tuning the duration predictor on the same references was tried and is 6x worse
# (CER 10.48%, pace 21.5 ch/s) -- MAS alignment does not survive 7.8 min of reverberant,
# ASR-transcribed podcast audio. Pace is one scalar; it does not need gradients.
# Female is uncalibrated (1.0): only the male voice has been measured against references.
_PACE_CALIBRATION = {"male": 1.10, "female": 1.0}

def _equal_power_crossfade(a: np.ndarray, b: np.ndarray, fade_len: int = 1200) -> np.ndarray:
    """Seamless equal-power cross-fade (cosine/sine) preventing any drop in RMS energy."""
    if len(a) == 0:
        return b
    if len(b) == 0:
        return a
    fade_len = min(fade_len, len(a), len(b))
    t = np.linspace(0, np.pi / 2, fade_len, dtype=np.float32)
    fade_out = np.cos(t)
    fade_in = np.sin(t)
    overlap = a[-fade_len:] * fade_out + b[:fade_len] * fade_in
    return np.concatenate([a[:-fade_len], overlap, b[fade_len:]])

def _split_sentences(text: str, cap: int = 350) -> List[str]:
    """Splits long text into sentence units preserving syntax boundaries."""
    out = []
    for s in _SENT.split(text):
        s = s.strip()
        while len(s) > cap:
            cut = s.rfind(",", 0, cap)
            cut = cut + 1 if cut > 0 else s.rfind(" ", 0, cap)
            if cut <= 0:
                cut = cap
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out

class StudioVoiceEngine:
    def __init__(self, voice_persona: str = "female"):
        """
        Initializes the 24kHz Studio Neural Voice Engine.
        voice_persona: 'female' (default) or 'male'.
        """
        self.voice_persona = voice_persona
        self.model_repo = "sulabhkatiyar/indic-tiny-tts-odia"
        
        # Download / load local cache
        self.model_dir = snapshot_download(self.model_repo)
        if self.model_dir not in sys.path:
            sys.path.insert(0, self.model_dir)
            
        from indic_tiny_tts.infer import TinyTTS
        self.tts = TinyTTS.from_pretrained(self.model_dir)
        self.sr = self.tts.sample_rate  # 24,000 Hz

        # Create natural 24kHz micro-inhalation breath (soft envelope)
        breath_samples = int(0.055 * self.sr)
        t = np.linspace(0, 1, breath_samples)
        env = (np.sin(np.pi * t) ** 2).astype(np.float32)
        noise = np.random.normal(0, 0.008, breath_samples).astype(np.float32)
        self.breath_audio = noise * env
        self.vocal_gap = np.random.normal(0, 0.0004, int(0.040 * self.sr)).astype(np.float32)
        self._active_ft_file = None
        # Pristine booth weights. Without this, load_state_dict(strict=False) layers each
        # persona's checkpoint on top of the previous one: keys the new checkpoint does not
        # contain keep the old persona's values, so male/female cross-contaminate and the
        # acoustic model ends up a mixture no fine-tune ever validated.
        self._base_state = {k: v.detach().clone() for k, v in self.tts.acoustic.state_dict().items()}

    def _apply_finetuned_weights(self, is_female: bool):
        """Loads fine-tuned conversational prosody weights onto the pristine booth model.

        MIRA_FT_MODE picks what gets loaded, so a persona can be A/B'd without code edits:
          off (default)      - pristine booth voice, no fine-tune. Measured best on male:
                               CER 1.74% vs 10.48% for the trained duration predictor.
          rhythm             - load ONLY the duration predictor (encoder.proj_w): pacing and
                               pause length, which is all finetune_prosody.py actually trains.
                               Timbre stays the pristine booth voice.
          filtered           - legacy: load everything EXCEPT encoder.proj_w and spk_emb
          full               - load the checkpoint whole
        'filtered' is self-defeating: it discards encoder.proj_w, the duration predictor, which
        is the one thing prosody fine-tuning produces -- so every prosody checkpoint loaded this
        way was a measured no-op (male: CER 1.74% with it, 1.74% without). It is also
        inconsistent for any checkpoint trained with --full, since the encoder and decoder were
        co-adapted with the spk_emb it throws away.
        'full' measured worst on male: the harvested-podcast duration predictor rushes to
        20.8 ch/s against a 14.4 ch/s human target, and CER rises 1.74% -> 4.78%.
        """
        mode = os.environ.get("MIRA_FT_MODE", "off").lower()
        fn_list = (["odia_female_prosody_restored.safetensors", "odia_female_prosody_ft.safetensors"]
                   if is_female else
                   ["odia_male_prosody_ft.safetensors", "odia_prosody_ft.safetensors"])
        target = None
        if mode != "off":
            for fn in fn_list:
                candidates = [
                    _REPO_ROOT / "models" / fn,
                    _REPO_ROOT / "openflow" / "models" / fn,
                    Path("models") / fn,
                    Path("openflow/models") / fn,
                ]
                target = next((p for p in candidates if p.exists()), None)
                if target:
                    break

        tag = f"{mode}:{target}"
        if self._active_ft_file == tag:
            return

        # Always start from the pristine booth weights, never from the last persona.
        self.tts.acoustic.load_state_dict(self._base_state, strict=False)
        self._active_ft_file = tag

        if target is None:
            return
        try:
            from safetensors.torch import load_file
            weights = load_file(str(target))
            if mode == "rhythm":
                weights = {k: v for k, v in weights.items() if k.startswith("encoder.proj_w")}
            elif mode == "filtered":
                weights = {
                    k: v for k, v in weights.items()
                    if not k.startswith("encoder.proj_w") and not k.startswith("spk_emb")
                }
            if weights:
                self.tts.acoustic.load_state_dict(weights, strict=False)
        except Exception as e:
            print(f"[WARN] Failed to load fine-tuned weights from {target}: {e}")
            self._active_ft_file = None

    def _synthesize_continuous(
        self,
        ids: List[int],
        lang_t: torch.Tensor,
        spk_t: torch.Tensor,
        style_t: torch.Tensor,
        length_scale: float,
        temperature: float = 0.45,
        conv_mode: bool = True
    ) -> np.ndarray:
        """
        Direct continuous acoustic synthesis with context-aware duration smoothing.
        Prevents intra-word <blank> tokens and punctuation from ballooning into dead silences
        while preserving natural human cadence and micro-pauses.
        """
        from indic_tiny_tts.infer import MIN_FRAMES
        from indic_tiny_tts.model.acoustic import sequence_mask, fix_len_compatibility, generate_path
        
        dev = self.tts.device
        with torch.inference_mode():
            x = torch.tensor([ids], device=dev)
            x_lengths = torch.tensor([len(ids)], device=dev)
            spks = self.tts.acoustic.cond(lang_t, spk_t, style_t)
            mu_x, logw, x_mask = self.tts.acoustic.encoder(x, x_lengths, spks)
            mu_x, logw, x_mask = mu_x.float(), logw.float(), x_mask.float()
            w = torch.exp(logw) * x_mask
            w_ceil = torch.ceil(w) * length_scale
            
            if conv_mode:
                # Hand-written durations that override the model's duration predictor.
                # OFF by default: measured on 10 Odia eval sentences (score_pronunciation.py),
                # scoring synthesized audio back through the IndicConformer ASR, male voice:
                #   conv_mode=True            CER 3.97-6.39%  (mean 5.0%)  pace 16.3 ch/s
                #   conv_mode=False temp=0.45 CER 1.74-1.97%  (mean 1.8%)  pace 13.1 ch/s
                # Forcing every <blank> to a single 10 ms frame while stretching phones 1.65x
                # crushes the inter-phone transitions that carry co-articulation, so consonants
                # smear into each other -- the "fumbling". It also ends up faster than the
                # 14.4 ch/s podcast target, not slower, despite the 1.65x.
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
            y_max_length_ = fix_len_compatibility(y_max_length, self.tts.acoustic.n_down)
            
            y_mask = sequence_mask(y_lengths, y_max_length_).unsqueeze(1).to(x_mask.dtype)
            attn_mask = x_mask.unsqueeze(-1) * y_mask.unsqueeze(2)
            attn = generate_path(w_ceil.squeeze(1), attn_mask.squeeze(1))
            mu_y = torch.matmul(attn.transpose(1, 2), mu_x.transpose(1, 2)).transpose(1, 2)
            
            # 10 Euler ODE steps eliminates robotic metallic artifacts and recovers rich harmonic presence
            ode_steps = max(10, self.tts.n_timesteps)
            dec = self.tts.acoustic.decoder(mu_y, y_mask, ode_steps, temperature, spks).float()
            dec = dec[:, :, :y_max_length]
            mel = dec * self.tts.acoustic.mel_std + self.tts.acoustic.mel_mean
            mel = mel * sequence_mask(y_lengths, y_max_length).unsqueeze(1).to(mel.dtype)
            
            wav = self.tts.vocoder.decode(mel.float()).squeeze(0).clamp(-1, 1).float().cpu().numpy()
            return wav

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        temperature: float = 0.45,
        style: Optional[str] = "conv",
        humanize: bool = False,
        add_breath: bool = False,
        conv_mode: bool = False
    ) -> np.ndarray:
        """
        Synthesizes text into crisp 24kHz broadcast audio with continuous natural blending.
        - True continuous neural flow-matching (eliminates unnatural word/clause gaps).
        - Natural 1x human speech pacing calibrated against 1,274 Odia podcast turns (14.4 chars/s).
        - Ambient room tone floor ensures zero dead digital dropouts.
        """
        chosen_voice = voice or self.voice_persona
        raw_input = text
        if humanize:
            raw_input = humanize_to_podcast_style(raw_input)

        clean_text = prepare_text_for_tts(raw_input)
        if not clean_text.strip():
            return np.zeros(0, dtype=np.float32)

        # Determine acoustic gender and speaker ID
        is_female = str(chosen_voice).lower() in ["female", "mira_female", "sambalpuri", "mira_sambalpuri", "smita"]
        tts_speaker = "female" if is_female else "male"
        self._apply_finetuned_weights(is_female)
        spk_name = self.tts.voices[tts_speaker]
        spk_row = self.tts.speaker_rows[spk_name]

        # Natural 1x human speech pacing calibrated without coarse frame distortion:
        pace = _PACE_CALIBRATION.get(tts_speaker, 1.0)
        length_scale = float(self.tts.length_scale.get(spk_name, 1.0)) / (max(0.5, min(2.0, speed)) * pace)

        from indic_tiny_tts.infer import LANG_ID, STYLE_ID
        dev = self.tts.device
        lang_t = torch.tensor([LANG_ID[self.tts.lang]], device=dev)
        spk_t = torch.tensor([spk_row], device=dev)
        
        style_key = style.lower() if style else "conv"
        style_code = STYLE_ID.get(style_key, STYLE_ID.get("conv", 1))
        style_t = torch.tensor([style_code], device=dev)

        norm = self.tts.normalize(clean_text)
        
        # 1. If text fits in a single conversational turn (<= 350 chars), synthesize in one unified pass!
        if len(norm) <= 350:
            ids = self.tts._ids(norm)
            if not ids:
                return np.zeros(0, dtype=np.float32)
            raw_wav = self._synthesize_continuous(ids, lang_t, spk_t, style_t, length_scale, temperature=temperature, conv_mode=conv_mode)
        else:
            # 2. For longer multi-sentence paragraphs, split at sentence breaks and blend with equal-power crossfade
            chunks = _split_sentences(norm, cap=300)
            audio_pieces = []
            for c in chunks:
                ids = self.tts._ids(c)
                if not ids:
                    continue
                sub_wav = self._synthesize_continuous(ids, lang_t, spk_t, style_t, length_scale, temperature=temperature, conv_mode=conv_mode)
                if len(sub_wav) > 0:
                    audio_pieces.append(sub_wav)
                    
            if not audio_pieces:
                return np.zeros(0, dtype=np.float32)
                
            raw_wav = audio_pieces[0]
            for next_piece in audio_pieces[1:]:
                # Smooth 1200-sample (50ms) equal-power crossfade between sentences
                raw_wav = _equal_power_crossfade(raw_wav, next_piece, fade_len=1200)

        # 3. Add subtle room tone floor (-52dB) to eliminate dead digital silence
        noise_floor = np.random.normal(0, 0.0006, len(raw_wav)).astype(np.float32)
        full_audio = raw_wav + noise_floor

        # 4. Optional pre-speech biological breath
        if add_breath:
            full_audio = _equal_power_crossfade(self.breath_audio, full_audio, fade_len=600)

        # 5. Broadcast-standard peak normalization to 0.890 (-1.0 dBFS)
        max_val = np.max(np.abs(full_audio))
        if max_val > 1e-4:
            full_audio = (full_audio / max_val) * 0.890

        return full_audio

    def save_wav(self, audio: np.ndarray, path: str):
        self.tts.save_wav(audio, path)


_GLOBAL_STUDIO_VOICE = None

def get_studio_voice(voice_persona: str = "female") -> StudioVoiceEngine:
    global _GLOBAL_STUDIO_VOICE
    if _GLOBAL_STUDIO_VOICE is None:
        _GLOBAL_STUDIO_VOICE = StudioVoiceEngine(voice_persona=voice_persona)
    return _GLOBAL_STUDIO_VOICE


if __name__ == "__main__":
    u = _split_sentences("ନମସ୍କାର ଭାଇ । କେମିତି ଅଛ ? ଭଲ !")
    assert len(u) == 3
    print("studio_voice tests OK")
