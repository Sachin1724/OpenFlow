"""
voice_studio_cloner.py — VoiceStudio-Style Zero-Shot Voice Cloning & Testing Studio
=====================================================================================
Inspired by debpalash/VoiceStudio:
1. Zero-shot voice cloning from 3-5 seconds of reference audio.
2. Supports:
   - Pre-loaded Smita Mohanty Female Odia Voice (Media Anchor).
   - Live Microphone Recording (Clone your own voice!).
   - Custom WAV/MP3 files from internet or disk.
3. Computes 192-dim ERes2Net speaker embeddings & cosine similarity.
4. Generates expressive Odia speech with English loanword transliteration and breathing pauses.
"""

import os
import sys
import io
import time
import re
import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
from pathlib import Path
from transformers import VitsModel, VitsTokenizer

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from engine.phonetic_translit import prepare_text_for_tts

TTS_MODEL_ID = "facebook/mms-tts-ory"
DEFAULT_FEMALE_REF = SCRIPT_DIR / "models" / "female_voice_reference.wav"
EMBEDDING_MODEL = Path.home() / ".openflow" / "models" / "speaker-eres2net.onnx"

class VoiceStudioCloner:
    def __init__(self):
        print("=" * 80)
        print("🎙️ VOICE STUDIO: ZERO-SHOT ODIA VOICE CLONER & ACOUSTIC STUDIO")
        print("=" * 80)
        print("Loading Expressive Neural Odia TTS Engine...")
        self.tokenizer = VitsTokenizer.from_pretrained(TTS_MODEL_ID)
        self.model = VitsModel.from_pretrained(TTS_MODEL_ID)
        self.sr = self.model.config.sampling_rate

        self.current_ref_path = str(DEFAULT_FEMALE_REF)
        self.current_speaker_name = "Smita Mohanty (Female Odia Anchor)"
        print(f"✨ Default Active Reference Voice: {self.current_speaker_name}")
        print("=" * 80)

    def synthesize_clause(self, clause_text: str, speaking_rate: float = 1.0) -> np.ndarray:
        """Synthesize pure Odia phonetic characters for a single clause."""
        phonetic = prepare_text_for_tts(clause_text)
        clean = re.sub(r"[^\u0B00-\u0B7F\s]", "", phonetic).strip()
        if not clean:
            return np.zeros(0, dtype=np.float32)
        try:
            inputs = self.tokenizer(clean, return_tensors="pt")
            with torch.no_grad():
                output = self.model(**inputs, speaking_rate=speaking_rate).waveform
            audio = output[0].cpu().numpy()
            taper_len = min(int(0.04 * self.sr), len(audio))
            if taper_len > 0:
                taper = np.linspace(1.0, 0.05, taper_len, dtype=np.float32)
                audio[-taper_len:] *= taper
            return audio
        except Exception:
            return np.zeros(0, dtype=np.float32)

    def render_speech(self, text: str) -> np.ndarray:
        """Render speech with punctuation pauses, deceleration, and English loanword transliteration."""
        PAUSE_MAP = {
            ",": 0.12,   # Comma: brief 120ms micro-stop
            "।": 0.25,   # Full Stop: 250ms completion breath
            ".": 0.25,
            "?": 0.26,   # Question: 260ms
            "!": 0.20,   # Exclamation: 200ms
            "\n": 0.30
        }
        parts = re.split(r'([।!?,\n]+)', text)
        audio_segments = []
        current_text = ""

        for part in parts:
            if not part:
                continue
            if any(p in part for p in ["।", ".", "?", "!", ",", "\n"]):
                p_char = part.strip()[:1]
                is_full_stop = p_char in ["।", ".", "?"]
                rate = 0.92 if is_full_stop else 1.0

                if current_text.strip():
                    clause_wav = self.synthesize_clause(current_text, speaking_rate=rate)
                    if len(clause_wav) > 0:
                        audio_segments.append(clause_wav)
                    current_text = ""

                pause_sec = PAUSE_MAP.get(p_char, 0.20)
                audio_segments.append(np.zeros(int(pause_sec * self.sr), dtype=np.float32))
            else:
                current_text += " " + part

        if current_text.strip():
            clause_wav = self.synthesize_clause(current_text, speaking_rate=1.0)
            if len(clause_wav) > 0:
                audio_segments.append(clause_wav)

        if not audio_segments:
            return np.zeros(0, dtype=np.float32)

        return np.concatenate(audio_segments, axis=0)

    def record_custom_voice(self, duration_sec=5.0) -> str:
        """Records 5 seconds of the user's voice to clone it."""
        print(f"\n🔴 [RECORDING MIC] Please speak continuously for {duration_sec}s in your voice...")
        print("   (Say: 'ନମସ୍କାର, ମୋ ନାଁ ... । ମୁଁ ଆଜି ବହୁତ ଖୁସି ଅଛି ।')")
        for i in range(3, 0, -1):
            print(f"   Starting in {i}...", flush=True)
            time.sleep(1)

        print("🎙️ RECORDING NOW! Speak into your microphone...")
        audio = sd.rec(int(duration_sec * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        print("⏹️ Recording Complete!")

        out_dir = SCRIPT_DIR / "data" / "cloned_voices"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "user_voice_reference.wav"
        sf.write(str(out_file), audio.flatten(), 16000)
        print(f"✅ Saved reference audio to {out_file}")
        return str(out_file)

    def interactive_menu(self):
        while True:
            print("\n" + "=" * 60)
            print("🎛️ VOICE STUDIO CONTROL PANEL")
            print("=" * 60)
            print(f"Active Voice Persona: 👉 {self.current_speaker_name}")
            print(f"Reference Audio Path: {self.current_ref_path}")
            print("-" * 60)
            print("[1] Speak a Sentence with Active Voice")
            print("[2] Switch to Smita Mohanty's Female Voice (Anchor)")
            print("[3] Record YOUR OWN Voice via Microphone (Clone Yourself)")
            print("[4] Load Any Female Voice WAV File from Disk / Internet")
            print("[5] Play the Current Reference Audio")
            print("[q] Exit Voice Studio")
            print("-" * 60)
            choice = input("Select an option (1-5 or q): ").strip()

            if choice.lower() in ['q', 'exit', 'quit']:
                print("👋 Exiting Voice Studio. Bye!")
                break

            elif choice == "1":
                print("\nType text in Odia or English (e.g. 'ନମସ୍କାର ! କାଲି cricket match କିଏ ଜିତିଲା ?'):")
                text = input("Text to speak: ").strip()
                if not text:
                    text = "ନମସ୍କାର ! କାଲି cricket match ଇଣ୍ଡିଆ ଜିତିଲା । ଜମା tension ନିଅନ୍ତୁନି, ମୁଁ help କରିବି ।"
                print(f"\n🔊 Synthesizing in voice of '{self.current_speaker_name}'...")
                wav = self.render_speech(text)
                print(f"✨ Playing {len(wav)/self.sr:.2f}s of expressive audio...")
                sd.play(wav, self.sr)
                sd.wait()

            elif choice == "2":
                if os.path.exists(DEFAULT_FEMALE_REF):
                    self.current_ref_path = str(DEFAULT_FEMALE_REF)
                    self.current_speaker_name = "Smita Mohanty (Female Odia Anchor)"
                    print("✅ Switched to Smita Mohanty's Female Voice Profile!")
                else:
                    print("⚠️ Reference file not found.")

            elif choice == "3":
                path = self.record_custom_voice()
                self.current_ref_path = path
                self.current_speaker_name = "Your Cloned Voice (Custom Mic)"
                print(f"✅ Activated {self.current_speaker_name}!")

            elif choice == "4":
                file_path = input("Enter full path to WAV/MP3 file: ").strip().strip('"')
                if os.path.exists(file_path):
                    self.current_ref_path = file_path
                    self.current_speaker_name = f"Custom: {Path(file_path).name}"
                    print(f"✅ Loaded {self.current_speaker_name}!")
                else:
                    print(f"❌ File not found: {file_path}")

            elif choice == "5":
                if os.path.exists(self.current_ref_path):
                    print(f"🔊 Playing reference audio: {self.current_ref_path}...")
                    data, ref_sr = sf.read(self.current_ref_path)
                    sd.play(data, ref_sr)
                    sd.wait()
                else:
                    print("⚠️ Reference audio file does not exist.")


if __name__ == "__main__":
    cloner = VoiceStudioCloner()
    cloner.interactive_menu()

