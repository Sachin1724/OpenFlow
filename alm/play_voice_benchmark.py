"""
play_voice_benchmark.py - Interactive Audio Player & Benchmark Audition Console
================================================================================
Allows listening to and comparing the verified Odia voice architectures:
1. MIRA Studio Voice (Female - Smita): Ultra-low latency, crystal-clear Odia booth presence.
2. MIRA Studio Voice (Male - Kishore): Grounded, poised masculine Odia tone.
3. Chatterbox 0.5B (Conversational ALM): Auto-regressive prosody modeling with guided emotion.
"""
import os
import sys
import time
import winsound
from pathlib import Path

import soundfile as sf
import numpy as np

BENCHMARK_DIR = Path("openflow/scratch/benchmark_results")

VOICES = {
    "1": {
        "title": "MIRA Studio Voice (Female / Smita)",
        "desc": "Ultra-low latency (<600ms, 15x-22x real-time), crisp broadcast Odia, natural smoothing",
        "file": BENCHMARK_DIR / "1_mira_studio_voice.wav",
    },
    "2": {
        "title": "MIRA Studio Voice (Male / Kishore)",
        "desc": "Fast, authentic male Odia conversational host with grounded vocal presence",
        "file": BENCHMARK_DIR / "1_mira_studio_voice_kishore.wav",
    },
    "3": {
        "title": "Chatterbox 0.5B (Conversational ALM with Guided Emotion)",
        "desc": "Llama auto-regressive prosody backbone, guided emotion exaggeration, Roman phonetic bridge",
        "file": BENCHMARK_DIR / "3_chatterbox_0.5b.wav",
    },
}

def print_banner():
    print("\n" + "=" * 76)
    print("       MIRA ODIA VOICE ARCHITECTURE AUDITION & BENCHMARK CONSOLE       ")
    print("=" * 76)
    print("Benchmark Prompt:")
    print("  'ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ ଆପଣଙ୍କୁ ସ୍ୱାଗତ ।")
    print("   ଆଜି ଆପଣ କ'ଣ ଖାଇବାକୁ ପସନ୍ଦ କରିବେ ?")
    print("   ଆମ ପାଖରେ ମଟନ କସା ଏବଂ ଗରମ ନାନ୍ ବହୁତ ବଢ଼ିଆ ହୋଇଛି ।'")
    print("-" * 76)

def show_menu():
    print("\nSelect a voice architecture to audition:")
    for k, v in VOICES.items():
        exists = " [READY]" if v["file"].exists() else " [GENERATING]"
        print(f"  [{k}] {v['title']}{exists}")
        print(f"      Description: {v['desc']}")
        if v["file"].exists():
            try:
                info = sf.info(str(v["file"]))
                print(f"      Specs: {info.duration:.2f}s | {info.samplerate}Hz | Mono WAV")
            except Exception:
                pass
    print("  [4] Run Complete Voice Benchmark Suite")
    print("  [Q] Quit")
    print("-" * 76)

def play_audio(filepath: Path):
    if not filepath.exists():
        print(f"\n[ERROR] Audio file not found: {filepath}")
        print("Please ensure benchmark has been run to generate this file.")
        return

    print(f"\n>>> Playing: {filepath.name} ...")
    print("    (Press Ctrl+C to stop playback)")
    try:
        info = sf.info(str(filepath))
        print(f"    Duration: {info.duration:.2f}s | Sample Rate: {info.samplerate}Hz")
        winsound.PlaySound(str(filepath), winsound.SND_FILENAME)
        print("    Playback finished.")
    except KeyboardInterrupt:
        winsound.PlaySound(None, winsound.SND_PURGE)
        print("\n    Playback stopped by user.")
    except Exception as e:
        print(f"    Playback error: {e}")

def main():
    print_banner()
    while True:
        show_menu()
        choice = input("\nEnter choice (1-4, Q): ").strip().lower()
        if choice in ["q", "quit", "exit"]:
            print("\nExiting audition console. Goodbye!")
            break
        elif choice in VOICES:
            play_audio(VOICES[choice]["file"])
        elif choice == "4":
            print("\n>>> Launching full voice benchmark...")
            import subprocess
            subprocess.run([sys.executable, "openflow/alm/benchmark_voice_engines.py"])
        else:
            print("Invalid selection. Please choose an option from the menu.")

if __name__ == "__main__":
    main()
