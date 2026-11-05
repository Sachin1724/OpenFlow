"""
speak_custom_message.py — Instant Custom Speech Synthesizer for Odia & English Loanwords
========================================================================================
Type or pass any custom message in Odia or mixed Odia/English:
1. Converts English words (e.g. cricket, match, help, online, tea) into Odia phonetics.
2. Injects human breathing pauses at punctuation (।, ?, !, ,).
3. Synthesizes using neural VITS Odia TTS.
4. Plays out loud through the speakers and saves to 'openflow/data/custom_speech.wav'.
"""

import os
import sys
import io
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

class CustomSpeaker:
    def __init__(self):
        print("=" * 80)
        print("🔊 INITIALIZING CUSTOM ODIA SPEECH SYNTHESIZER")
        print("=" * 80)
        print("Loading Expressive Neural Odia TTS Model...")
        self.tokenizer = VitsTokenizer.from_pretrained(TTS_MODEL_ID)
        self.model = VitsModel.from_pretrained(TTS_MODEL_ID)
        self.sr = self.model.config.sampling_rate
        print("✨ Ready to speak any custom text!\n" + "=" * 80)

    def _synthesize_raw_clause(self, clause_text: str) -> np.ndarray:
        phonetic = prepare_text_for_tts(clause_text)
        clean = re.sub(r"[^\u0B00-\u0B7F\s]", "", phonetic).strip()
        if not clean:
            return np.zeros(0, dtype=np.float32)
        try:
            inputs = self.tokenizer(clean, return_tensors="pt")
            with torch.no_grad():
                output = self.model(**inputs).waveform
            return output[0].cpu().numpy()
        except Exception:
            return np.zeros(0, dtype=np.float32)

    def speak_text(self, text: str, save_path=None) -> np.ndarray:
        PAUSE_MAP = {
            "।": 0.40,
            ".": 0.40,
            "\n": 0.45,
            "?": 0.38,
            "!": 0.32,
            ",": 0.18
        }
        parts = re.split(r'([।!?,\n]+)', text)
        audio_segments = []
        current_text = ""

        for part in parts:
            if not part:
                continue
            if any(p in part for p in ["।", ".", "?", "!", ",", "\n"]):
                if current_text.strip():
                    wav = self._synthesize_raw_clause(current_text)
                    if len(wav) > 0:
                        audio_segments.append(wav)
                    current_text = ""

                p_char = part.strip()[:1]
                pause_sec = PAUSE_MAP.get(p_char, 0.25)
                audio_segments.append(np.zeros(int(pause_sec * self.sr), dtype=np.float32))
            else:
                current_text += " " + part

        if current_text.strip():
            wav = self._synthesize_raw_clause(current_text)
            if len(wav) > 0:
                audio_segments.append(wav)

        if not audio_segments:
            print("⚠️ No pronounceable text found.")
            return np.zeros(0, dtype=np.float32)

        full_audio = np.concatenate(audio_segments, axis=0)

        # Save to disk
        if save_path:
            p = Path(save_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(p), full_audio, self.sr)
            print(f"💾 Audio saved to: {p}")

        # Play audio out loud
        print(f"🔊 Playing audio out loud ({len(full_audio)/self.sr:.2f}s)...")
        sd.play(full_audio, self.sr)
        sd.wait()
        return full_audio


def main():
    speaker = CustomSpeaker()

    # If passed as command-line argument
    if len(sys.argv) > 1:
        custom_msg = " ".join(sys.argv[1:])
        out_wav = SCRIPT_DIR / "data" / "custom_speech.wav"
        print(f"\n🗣️ Custom Message: {custom_msg}")
        speaker.speak_text(custom_msg, save_path=out_wav)
        return

    # Interactive Loop
    out_wav = SCRIPT_DIR / "data" / "custom_speech.wav"
    while True:
        print("\nType any custom message in Odia or mixed English (or 'q' to quit):")
        print("Example: 'ନମସ୍କାର ସଚିନ ଭାଇ ! କାଲି cricket match କିଏ ଜିତିଲା କହିଲ ?'")
        msg = input("\n👉 Enter Message: ").strip()

        if msg.lower() in ['q', 'exit', 'quit']:
            print("👋 Bye!")
            break

        if not msg:
            msg = "ନମସ୍କାର ସଚିନ ଭାଇ ! ମୁଁ ମୀରା, ଆପଣଙ୍କ ଓଡ଼ିଆ ଭଏସ ଆସିଷ୍ଟାଣ୍ଟ । କାଲି cricket match ବହୁତ ବଢ଼ିଆ ଥିଲା !"

        print(f"\n🗣️ SPEAKING: {msg}")
        speaker.speak_text(msg, save_path=out_wav)


if __name__ == "__main__":
    main()
