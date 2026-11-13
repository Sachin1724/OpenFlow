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
    "0": {
        "title": "Your Enrolled Cloned Voice (Sam / 129.7 Hz Baritone)",
        "desc": "Calibrated directly from your live microphone recording with natural chest resonance",
        "file": BENCHMARK_DIR / "cloned_user_sam.wav",
    },
    "1": {
        "title": "MIRA Normal Conversation (Female / Smita)",
        "desc": "Natural, everyday conversational assistant: 'ନମସ୍କାର ! ମୁଁ ମୀରା । ଆପଣ କେମିତି ଅଛନ୍ତି ?...'",
        "file": BENCHMARK_DIR / "normal_female.wav",
    },
    "2": {
        "title": "MIRA Normal Conversation (Male / Kishore)",
        "desc": "Natural, everyday conversational assistant: 'ନମସ୍କାର ! ମୁଁ ମୀରା । ଆପଣ କେମିତି ଅଛନ୍ତି ?...'",
        "file": BENCHMARK_DIR / "normal_male.wav",
    },
    "3": {
        "title": "MIRA Restaurant Benchmark (Female / Smita)",
        "desc": "Fine-tuned restaurant host dialogue: 'ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ...'",
        "file": BENCHMARK_DIR / "1_mira_studio_voice.wav",
    },
    "4": {
        "title": "MIRA Restaurant Benchmark (Male / Kishore)",
        "desc": "Fine-tuned restaurant host dialogue: 'ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ...'",
        "file": BENCHMARK_DIR / "1_mira_studio_voice_kishore.wav",
    },
    "5": {
        "title": "Real Human Podcast Audio (Elina Samantray Harvest Reference)",
        "desc": "Original 24kHz studio recording of Elina Samantray from the harvested podcast set",
        "file": BENCHMARK_DIR / "raw_human_sample.wav",
    },
    "6": {
        "title": "Chatterbox 0.5B (Conversational ALM with Guided Emotion)",
        "desc": "Llama auto-regressive prosody backbone, guided emotion exaggeration",
        "file": BENCHMARK_DIR / "3_chatterbox_0.5b.wav",
    },
    "7": {
        "title": "Zero-Shot Cloned Voice (Elina Samantray / Temperature 0.67)",
        "desc": "Cloned from podcast harvest using ERes2Net continuous vector injection",
        "file": BENCHMARK_DIR / "cloned_elina_samantray.wav",
    },
    "8": {
        "title": "Zero-Shot Cloned Voice (Smita Mohanty / Calm Steady T=0.30)",
        "desc": "Low stochasticity Euler ODE flow-matching (calm deterministic cadence)",
        "file": BENCHMARK_DIR / "cloned_smita_calm_temp03.wav",
    },
    "9": {
        "title": "Zero-Shot Cloned Voice (Smita Mohanty / Expressive T=1.00)",
        "desc": "High stochasticity Euler ODE flow-matching (expressive pitch inflections)",
        "file": BENCHMARK_DIR / "cloned_smita_expressive_temp10.wav",
    },
}

def print_banner():
    print("\n" + "=" * 76)
    print("       MIRA ODIA VOICE ARCHITECTURE AUDITION & BENCHMARK CONSOLE       ")
    print("=" * 76)
    print("Sample Prompts:")
    print("  Normal: 'ନମସ୍କାର ! ମୁଁ ମୀରା । ଆପଣ କେମିତି ଅଛନ୍ତି ? ଆଜି ଆପଣଙ୍କ ଦିନ କିପରି କଟିଲା ?'")
    print("  Benchmark: 'ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ ଆପଣଙ୍କୁ ସ୍ୱାଗତ ।...'")
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
    print("  [B] Run Complete Voice Benchmark Suite")
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
        choice = input("\nEnter choice (1-9, B, Q): ").strip().lower()
        if choice in ["q", "quit", "exit"]:
            print("\nExiting audition console. Goodbye!")
            break
        elif choice in VOICES:
            play_audio(VOICES[choice]["file"])
        elif choice == "b":
            print("\n>>> Launching full voice benchmark...")
            import subprocess
            subprocess.run([sys.executable, "openflow/alm/benchmark_voice_engines.py"])
        else:
            print("Invalid selection. Please choose an option from the menu.")

if __name__ == "__main__":
    main()
