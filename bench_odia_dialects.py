"""
bench_odia_dialects.py — Benchmark Real Odia Audio across Dialects, Background Music, and Code-Mixing
=====================================================================================================
Evaluates OpenFlow's Odia speech pipeline on authentic podcast speech:
1. Standard / Coastal Odia (Kataki)
2. Conversational Code-Mixed Odia (English loanwords: charm, response, second, etc.)
3. Sambalpuri / Western Odia (Kosali folk song rhythm & dialect)
4. Fast Dialogue with background music
"""

import os
import sys
import time
import wave
import subprocess
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import model_manager
from engine.indic_asr import IndicCTC
from engine.odia_mix import to_mixed
from engine.translator import OdiaToEnglish

SCRATCH_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
ODIA_M4A = os.path.join(SCRATCH_DIR, "odia_podcast.m4a")

BENCH_SECTIONS = [
    {
        "dialect": "Standard Coastal Odia (Kataki)",
        "desc": "Interview opening & personal background",
        "start": 120,
        "dur": 25,
        "wav": os.path.join(SCRATCH_DIR, "bench_standard_odia.wav")
    },
    {
        "dialect": "Conversational Code-Mixed Odia",
        "desc": "Audience response, charm, work ethics (English loanwords)",
        "start": 300,
        "dur": 25,
        "wav": os.path.join(SCRATCH_DIR, "bench_codemixed_odia.wav")
    },
    {
        "dialect": "Sambalpuri Dialect (Western Odia)",
        "desc": "Discussion of Sambalpuri folk music & singing rhythm",
        "start": 420,
        "dur": 25,
        "wav": os.path.join(SCRATCH_DIR, "bench_sambalpuri_odia.wav")
    },
    {
        "dialect": "Rapid Dialogue with Background Music",
        "desc": "Fast conversational exchanges with studio ambient score",
        "start": 540,
        "dur": 25,
        "wav": os.path.join(SCRATCH_DIR, "bench_music_odia.wav")
    }
]


def extract_clip(src_m4a, start, dur, out_wav):
    cmd = [
        "ffmpeg", "-y", "-ss", str(start), "-i", src_m4a,
        "-t", str(dur), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        out_wav
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def load_audio(wav_path):
    with wave.open(wav_path, "rb") as wf:
        raw = wf.readframes(wf.getnframes())
    return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0


def main():
    print("=" * 85)
    print("OPENFLOW REAL ODIA AUDIO BENCHMARK (MULTI-DIALECT & BACKGROUND MUSIC)")
    print("=" * 85)

    if not os.path.exists(ODIA_M4A):
        print(f"Error: {ODIA_M4A} not found.")
        return

    # Load Odia IndicCTC
    odia_root = model_manager.cached_path("odia")
    model_folder = os.path.join(odia_root, "or")
    indic_ctc = IndicCTC(model_folder, threads=8)

    # Load IndicTrans2 for English translation
    tr_dir = os.path.join(model_manager.cached_path("odia-en"), model_manager.TRANSLATOR_DIR)
    translator = OdiaToEnglish(tr_dir, threads=8)

    results = []

    for item in BENCH_SECTIONS:
        print(f"\n--- Testing: {item['dialect']} ({item['dur']}s) ---")
        print(f"Context: {item['desc']}")
        extract_clip(ODIA_M4A, item["start"], item["dur"], item["wav"])
        audio = load_audio(item["wav"])

        t0 = time.time()
        raw_odia = indic_ctc.text(audio, beam=False)
        lat_asr = time.time() - t0
        speed_x = item["dur"] / max(0.01, lat_asr)

        # Apply OdiaMix
        t_mix = to_mixed(raw_odia)

        # Apply English Translation
        t1 = time.time()
        en_trans = translator.translate(raw_odia)
        lat_trans = time.time() - t1

        results.append({
            "dialect": item["dialect"],
            "dur": item["dur"],
            "lat_asr": lat_asr,
            "speed_x": speed_x,
            "raw_odia": raw_odia,
            "mixed_odia": t_mix,
            "en_trans": en_trans
        })

        print(f"ASR Latency: {lat_asr:.3f}s | Speed: {speed_x:.1f}x real-time")
        print(f"Raw Odia Output:")
        sys.stdout.buffer.write(f"  {raw_odia}\n".encode("utf-8"))
        print(f"Code-Mixed Output:")
        sys.stdout.buffer.write(f"  {t_mix}\n".encode("utf-8"))
        print(f"English Translation:")
        print(f"  {en_trans}")

    print("\n" + "=" * 85)
    print(f"{'Dialect / Speech Style':<36} | {'Audio':<6} | {'ASR Latency':<12} | {'Speed':<10}")
    print("-" * 85)
    for r in results:
        print(f"{r['dialect']:<36} | {r['dur']:<4.0f}s | {r['lat_asr']:<10.3f}s | {r['speed_x']:<6.1f}x")
    print("=" * 85)


if __name__ == "__main__":
    main()
