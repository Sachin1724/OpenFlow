import sys
from pathlib import Path
_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest
import numpy as np
import soundfile as sf
from engine.enrollment import VoiceEnrollmentManager, get_enrollment_manager

def test_audio_validation_rules():
    mgr = get_enrollment_manager()
    sr = 24000
    
    # 1. Too short
    short_wav = np.zeros(int(1.0 * sr), dtype=np.float32)
    valid, reason, _ = mgr.validate_audio(short_wav, sr)
    assert not valid
    assert "too short" in reason.lower()
    
    # 2. Too quiet (silence)
    quiet_wav = np.random.normal(0, 0.001, int(4.0 * sr)).astype(np.float32)
    valid, reason, _ = mgr.validate_audio(quiet_wav, sr)
    assert not valid
    assert "too quiet" in reason.lower()
    
    # 3. Valid speech-like signal with natural pauses
    good_wav = np.zeros(int(4.0 * sr), dtype=np.float32)
    t = np.linspace(0, 1.5, int(1.5 * sr), dtype=np.float32)
    # Burst 1 (0.2s - 1.7s)
    good_wav[int(0.2*sr):int(1.7*sr)] = 0.3 * np.sin(2 * np.pi * 220 * t)
    # Burst 2 (2.2s - 3.7s)
    good_wav[int(2.2*sr):int(3.7*sr)] = 0.25 * np.sin(2 * np.pi * 240 * t)
    # Subtle background noise floor
    good_wav += np.random.normal(0, 0.001, len(good_wav)).astype(np.float32)
    
    valid, reason, stats = mgr.validate_audio(good_wav, sr)
    assert valid, f"Failed validation: {reason}"
    assert stats["duration_s"] == 4.0
    assert stats["rms"] > 0.05

def test_enrollment_from_file():
    mgr = get_enrollment_manager()
    ref_path = _REPO_ROOT / "models" / "female_voice_reference.wav"
    assert ref_path.exists(), "female_voice_reference.wav must exist"
    
    profile = mgr.enroll_speaker(
        name="Smita Studio Test",
        audio_input=ref_path,
        speaker_id="test_smita"
    )
    
    assert profile["speaker_id"] == "test_smita"
    assert profile["name"] == "Smita Studio Test"
    assert profile["gender"] == "female"
    assert len(profile["latent_64"]) == 64
    assert len(profile["embedding_512"]) == 512
    assert Path(profile["sample_path"]).exists()
    
    # Check persistence retrieval
    fetched = mgr.get_speaker("test_smita")
    assert fetched is not None
    assert fetched["name"] == "Smita Studio Test"
    
    # Check listing
    all_speakers = mgr.list_enrolled_speakers()
    assert any(s["speaker_id"] == "test_smita" for s in all_speakers)
    
    # Clean up test speaker
    mgr.delete_speaker("test_smita")
    assert mgr.get_speaker("test_smita") is None
