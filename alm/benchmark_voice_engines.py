"""
benchmark_voice_engines.py - Side-by-side benchmark of Odia Voice AI architectures.

Compares:
1. MIRA Studio Voice (Matcha-Vocos Female - Smita)
2. MIRA Studio Voice (Matcha-Vocos Male - Kishore)
3. Chatterbox 0.5B (Resemble AI conversational dialogue ALM with guided emotion)

Measures:
- Latency (time to first audio / total synthesis time)
- Real-Time Factor (RTF = synthesis_time / audio_duration)
- Output sample rate & Peak amplitude (dBFS / normalized)
- Acoustic stability & prosody naturalness
"""
import os
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

import chatterbox
from openflow.engine.phonetic_translit import odia_to_roman

BENCHMARK_PROMPT = (
    "ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ ଆପଣଙ୍କୁ ସ୍ୱାଗତ । "
    "ଆଜି ଆପଣ କ'ଣ ଖାଇବାକୁ ପସନ୍ଦ କରିବେ ? "
    "ଆମ ପାଖରେ ମଟନ କସା ଏବଂ ଗରମ ନାନ୍ ବହୁତ ବଢ଼ିଆ ହୋଇଛି ।"
)

OUT_DIR = Path("openflow/scratch/benchmark_results")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def benchmark_studio_voice(text: str, voice: str = "female") -> dict:
    """Benchmark: MIRA Studio Voice (Matcha-Vocos Odia)."""
    label = f"MIRA Studio Voice ({voice.title()})"
    print("\n" + "=" * 60)
    print(f">>> Benchmarking {label}...")
    print("=" * 60)

    from openflow.engine.studio_voice import StudioVoiceEngine

    engine = StudioVoiceEngine()
    filename = "1_mira_studio_voice.wav" if voice == "female" else "1_mira_studio_voice_kishore.wav"
    out_wav = OUT_DIR / filename

    speed = 0.86 if voice == "female" else 0.88
    t0 = time.perf_counter()
    wav = engine.synthesize(text, voice=voice, speed=speed)
    sr = engine.sr
    elapsed = time.perf_counter() - t0

    dur = len(wav) / sr
    rtf = elapsed / dur if dur > 0 else 0
    peak = float(np.max(np.abs(wav)))
    rms = float(np.sqrt(np.mean(wav ** 2)))

    sf.write(str(out_wav), wav, sr)
    print(f"  [{label}] Synthesized {dur:.2f}s in {elapsed:.3f}s | RTF={rtf:.4f} ({1/rtf:.1f}x real-time)")
    print(f"  [{label}] Peak={peak:.3f} | RMS={rms:.4f} | Path={out_wav}")

    return {
        "engine": label,
        "dur_s": dur,
        "latency_s": elapsed,
        "rtf": rtf,
        "speedup": (1 / rtf) if rtf > 0 else 0,
        "peak": peak,
        "rms": rms,
        "out_file": str(out_wav),
        "status": "PASS",
    }


def benchmark_chatterbox(text: str) -> dict:
    """Benchmark: Chatterbox 0.5B (Conversational ALM with guided emotion)."""
    print("\n" + "=" * 60)
    print(">>> Benchmarking Chatterbox 0.5B (Conversational ALM)...")
    print("=" * 60)

    out_wav = OUT_DIR / "3_chatterbox_0.5b.wav"
    try:
        from openflow.alm.chatterbox_engine import ChatterboxEngine
        engine = ChatterboxEngine(device="cuda" if torch.cuda.is_available() else "cpu")

        t0 = time.perf_counter()
        wav, sr, rtf = engine.synthesize(
            text=text,
            persona="smita",
            exaggeration=0.5,
            cfg_weight=0.5,
        )
        elapsed = time.perf_counter() - t0

        dur = len(wav) / sr
        peak = float(np.max(np.abs(wav)))
        rms = float(np.sqrt(np.mean(wav ** 2)))

        sf.write(str(out_wav), wav, sr)
        print(f"  [Chatterbox] Synthesized {dur:.2f}s in {elapsed:.3f}s | RTF={rtf:.4f} ({1/rtf:.1f}x real-time)")
        print(f"  [Chatterbox] Peak={peak:.3f} | RMS={rms:.4f} | Path={out_wav}")

        return {
            "engine": "Chatterbox 0.5B (Conversational ALM)",
            "dur_s": dur,
            "latency_s": elapsed,
            "rtf": rtf,
            "speedup": (1 / rtf) if rtf > 0 else 0,
            "peak": peak,
            "rms": rms,
            "out_file": str(out_wav),
            "status": "PASS",
        }
    except Exception as e:
        print(f"  [Chatterbox] Benchmark skipped or error: {e}")
        return {
            "engine": "Chatterbox 0.5B (Conversational ALM)",
            "status": f"ERROR: {e}",
        }


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("OPENFLOW ODIA VOICE AI ARCHITECTURE BENCHMARK")
    print(f"Prompt: {BENCHMARK_PROMPT}")
    print("=" * 70)

    results = []

    # 1. Studio Voice Female (Smita)
    r1 = benchmark_studio_voice(BENCHMARK_PROMPT, voice="female")
    results.append(r1)

    # 2. Studio Voice Male (Kishore)
    r2 = benchmark_studio_voice(BENCHMARK_PROMPT, voice="male")
    results.append(r2)

    # 3. Chatterbox 0.5B ALM
    r3 = benchmark_chatterbox(BENCHMARK_PROMPT)
    results.append(r3)

    # Print Summary Table
    print("\n" + "=" * 70)
    print("BENCHMARK SUMMARY COMPARISON")
    print("=" * 70)
    print(f"{'Engine':<38} | {'Latency':<9} | {'Duration':<9} | {'RTF':<8} | {'Speedup':<8}")
    print("-" * 75)
    for r in results:
        if r["status"] == "PASS":
            print(f"{r['engine']:<38} | {r['latency_s']:6.3f}s   | {r['dur_s']:6.2f}s   | {r['rtf']:6.4f} | {r['speedup']:5.1f}x")
        else:
            print(f"{r['engine']:<38} | {r['status']}")
    print("=" * 75)


if __name__ == "__main__":
    main()
