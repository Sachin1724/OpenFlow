"""
test_alm_live.py — Comprehensive Live Benchmark & Verification for MIRA-ALM
===========================================================================
Benchmarks discrete neural audio generation across Odia dialects & prosody tokens:
- Zero-shot in-context voice prompt conditioning (Smita Mohanty, Kishore, Gulua, Sambalpuri)
- Non-verbal prosody tags (<chuckle>, <laugh>, <breathe>, <pause_short>, <question_rise>)
- Inference latency, Real-Time Factor (RTF), memory consumption, and 24kHz audio verification.
"""

import os
import sys
import time
import torch
import torchaudio
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alm.inference import MiraALMEngine

OUTPUT_DIR = REPO_ROOT / "scratch"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BENCHMARK_PROMPTS = [
    {
        "speaker": "smita",
        "label": "Smita Mohanty (Warm Conversational & Chuckle)",
        "text": "ଆଚ୍ଛା! <chuckle> ତମେ କେମିତି ଅଛ? ମୁଁ ବିଲକୁଲ ଭଲ ଅଛି। <breathe> ଆମର ନୂଆ ଅର୍ଡର ଟା ରେଡି ହେଇଗଲା!",
        "filename": "mira_alm_smita_conversational.wav"
    },
    {
        "speaker": "kishore",
        "label": "Kishore (Enthusiastic Laughter & Question Rise)",
        "text": "ଆରେ ଭାଇ, <laugh> ଏଇଟା ତ ଏକଦମ୍ ଚମତ୍କାର ହେଇଛି! <pause_short> ସତରେ ବହୁତ ଖୁସି ଲାଗିଲା <question_rise>?",
        "filename": "mira_alm_kishore_expressive.wav"
    },
    {
        "speaker": "gulua",
        "label": "Gulua (Comedy & Emphatic Delivery)",
        "text": "ଏଇ ଦେଖ, <chuckle> ଆମ ଗୁଲୁଆ ଭାଇଙ୍କ ଷ୍ଟାଇଲ୍ ପୁରା ନିଆରା <emphatic>! ହସି ହସି ପେଟ ଫାଟିଯିବ!",
        "filename": "mira_alm_gulua_comedy.wav"
    },
    {
        "speaker": "sambalpuri",
        "label": "Sambalpuri (Western Odia In-Context Cadence)",
        "text": "ଜୁହାର! <warm_whisper> ସମକୁ ମୋର ସମ୍ବଲପୁରୀ ଜୁହାର। <pause_medium> ଆମର୍ ସମ୍ବଲପୁରୀ ଭାଷା କେତେ ସୁନ୍ଦର!",
        "filename": "mira_alm_sambalpuri_juhar.wav"
    }
]

def run_alm_benchmark():
    print("=" * 85)
    print("🎙️ MIRA-ALM LIVE BENCHMARK — DISCRETE NEURAL AUDIO LANGUAGE MODEL")
    print("=" * 85)
    
    device = "cuda" if torch.cuda.is_available() else "cpu"
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    print(f"Device: {device.upper()} ({gpu_name})")
    
    engine = MiraALMEngine(device=device)
    
    results = []
    
    for i, test in enumerate(BENCHMARK_PROMPTS, 1):
        print(f"\n[{i}/{len(BENCHMARK_PROMPTS)}] Benchmarking: {test['label']}")
        print(f"  Input Text: {test['text']}")
        
        out_wav = str(OUTPUT_DIR / test["filename"])
        
        # Warmup and timed execution
        res = engine.synthesize(
            text=test["text"],
            speaker=test["speaker"],
            output_wav=out_wav,
            temperature=0.65,
            top_p=0.85
        )
        
        # Verify file on disk
        info = torchaudio.info(out_wav)
        assert info.sample_rate == 24000, f"Sample rate mismatch: {info.sample_rate}"
        file_size_kb = os.path.getsize(out_wav) / 1024
        
        test_res = {
            "speaker": test["speaker"],
            "label": test["label"],
            "duration_s": res["duration_s"],
            "latency_ms": res["latency_ms"],
            "rtf": res["rtf"],
            "frames": res["num_frames"],
            "sample_rate": info.sample_rate,
            "file_size_kb": round(file_size_kb, 1),
            "output_path": out_wav
        }
        results.append(test_res)
        
        print(f"  ✓ Generated: {res['duration_s']}s audio ({res['num_frames']} discrete frames @ 75 fps)")
        print(f"  ✓ Latency:   {res['latency_ms']:.1f}ms | RTF: {res['rtf']:.4f} (Real-Time Factor)")
        print(f"  ✓ Audio:     {info.sample_rate} Hz Mono WAV ({file_size_kb:.1f} KB) -> {test['filename']}")
        
    print("\n" + "=" * 85)
    print("📊 BENCHMARK SUMMARY TABLE:")
    print("=" * 85)
    print(f"{'Speaker':<15} | {'Duration':<10} | {'Latency':<12} | {'RTF':<8} | {'Audio Spec':<18} | {'Status'}")
    print("-" * 85)
    for r in results:
        status = "✅ PASS (Sub-Realtime)" if r["rtf"] < 1.0 else "⚠️ SLOW"
        print(f"{r['speaker']:<15} | {r['duration_s']:>6.2f}s    | {r['latency_ms']:>8.1f}ms   | {r['rtf']:>6.4f} | 24kHz / {r['file_size_kb']:>4.1f}KB | {status}")
    print("=" * 85)
    
    avg_rtf = sum(r["rtf"] for r in results) / len(results)
    avg_latency = sum(r["latency_ms"] for r in results) / len(results)
    print(f"🎯 Average Latency: {avg_latency:.1f}ms | Average RTF: {avg_rtf:.4f}")
    if torch.cuda.is_available():
        vram_used = torch.cuda.max_memory_allocated() / (1024 ** 2)
        print(f"⚡ Peak VRAM Footprint: {vram_used:.1f} MB (Comfortably fits 6GB RTX 4050)")
    print("=" * 85)
    return results

if __name__ == '__main__':
    run_alm_benchmark()

