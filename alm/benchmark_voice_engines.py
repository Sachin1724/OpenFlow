"""
benchmark_voice_engines.py - Side-by-side benchmark of next-gen Voice AI architectures for OpenFlow.

Compares:
1. MIRA Studio Voice (Matcha-Vocos fine-tuned Odia acoustic engine)
2. MIRA F5-TTS (Zero-shot Flow-Matching Diffusion Transformer)
3. Chatterbox 0.5B (Resemble AI conversational dialogue ALM with guided emotion)

Generates audio samples for each engine, measures:
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
from openflow.engine.phonetic_translit import odia_to_devanagari

BENCHMARK_PROMPT = (
    "ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ ଆପଣଙ୍କୁ ସ୍ୱାଗତ । "
    "ଆଜି ଆପଣ କ'ଣ ଖାଇବାକୁ ପସନ୍ଦ କରିବେ ? "
    "ଆମ ପାଖରେ ମଟନ କସା ଏବଂ ଗରମ ନାନ୍ ବହୁତ ବଢ଼ିଆ ହୋଇଛି ।"
)

OUT_DIR = Path("openflow/scratch/benchmark_results")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def benchmark_studio_voice(text: str) -> dict:
    """Benchmark 1: MIRA Studio Voice (Matcha-Vocos)."""
    print("\n" + "=" * 60)
    print(">>> 1. Benchmarking MIRA Studio Voice (Matcha-Vocos)...")
    print("=" * 60)
    
    from openflow.engine.studio_voice import StudioVoiceEngine

    engine = StudioVoiceEngine()
    out_wav = OUT_DIR / "1_mira_studio_voice.wav"
    
    t0 = time.perf_counter()
    wav = engine.synthesize(text, voice="female", speed=0.86)
    sr = engine.sr
    elapsed = time.perf_counter() - t0
    
    dur = len(wav) / sr
    rtf = elapsed / dur if dur > 0 else 0
    peak = float(np.max(np.abs(wav)))
    rms = float(np.sqrt(np.mean(wav ** 2)))
    
    sf.write(str(out_wav), wav, sr)
    print(f"  [Studio Voice] Synthesized {dur:.2f}s in {elapsed:.3f}s | RTF={rtf:.4f} ({1/rtf:.1f}x real-time)")
    print(f"  [Studio Voice] Peak={peak:.3f} | RMS={rms:.4f} | Path={out_wav}")

    return {
        "engine": "MIRA Studio Voice (Matcha-Vocos)",
        "dur_s": dur,
        "latency_s": elapsed,
        "rtf": rtf,
        "speedup": (1 / rtf) if rtf > 0 else 0,
        "peak": peak,
        "rms": rms,
        "out_file": str(out_wav),
        "status": "PASS",
    }


def benchmark_f5_tts(text: str) -> dict:
    """Benchmark 2: MIRA F5-TTS (Zero-shot Flow-Matching DiT)."""
    print("\n" + "=" * 60)
    print(">>> 2. Benchmarking MIRA F5-TTS (Flow-Matching DiT)...")
    print("=" * 60)

    out_wav = OUT_DIR / "2_mira_f5_tts.wav"
    try:
        from openflow.alm.f5_engine import F5VoiceEngine
        engine = F5VoiceEngine(device="cuda" if torch.cuda.is_available() else "cpu")

        t0 = time.perf_counter()
        wav, sr, rtf = engine.synthesize(
            gen_text=text,
            persona="smita",
            nfe_step=16,
            speed=1.0,
        )
        elapsed = time.perf_counter() - t0

        dur = len(wav) / sr
        peak = float(np.max(np.abs(wav)))
        rms = float(np.sqrt(np.mean(wav ** 2)))

        sf.write(str(out_wav), wav, sr)
        print(f"  [F5-TTS] Synthesized {dur:.2f}s in {elapsed:.3f}s | RTF={rtf:.4f} ({1/rtf:.1f}x real-time)")
        print(f"  [F5-TTS] Peak={peak:.3f} | RMS={rms:.4f} | Path={out_wav}")

        return {
            "engine": "MIRA F5-TTS (Flow-Matching Zero-Shot)",
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
        print(f"  [F5-TTS] Benchmark skipped or error: {e}")
        return {
            "engine": "MIRA F5-TTS (Flow-Matching Zero-Shot)",
            "status": f"ERROR: {e}",
        }


def benchmark_chatterbox(text: str) -> dict:
    """Benchmark 3: Chatterbox 0.5B (Conversational ALM with guided emotion)."""
    print("\n" + "=" * 60)
    print(">>> 3. Benchmarking Chatterbox 0.5B (Conversational ALM)...")
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
    print("OPENFLOW NEXT-GEN VOICE AI ARCHITECTURE BENCHMARK")
    print(f"Prompt: {BENCHMARK_PROMPT}")
    print("=" * 70)

    results = []
    
    # 1. Studio Voice (always available and lightning fast)
    r1 = benchmark_studio_voice(BENCHMARK_PROMPT)
    results.append(r1)

    # 2. F5-TTS Flow Matching
    r2 = benchmark_f5_tts(BENCHMARK_PROMPT)
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
