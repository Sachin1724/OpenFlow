"""
play_voice_benchmark.py - Interactive Audio Player & Benchmark Audition Console
================================================================================
Allows listening to and comparing the three next-gen Odia voice architectures:
1. MIRA Studio Voice (Matcha-Vocos fine-tuned Odia acoustic engine)
2. MIRA F5-TTS (Zero-shot Flow-Matching Diffusion Transformer)
3. Chatterbox 0.5B (Resemble AI conversational dialogue ALM with guided emotion)
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
        "title": "MIRA Studio Voice (Matcha-Vocos Odia)",
        "desc": "Ultra-low latency (<600ms, 22.6x real-time), crisp broadcast Odia, natural smoothing",
        "file": BENCHMARK_DIR / "1_mira_studio_voice.wav",
    },
    "2": {
        "title": "MIRA F5-TTS (Zero-Shot DiT - Smita Voice Clone)",
        "desc": "Flow-Matching Euler ODE solver, cloned from 3s reference audio, rich prosody",
        "file": BENCHMARK_DIR / "2_mira_f5_tts.wav",
    },
    "3": {
        "title": "MIRA F5-TTS (Zero-Shot DiT - Kishore Voice Clone)",
        "desc": "Male voice reference clone with expressive natural intonation",
        "file": BENCHMARK_DIR / "2_mira_f5_tts_kishore.wav",
    },
    "4": {
        "title": "Chatterbox 0.5B (Conversational ALM with Guided Emotion)",
        "desc": "Llama auto-regressive prosody backbone, guided emotion exaggeration, Devanagari bridge",
        "file": BENCHMARK_DIR / "3_chatterbox_0.5b.wav",
    },
}

def print_banner():
    print("\n" + "=" * 76)
    print("       MIRA NEXT-GEN VOICE ARCHITECTURE AUDITION & BENCHMARK CONSOLE       ")
    print("=" * 76)
    print("Benchmark Prompt:")
    print("  'ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ ଆପଣଙ୍କୁ ସ୍ୱାଗତ ।")
    print("   ଆଜି ଆପଣ କ'ଣ ଖାଇବାକୁ ପସନ୍ଦ କରିବେ ?")
    print("   ଆମ ପାଖରେ ମଟନ କସା ଏବଂ ଗରମ ନାନ୍ ବହୁତ ବଢ଼ିଆ ହୋଇଛି ।'")
    print("-" * 76)

def show_menu():
    print("\nSelect a voice architecture to audition:")
    for k, v in VOICES.items():
        exists = " [READY]" if v["file"].exists() else " [GENERATING / DOWNLOADING]"
        print(f"  [{k}] {v['title']}{exists}")
        print(f"      Description: {v['desc']}")
        if v["file"].exists():
            try:
                info = sf.info(str(v["file"]))
                print(f"      Specs: {info.duration:.2f}s | {info.samplerate}Hz | Mono WAV")
            except Exception:
                pass
    print("  [5] Run Complete 3-Way Benchmark Suite")
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
        choice = input("\nEnter choice (1-5, Q): ").strip().lower()
        if choice in ["q", "quit", "exit"]:
            print("\nExiting audition console. Goodbye!")
            break
        elif choice in VOICES:
            play_audio(VOICES[choice]["file"])
        elif choice == "5":
            print("\n>>> Launching full 3-way benchmark...")
            import subprocess
            subprocess.run([sys.executable, "openflow/alm/benchmark_voice_engines.py"])
        else:
            print("\nInvalid choice. Please select 1, 2, 3, 4, 5, or Q.")

if __name__ == "__main__":
    main()

