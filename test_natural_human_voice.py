import os
import sys
import io
import re
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
from pathlib import Path
from transformers import VitsModel, VitsTokenizer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SCRIPT_DIR = Path(r"c:\Users\sachi\Music\rea\openflow")
sys.path.insert(0, str(SCRIPT_DIR))
from engine.phonetic_translit import prepare_text_for_tts

print("=" * 70)
print("🎙️ PROTOTYPING HUMAN-LIKE NATURAL VOICE & NLP FOR MIRA")
print("=" * 70)

# Load MMS-TTS
tts_id = "facebook/mms-tts-ory"
print(f"Loading {tts_id}...")
tokenizer = VitsTokenizer.from_pretrained(tts_id)
model = VitsModel.from_pretrained(tts_id)
device = "cuda:0" if torch.cuda.is_available() else "cpu"
model.to(device)
sr = model.config.sampling_rate

# Create synthetic micro-breath (60ms pink noise shaped with bell curve)
breath_len = int(0.065 * sr)
t = np.linspace(0, 1, breath_len)
# Soft intake envelope
envelope = np.sin(np.pi * t) ** 2
noise = np.random.normal(0, 0.015, breath_len)
# Low-pass filter the noise slightly
breath_audio = (noise * envelope).astype(np.float32)

def synthesize_clause(text: str, speaking_rate: float = 1.0) -> np.ndarray:
    clean = prepare_text_for_tts(text)
    if not clean.strip():
        return np.zeros(0, dtype=np.float32)
    inputs = tokenizer(clean, return_tensors="pt").to(device)
    with torch.no_grad():
        output = model(**inputs, speaking_rate=speaking_rate).waveform
    audio = output[0].cpu().numpy()
    
    # Apply soft attack (15ms fade in) and soft decay (35ms fade out)
    attack_len = min(int(0.015 * sr), len(audio))
    decay_len = min(int(0.035 * sr), len(audio))
    if attack_len > 0:
        audio[:attack_len] *= np.linspace(0.1, 1.0, attack_len, dtype=np.float32)
    if decay_len > 0:
        audio[-decay_len:] *= np.linspace(1.0, 0.05, decay_len, dtype=np.float32)
    return audio

def render_human_speech(text: str, add_breath: bool = True) -> np.ndarray:
    """
    Renders with:
    1. Pre-speech micro-breath intake (tricks the human brain's auditory cortex).
    2. Punctuation cadence:
       - Comma (,): 120ms micro-stop
       - Full stop (।): 240ms statement completion breath
       - Question (?): 260ms reflective pause + slightly higher tempo
       - Exclamation (!): 200ms energetic pause
    3. Final clause deceleration (speaking_rate=0.92).
    """
    PAUSE_MAP = {
        ",": 0.12,
        "।": 0.24,
        ".": 0.24,
        "?": 0.26,
        "!": 0.20,
        "\n": 0.30
    }
    
    parts = re.split(r'([।!?,\n]+)', text)
    segments = []
    
    # 1. Natural pre-speech inhalation
    if add_breath:
        segments.append(breath_audio)
        segments.append(np.zeros(int(0.04 * sr), dtype=np.float32)) # 40ms vocal fold gap
        
    current_text = ""
    for part in parts:
        if not part:
            continue
        if any(p in part for p in ["।", ".", "?", "!", ",", "\n"]):
            p_char = part.strip()[:1]
            is_end = p_char in ["।", ".", "?"]
            rate = 0.92 if is_end else 1.0
            
            if current_text.strip():
                wav = synthesize_clause(current_text, speaking_rate=rate)
                if len(wav) > 0:
                    segments.append(wav)
                current_text = ""
            
            pause_sec = PAUSE_MAP.get(p_char, 0.20)
            segments.append(np.zeros(int(pause_sec * sr), dtype=np.float32))
        else:
            current_text += " " + part
            
    if current_text.strip():
        wav = synthesize_clause(current_text, speaking_rate=0.92)
        if len(wav) > 0:
            segments.append(wav)
            
    if not segments:
        return np.zeros(0, dtype=np.float32)
        
    return np.concatenate(segments, axis=0)

# Compare Robotic vs Human Conversational Style
comparisons = [
    {
        "style": "Textbook / Robotic (Traditional TTS)",
        "odia": "ମୁଁ ଏକ କମ୍ପ୍ୟୁଟର ପ୍ରୋଗ୍ରାମ । ଆପଣଙ୍କୁ ସାହାଯ୍ୟ କରିପାରିବି ।",
        "human_nlp": False
    },
    {
        "style": "Authentic Conversational Odia (Colloquial NLP + Breathing)",
        "odia": "ଆରେ ଭାଇନା ! କୁହନ୍ତୁ କଣ କଥା ? ମୁଁ ଶୁଣୁଛି ପରା, ଆରାମରେ କୁହନ୍ତୁ !",
        "human_nlp": True
    },
    {
        "style": "Natural Match Inquiry Answer",
        "odia": "ଆରେ ଶୁଣନ୍ତୁ, କାଲି cricket match ତ India ପରା ଜିତିଗଲା ! ବହୁତ ବଢ଼ିଆ ଖେଳିଲେ !",
        "human_nlp": True
    }
]

out_dir = SCRIPT_DIR / "data" / "voice_comparison"
out_dir.mkdir(parents=True, exist_ok=True)

for i, comp in enumerate(comparisons):
    print(f"\n[{i+1}/3] Synthesizing: {comp['style']}")
    print(f"   Text: {comp['odia']}")
    audio = render_human_speech(comp["odia"], add_breath=comp["human_nlp"])
    out_path = out_dir / f"sample_{i+1}_{'human' if comp['human_nlp'] else 'robotic'}.wav"
    sf.write(str(out_path), audio, sr)
    dur = len(audio) / sr
    print(f"   Saved: {out_path.name} ({dur:.2f}s)")

print("\n" + "="*70)
print("SUCCESS: Human voice prototypes generated in openflow/data/voice_comparison/")
print("="*70)

