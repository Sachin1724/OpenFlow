import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
import numpy as np
from engine.cloned_voice import ClonedVoiceEngine, get_cloned_voice_engine
from engine.enrollment import get_enrollment_manager

def test_cloned_voice_with_enrolled_speaker():
    mgr = get_enrollment_manager()
    cloner = get_cloned_voice_engine()
    
    # Enroll test reference
    ref_path = _REPO_ROOT / "models" / "female_voice_reference.wav"
    assert ref_path.exists()
    
    profile = mgr.enroll_speaker(
        name="Test Smita Cloned",
        audio_input=ref_path,
        speaker_id="unit_test_speaker"
    )
    
    # Synthesize paragraph
    text = "ନମସ୍କାର ! ଏହା ଆମର ଭଏସ ଏନରୋଲମେଣ୍ଟ ସିଷ୍ଟମ । ଆପଣ ଏଠାରେ ପାରାଗ୍ରାଫ ଲେଖିପାରିବେ ଏବଂ ଟେମ୍ପେରେଚର ଆଡଜଷ୍ଟ କରିପାରିବେ ।"
    wav, meta = cloner.synthesize(
        text=text,
        speaker_id="unit_test_speaker",
        temperature=0.667,
        speed=1.0
    )
    
    assert len(wav) > 0
    dur = len(wav) / 24000.0
    assert 4.0 <= dur <= 8.5
    assert np.max(np.abs(wav)) >= 0.85
    assert meta["speaker_name"] == "Test Smita Cloned"
    assert meta["temperature"] == 0.667
    
    # Cleanup test speaker
    mgr.delete_speaker("unit_test_speaker")

def test_speed_and_temperature_controls():
    cloner = get_cloned_voice_engine()
    text = "ନମସ୍କାର, ଆପଣ କେମିତି ଅଛନ୍ତି ?"
    
    # Speed control test
    wav_slow, _ = cloner.synthesize(text, speed=0.8)
    wav_fast, _ = cloner.synthesize(text, speed=1.3)
    
    dur_slow = len(wav_slow) / 24000.0
    dur_fast = len(wav_fast) / 24000.0
    assert dur_slow > dur_fast, f"Slow ({dur_slow:.2f}s) should be longer than Fast ({dur_fast:.2f}s)"
    
    # Temperature control test (low temp vs high temp)
    wav_low_temp, _ = cloner.synthesize(text, temperature=0.15)
    wav_high_temp, _ = cloner.synthesize(text, temperature=0.95)
    
    assert len(wav_low_temp) > 0
    assert len(wav_high_temp) > 0
    # Stochastic difference check
    min_len = min(len(wav_low_temp), len(wav_high_temp))
    assert not np.allclose(wav_low_temp[:min_len], wav_high_temp[:min_len], atol=1e-3)

