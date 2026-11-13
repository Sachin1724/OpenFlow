"""
speak_custom_message.py — Studio-Quality 24kHz HD Speech Synthesizer for Odia
=============================================================================
Type or pass any custom message in Odia or mixed Odia/English:
1. 24,000 Hz Broadcast-Quality Studio Audio (Zero muffled phone-call sound).
2. Native Female Studio Persona (Trained on AI4Bharat Rasa acoustic booth).
3. Converts English words (cricket, match, help, online, tea) into Odia phonetics.
4. Human breathing pauses at punctuation (।, ?, !, ,) with pre-speech inhalation.
5. Plays out loud through the speakers and saves to 'openflow/data/custom_speech.wav'.
"""

import os
import sys
import io
import numpy as np
import sounddevice as sd
import soundfile as sf
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from engine.studio_voice import get_studio_voice

class CustomSpeaker:
    def __init__(self, voice_persona="female"):
        print("=" * 80)
        print("🔊 INITIALIZING STUDIO 24kHz HD ODIA SPEECH SYNTHESIZER")
        print("=" * 80)
        print(f"Loading 24kHz Studio Neural Model (Persona: {voice_persona.upper()})...")
        self.engine = get_studio_voice(voice_persona=voice_persona)
        self.sr = self.engine.sr
        print("✨ Studio Engine Ready! 24,000 Hz Broadcast Audio Quality!
" + "=" * 80)

    def speak_text(self, text: str, save_path=None) -> np.ndarray:
        """Renders 24kHz studio audio with crystal-clear articulation and human cadence."""
        audio = self.engine.synthesize(text, add_breath=True)
        if len(audio) == 0:
            return audio

        if save_path:
            self.engine.save_wav(audio, save_path)
            print(f"📁 Audio saved to: {save_path} ({len(audio)/self.sr:.2f}s, {self.sr}Hz)")

        print("▶️ Playing audio through speakers...")
        try:
            sd.play(audio, self.sr)
            sd.wait()
        except Exception as e:
            print(f"Playback warning: {e}")

        return audio

def main():
    speaker = CustomSpeaker(voice_persona="female")
    save_dir = SCRIPT_DIR / "data"
    save_dir.mkdir(parents=True, exist_ok=True)
    out_wav = str(save_dir / "custom_speech.wav")

    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
        print(f"🗣️ Speaking message: '{text}'")
        speaker.speak_text(text, save_path=out_wav)
        return

    print("Type your message below (Odia, English loanwords, or mixed).")
    print("Press ENTER to speak. Type 'exit' or 'quit' to close.
")

    default_example = "ନମସ୍କାର ସଚିନ ଭାଇ, ଆପଣ କେମିତି ଅଛନ୍ତି ? ଆଜି ଆମେ ଏକ ବହୁତ ବଢ଼ିଆ cricket match ଦେଖିବା !"
    print(f"Example (Press ENTER to speak this default, or type your own):
  "{default_example}"
")

    while True:
        try:
            user_msg = input("Enter Message > ").strip()
            if not user_msg:
                user_msg = default_example
            if user_msg.lower() in ["exit", "quit", "q"]:
                print("Exiting custom speaker. Goodbye!")
                break

            speaker.speak_text(user_msg, save_path=out_wav)
            print()
        except (KeyboardInterrupt, EOFError):
            print("
Exiting.")
            break

if __name__ == "__main__":
    main()
