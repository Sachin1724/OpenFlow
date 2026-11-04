"""
bench_real_dialects.py — Benchmark OpenFlow on Real Odia Dialect Audio Recordings
=================================================================================
Tests OpenFlow's IndicCTC model on authentic recordings across 6 Odia dialects:
Standard Odia (Puri/Cuttack), Ganjami, Anugulia, Sambalpuri, Baleswari, Kalahandia.
"""

import os
import sys
import csv
import time
import subprocess
import numpy as np

# Force UTF-8 stdout
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import model_manager
from engine.indic_asr import IndicCTC
from engine.odia_mix import to_mixed

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "OdiaTTS_Data")
CSV_PATH = os.path.join(DATA_DIR, "metadata.csv")


def load_audio_resampled(file_path):
    """Decodes WebM/Opus/WAV directly to 16kHz mono float32 via ffmpeg pipe."""
    cmd = [
        "ffmpeg", "-y", "-i", file_path,
        "-f", "s16le", "-ar", "16000", "-ac", "1", "-"
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return np.frombuffer(res.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def main():
    print("=" * 90)
    print("OPENFLOW REAL ODIA REGIONAL DIALECT AUDIO BENCHMARK (19 DISTRICTS)")
    print("=" * 90)

    # Load Odia IndicCTC
    odia_root = model_manager.cached_path("odia")
    model_folder = os.path.join(odia_root, "or")
    indic_ctc = IndicCTC(model_folder, threads=8)

    # Read metadata
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Pick 1 sample per dialect
    target_dialects = ["Standard Odia", "Sambalpuri", "Ganjami", "Anugulia", "Baleswari", "Kalahandia"]
    samples = {}
    for r in rows:
        d = r.get("dialect")
        fn = r.get("audio_filename")
        if d in target_dialects and d not in samples and fn:
            p = os.path.join(DATA_DIR, fn.strip())
            if os.path.exists(p):
                samples[d] = r

    results = []
    for dialect in target_dialects:
        if dialect not in samples:
            continue
        info = samples[dialect]
        wav_path = os.path.join(DATA_DIR, info["audio_filename"].strip())
        audio = load_audio_resampled(wav_path)
        dur = len(audio) / 16000.0

        t0 = time.time()
        raw_odia = indic_ctc.text(audio, beam=False)
        lat = time.time() - t0
        speed_x = dur / max(0.001, lat)

        results.append({
            "dialect": dialect,
            "district": info.get("district", ""),
            "speaker": info.get("name", "").strip(),
            "dur": dur,
            "lat": lat,
            "speed": speed_x,
            "reference": info.get("standard_text", "").strip(),
            "spoken": info.get("translated_text", "").strip(),
            "predicted": raw_odia
        })

        print(f"\n[{dialect.upper()} — {info.get('district', '')}] Speaker: {info.get('name', '').strip()} ({dur:.1f}s)")
        print(f"Ground Truth Ref : {info.get('standard_text', '').strip()}")
        print(f"Spoken Form      : {info.get('translated_text', '').strip()}")
        print(f"Predicted Output : {raw_odia}")
        print(f"Latency: {lat:.3f}s | Speed: {speed_x:.1f}x real-time")

    print("\n" + "=" * 90)
    print(f"{'Dialect':<15} | {'District':<12} | {'Duration':<8} | {'Latency':<10} | {'Speed':<8}")
    print("-" * 90)
    for r in results:
        print(f"{r['dialect']:<15} | {r['district']:<12} | {r['dur']:<6.1f}s | {r['lat']:<8.3f}s | {r['speed']:<6.1f}x")
    print("=" * 90)


if __name__ == "__main__":
    main()
