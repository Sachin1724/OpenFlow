import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
import numpy as np
from engine.studio_voice import StudioVoiceEngine

def test_female_voice_clarity_and_duration():
    sv = StudioVoiceEngine("female")
    text = "ନମସ୍କାର ! ମୁଁ ମୀରା । ଆପଣ କେମିତି ଅଛନ୍ତି ? ଆଜି ଆପଣଙ୍କ ଦିନ କିପରି କଟିଲା ?"
    wav = sv.synthesize(text, voice="female", speed=1.0)
    dur = len(wav) / 24000.0
    
    # 67 characters at ~15-20 chars/s should be between 3.0s and 4.5s
    assert 2.8 <= dur <= 4.5, f"Duration {dur:.2f}s is abnormal (expected 2.8s - 4.5s)"
    assert np.max(np.abs(wav)) >= 0.85, f"Audio failed peak normalization: {np.max(np.abs(wav)):.3f}"
    
    # Check that there are no long internal dropouts (>60ms) inside speech
    win = int(0.04 * 24000)
    hop = int(0.02 * 24000)
    energies = [np.sum(wav[i:i+win]**2) for i in range(win, len(wav) - win, hop)]
    zero_runs = sum(1 for e in energies if e < 1e-6)
    assert zero_runs == 0, f"Found {zero_runs} dead silence dropouts inside continuous speech"

def test_temperature_variation():
    sv = StudioVoiceEngine("female")
    text = "ନମସ୍କାର, ଆପଣ କେମିତି ଅଛନ୍ତି ?"
    wav_low = sv.synthesize(text, voice="female", temperature=0.1)
    wav_high = sv.synthesize(text, voice="female", temperature=1.0)
    
    # Both should generate valid non-empty audio
    assert len(wav_low) > 0
    assert len(wav_high) > 0
    # Stochastic ODE noise should produce different spectrograms
    assert not np.allclose(wav_low[:len(wav_high)], wav_high[:len(wav_low)], atol=1e-3)

