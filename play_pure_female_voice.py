import os
import sys
import io
import time
import sounddevice as sd
import soundfile as sf
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SCRIPT_DIR = Path(__file__).resolve().parent
AUDIO_FILE = SCRIPT_DIR / "models" / "smita_mohanty_pure_female_speech.wav"
SHORT_REF = SCRIPT_DIR / "models" / "female_voice_reference.wav"

def main():
    print("=" * 80)
    print("🌸 SMITA MOHANTY: 100% PURE ODIA FEMALE VOICE AUDITION")
    print("=" * 80)
    print("Zero Male Host Interference | 100% Authentic Female Odia Diction")
    print("=" * 80)
    print("\nSelect an audition clip:")
    print(" [1] Full 40-Second Pure Female Speech Monologue (Detailed, Expressive)")
    print(" [2] 20-Second Greeting & Introduction Reference Clip")
    print(" [q] Exit")
    print("-" * 80)
    choice = input("Enter choice (1, 2, or q): ").strip()

    if choice == "2":
        target = SHORT_REF
    elif choice.lower() in ['q', 'exit', 'quit']:
        return
    else:
        target = AUDIO_FILE

    if not target.exists():
        print(f"❌ File not found: {target}")
        return

    data, sr = sf.read(str(target))
    duration = len(data) / sr

    print(f"\n🔊 NOW PLAYING: {target.name} ({duration:.1f}s)")
    print("-" * 80)
    if choice == "2":
        print("🗣️ TRANSCRIPT:\n")
        print('"ଫାଷ୍ଟ ଅଫ୍ ଅଲ୍ ମାନସ ବହୁତ ବଡ଼ ବ୍ଲେସିଙ୍ଗ ସେଇଟା... ଥ୍ୟାଙ୍କ ୟୁ ସୋ ମଚ୍ ମୋ ଫ୍ୟାନ୍ସମାନଙ୍କୁ')
        print(' ଏତେ ବଡ଼ କଥା ଫେସବୁକ୍ରେ ସେମାନେ ଶେୟାର କଲେ ତାଙ୍କ ମନର କଥା ।')
        print(' ଆଣ୍ଡ ମୁଁ ବହୁତ ହ୍ୟାପି ଆଣ୍ଡ ଭେରି ଏକ୍ସାଇଟେଡ୍ ତମ ଶୋ ରେ ମୁଁ ଆସିବାକୁ..."')
    else:
        print("🗣️ TRANSCRIPT:\n")
        print('"ମୋତେ ବହୁତ ସାରା ଭଲ ପାଇବା ଦେଇଛି, ସେ ପରିଚୟ ମୋତେ ବହୁତ ସାରା କାମ କରିବାର ଜୋସ୍ ଦେଇଛି !')
        print(' ଆକଚୁଆଲି ସେଇଠି ଦୁଇ ହଜାର ଏକ ରେ ଯଦି ମୋତେ ଅଫର୍ ମିଳିଲା, ସେ ସମୟରେ ମୁଁ ଫାଷ୍ଟ ଭାବିଲି କି')
        print(' ମୁଁ ଆକଚୁଲି କରିପାରିବି କି ନାହିଁ । ତା ପରେ ନାଇଁ, ମା ମୋତେ ବହୁତ ଏନକରେଜ୍ କଲେ ।')
        print(' ଏଇଟା ବହୁତ ହି ସୁନ୍ଦର କ୍ୟାରେକ୍ଟର, ତୁ କର୍, ବହୁତ ସାରା କଲର୍ ସେଡ଼ସ୍ ସବୁ ଅଛି, କର୍ ଭଲ ଲାଗିବ ।')
        print(' ତା ପରେ ଗୋଟେ ଝିଅ ଭିତରେ ଗୋଟିଏ ଚେଞ୍ଜ ଆସେ ନା, ଚରିତ୍ର କଳାକାର ହେବାର ଗୋଟିଏ ଇଚ୍ଛାଟା..."')

    print("-" * 80)
    print("▶️ Playing audio out loud through your speakers...")
    sd.play(data, sr)
    sd.wait()
    print("\n✨ Playback Finished successfully!")

if __name__ == "__main__":
    main()
