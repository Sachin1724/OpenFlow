"""
emotion_mirror.py — Acoustic Emotion & Pacing Mirroring
========================================================
Analyzes incoming caller audio waveform (pitch dynamics, speaking rate, energy)
and dynamically mirrors customer energy in MIRA CRM responses:

1. Rush / Transactional Mode (Fast cadence > 4.2 syl/sec):
   - MIRA drops all fillers and fluff.
   - Pacing accelerated to 1.18x - 1.25x speed.
   - ODE Flow Temperature set to 0.35 (snappy, deterministic, low-entropy).
   - Response style: crisp, transactional, immediate.

2. Warm / Relaxed Mode (Slow cadence < 3.2 syl/sec):
   - MIRA injects natural reassurance markers & conversational tags:
     e.g., "Don't worry, I've got it all down!", "ଆଚ୍ଛା, ଆଦୌ ବ୍ୟସ୍ତ ହୁଅନ୍ତୁନି..."
   - Pacing relaxed to 0.95x speed.
   - ODE Flow Temperature set to 0.75 - 0.80 (warm, natural vocal depth).

3. Inquisitive / Dynamic Mode (High pitch delta ΔF0 > 75 Hz):
   - MIRA increases dynamic range (temp 0.85 - 0.95).
   - Injects attentive active listening markers ("ହଁ ଆଜ୍ଞା...", "Sure thing!").
"""

import math
import numpy as np
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, List
import scipy.signal


@dataclass
class EmotionProfile:
    mode: str                    # 'rush_transactional', 'warm_relaxed', 'inquisitive_dynamic', 'neutral_balanced'
    speaking_rate_sps: float     # Estimated syllables per second
    f0_median_hz: float          # Fundamental pitch median
    f0_range_hz: float           # ΔF0 (max - min voiced pitch)
    energy_rms: float            # RMS amplitude of speech frames
    speed_factor: float          # Recommended TTS playback speed (e.g. 0.95x - 1.25x)
    temperature: float           # Recommended ODE flow matching temperature (0.35 - 0.95)
    allow_fillers: bool          # Whether conversational fluff/fillers are allowed
    reassurance_marker: str      # Dynamic opening or closing filler to mirror energy
    explanation: str             # Human-readable rationale for the adaptation


class AcousticEmotionMirror:
    """
    Analyzes customer vocal dynamics and extracts pacing and emotion cues
    to mirror the user's conversational state in real time.
    """

    def __init__(self, sample_rate: int = 24000):
        self.sr = sample_rate

    def extract_pitch_f0(self, wav: np.ndarray) -> Tuple[float, float, List[float]]:
        """
        Extracts fundamental pitch (F0) across short-time frames using normalized autocorrelation.
        Returns: (f0_median, f0_range, voiced_f0_list)
        """
        if len(wav) < self.sr * 0.1:
            return 160.0, 0.0, []

        frame_len = int(self.sr * 0.040)  # 40ms frame
        hop_len = int(self.sr * 0.020)    # 20ms hop
        min_lag = int(self.sr / 450.0)    # max F0 ~450 Hz
        max_lag = int(self.sr / 70.0)     # min F0 ~70 Hz

        f0_list = []
        for i in range(0, len(wav) - frame_len, hop_len):
            frame = wav[i : i + frame_len]
            # Energy gate (skip silent frames)
            rms = float(np.sqrt(np.mean(frame ** 2)))
            if rms < 0.015:
                continue

            # Normalized autocorrelation
            corr = np.correlate(frame - np.mean(frame), frame - np.mean(frame), mode='full')
            corr = corr[len(corr) // 2 :]
            if len(corr) <= max_lag:
                continue

            search_slice = corr[min_lag : max_lag]
            if len(search_slice) == 0:
                continue

            peak_idx = int(np.argmax(search_slice)) + min_lag
            if corr[0] > 1e-6 and (corr[peak_idx] / corr[0]) > 0.35:
                f0 = float(self.sr / peak_idx)
                if 70.0 <= f0 <= 450.0:
                    f0_list.append(f0)

        if not f0_list:
            return 160.0, 0.0, []

        f0_median = float(np.median(f0_list))
        f0_min = float(np.percentile(f0_list, 10))
        f0_max = float(np.percentile(f0_list, 90))
        f0_range = max(0.0, f0_max - f0_min)

        return f0_median, f0_range, f0_list

    def estimate_speaking_rate(
        self,
        wav: np.ndarray,
        transcript: Optional[str] = None
    ) -> float:
        """
        Estimates syllables per second (speaking rate).
        Uses phonotactic syllable nucleus counting if transcript is provided,
        or acoustic energy envelope modulation peak tracking (2-8 Hz syllable nuclei).
        """
        dur_sec = max(len(wav) / float(self.sr), 0.1)

        # Method A: Lexical transcript estimation
        if transcript and transcript.strip():
            words = transcript.strip().split()
            if words:
                import re
                total_syllables = 0
                for w in words:
                    w_clean = re.sub(r'[^a-zA-Z\u0B00-\u0B7F\u0900-\u097F]', '', w.lower())
                    if not w_clean:
                        continue

                    # 1. Odia / Hindi Indic syllable nucleus counting
                    indic_vowels = re.findall(r'[\u0B05-\u0B14\u0B3E-\u0B4C\u0904-\u0914\u093E-\u094C]', w_clean)
                    if indic_vowels:
                        total_syllables += max(1, len(indic_vowels))
                    else:
                        # 2. English syllable estimation: group vowel diphthongs & drop silent trailing 'e'
                        w_eng = re.sub(r'e$', '', w_clean) if len(w_clean) > 2 else w_clean
                        vowel_groups = re.findall(r'[aeiouy]+', w_eng)
                        total_syllables += max(1, len(vowel_groups))

                if total_syllables > 0:
                    return max(1.0, float(total_syllables) / dur_sec)

        # Method B: Acoustic envelope modulation peak detection
        # Filter audio in 300 - 3000 Hz (speech vowel band)
        b, a = scipy.signal.butter(2, [300 / (self.sr / 2), 3000 / (self.sr / 2)], btype='bandpass')
        filtered = scipy.signal.lfilter(b, a, wav)

        # Extract envelope via Hilbert transform
        analytic = scipy.signal.hilbert(filtered)
        envelope = np.abs(analytic)

        # Lowpass envelope at 8 Hz to capture syllable rate modulation (2 - 8 Hz)
        b_low, a_low = scipy.signal.butter(2, 8.0 / (self.sr / 2), btype='lowpass')
        smooth_env = scipy.signal.lfilter(b_low, a_low, envelope)

        # Detect peaks representing vowel nuclei
        min_peak_distance = int(self.sr * 0.12)  # min 120ms between syllables (~max 8.3 Hz)
        peaks, _ = scipy.signal.find_peaks(
            smooth_env,
            distance=min_peak_distance,
            height=np.mean(smooth_env) * 0.75
        )

        n_syllables = len(peaks)
        if dur_sec < 0.5:
            return 3.5

        rate = float(n_syllables) / dur_sec
        return max(1.5, min(7.5, rate))

    def analyze_caller_emotion(
        self,
        wav: np.ndarray,
        transcript: Optional[str] = None,
        language: str = "or"
    ) -> EmotionProfile:
        """
        Performs holistic acoustic and pacing analysis to determine caller mode
        and generate exact TTS synthesis parameters and conversational tags.
        """
        # Calculate RMS energy of active speech
        rms = float(np.sqrt(np.mean(wav ** 2)))

        # Extract pitch metrics
        f0_median, f0_range, _ = self.extract_pitch_f0(wav)

        # Extract speech cadence
        syl_rate = self.estimate_speaking_rate(wav, transcript=transcript)

        # Decision Logic:
        # Thresholds:
        # Normal conversational cadence: 3.5 - 5.0 syl/s
        # Rush / fast: >= 5.2 syl/s (or explicit urgency triggers)
        # Warm / slow / casual: <= 3.4 syl/s
        
        is_rush_trigger = transcript and any(w in transcript.lower() for w in ["quick", "fast", "hurry", "ଶୀଘ୍ର", "ଜଲ୍ଦି", "actually change"])
        
        # 1. RUSH / TRANSACTIONAL
        if syl_rate >= 5.2 or is_rush_trigger:
            mode = "rush_transactional"
            speed_factor = 1.20
            temperature = 0.35
            allow_fillers = False
            reassurance = ""
            explanation = f"Customer speaking rapidly ({syl_rate:.1f} syl/s). Dropping all fillers; accelerated to 1.20x with crisp ODE temp 0.35."

        # 2. INQUISITIVE / DYNAMIC
        elif f0_range >= 75.0 or (transcript and ("?" in transcript or any(w in transcript.lower() for w in ["does it", "contain", "କ'ଣ", "କଣ", "କିଏ"]))):
            mode = "inquisitive_dynamic"
            speed_factor = 1.02
            temperature = 0.90
            allow_fillers = True
            if language == "en":
                reassurance = "Sure thing! "
            elif language == "hi":
                reassurance = "जी ज़रूर! "
            else:
                reassurance = "ହଁ ଆଜ୍ଞା, "
            explanation = f"Customer shows high pitch dynamism (ΔF0={f0_range:.1f} Hz). Set lively ODE temp 0.90 with active attentive affirmation."

        # 3. WARM / RELAXED
        elif syl_rate <= 3.5:
            mode = "warm_relaxed"
            speed_factor = 0.95
            temperature = 0.75
            allow_fillers = True
            if language == "en":
                reassurance = "Don't worry, I've got it all down! "
            elif language == "hi":
                reassurance = "आप बिल्कुल चिंता न करें, मैंने सब नोट कर लिया है। "
            else:
                reassurance = "ଆଚ୍ଛା, ଆଦୌ ବ୍ୟସ୍ତ ହୁଅନ୍ତୁନି, ମୁଁ ସବୁ ଠିକ୍ କରିଦେଉଛି। "
            explanation = f"Customer speaking in relaxed, deliberating cadence ({syl_rate:.1f} syl/s). Relaxed pacing 0.95x with warm reassurance filler."

        # 4. BALANCED / NEUTRAL
        else:
            mode = "neutral_balanced"
            speed_factor = 1.00
            temperature = 0.65
            allow_fillers = True
            reassurance = ""
            explanation = f"Standard balanced conversational cadence ({syl_rate:.1f} syl/s, ΔF0={f0_range:.1f} Hz)."

        return EmotionProfile(
            mode=mode,
            speaking_rate_sps=round(syl_rate, 2),
            f0_median_hz=round(f0_median, 1),
            f0_range_hz=round(f0_range, 1),
            energy_rms=round(rms, 4),
            speed_factor=speed_factor,
            temperature=temperature,
            allow_fillers=allow_fillers,
            reassurance_marker=reassurance,
            explanation=explanation
        )

    def adapt_response_script(
        self,
        base_text: str,
        profile: EmotionProfile
    ) -> str:
        """
        Applies conversational mirroring tags to the response script.
        - In rush mode: Strips any pre-existing conversational fillers.
        - In warm mode: Prepends reassurance markers.
        """
        text = base_text.strip()

        if not profile.allow_fillers:
            # Strip casual prefixes
            fluff_prefixes = [
                "ଆଚ୍ଛା, ଆଦୌ ବ୍ୟସ୍ତ ହୁଅନ୍ତୁନି, ",
                "ଆଚ୍ଛା, ",
                "ହଁ ଆଜ୍ଞା, ",
                "Don't worry, I've got it all down! ",
                "Sure thing! ",
                "जी ज़रूर! "
            ]
            for p in fluff_prefixes:
                if text.startswith(p):
                    text = text[len(p):].strip()
            return text

        if profile.reassurance_marker and not text.startswith(profile.reassurance_marker):
            return profile.reassurance_marker + text

        return text


# Standalone quick test
if __name__ == "__main__":
    mirror = AcousticEmotionMirror(sample_rate=24000)

    # Test 1: Rapid speech synthetic buffer
    t = np.linspace(0, 1.2, int(24000 * 1.2))
    # 6 syllables in 1.2s = 5 syl/s
    rapid_wave = 0.3 * np.sin(2 * np.pi * 200 * t) * (np.sin(2 * np.pi * 5 * t) ** 2)

    profile_rapid = mirror.analyze_caller_emotion(
        rapid_wave,
        transcript="Actually can you change the pepperoni to large and add five diet cokes quick",
        language="en"
    )
    print("=== RAPID SPEECH PROFILE ===")
    print(f"Mode: {profile_rapid.mode}")
    print(f"Speed: {profile_rapid.speed_factor}x | Temp: {profile_rapid.temperature}")
    print(f"Allow Fillers: {profile_rapid.allow_fillers}")
    print(f"Explanation: {profile_rapid.explanation}")

    # Test 2: Slow deliberating speech (4.5s for 12 syllables ~ 2.6 syl/s)
    t_slow = np.linspace(0, 4.5, int(24000 * 4.5))
    slow_wave = 0.25 * np.sin(2 * np.pi * 140 * t_slow) * (np.sin(2 * np.pi * 1.5 * t_slow) ** 2)

    profile_slow = mirror.analyze_caller_emotion(
        slow_wave,
        transcript="Umm... can you tell me what pizzas you have today please",
        language="en"
    )
    print("\n=== SLOW / WARM SPEECH PROFILE ===")
    print(f"Mode: {profile_slow.mode}")
    print(f"Speed: {profile_slow.speed_factor}x | Temp: {profile_slow.temperature}")
    print(f"Reassurance: '{profile_slow.reassurance_marker}'")
    print(f"Explanation: {profile_slow.explanation}")

    # Test 3: Inquisitive question
    t_inq = np.linspace(0, 2.0, int(24000 * 2.0))
    # Pitch modulated from 130 to 220 Hz (ΔF0 ~ 90 Hz)
    f0_mod = 130 + 90 * (t_inq / 2.0)
    phase = 2 * np.pi * np.cumsum(f0_mod) / 24000.0
    inq_wave = 0.3 * np.sin(phase)

    profile_inq = mirror.analyze_caller_emotion(
        inq_wave,
        transcript="Does the chicken biryani contain nuts?",
        language="en"
    )
    print("\n=== INQUISITIVE SPEECH PROFILE ===")
    print(f"Mode: {profile_inq.mode}")
    print(f"Speed: {profile_inq.speed_factor}x | Temp: {profile_inq.temperature}")
    print(f"Reassurance: '{profile_inq.reassurance_marker}'")
    print(f"Explanation: {profile_inq.explanation}")