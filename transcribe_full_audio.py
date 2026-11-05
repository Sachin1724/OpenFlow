"""
transcribe_full_audio.py — Full-Length Audio Transcriber & Dialogue Extractor
=============================================================================
Processes complete 30-to-90 minute Odia podcasts and comedy videos:
1. Fast streaming chunking (15s windows)
2. SOTA IndicConformer CTC ASR decoding (~44x real-time speed)
3. MIRA sub-millisecond phonetic normalization & emotion restoration
4. Exports:
   - Full human-readable transcript with [MM:SS] timestamps
   - Structured JSONL dialogue pairs for model learning
   - Colloquial slang & discourse marker frequency statistics
"""

import os
import sys
import io
import time
import json
import argparse
import subprocess
import numpy as np
import soundfile as sf

# Force UTF-8 stdout with immediate line flushing
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# Ensure openflow modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.indic_asr import IndicCTC
from engine.dialect_normalizer import get_dialect_normalizer
from huggingface_hub import snapshot_download


def format_timestamp(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def transcribe_full_file(audio_path: str, output_dir: str = "openflow/data/harvested_scripts", chunk_sec: float = 15.0):
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    txt_out = os.path.join(output_dir, f"{base_name}_full_script.txt")
    jsonl_out = os.path.join(output_dir, f"{base_name}_dialogue_pairs.jsonl")
    stats_out = os.path.join(output_dir, f"{base_name}_linguistic_stats.json")

    print("=" * 80)
    print(f"🎙️ FULL-LENGTH AUDIO TRANSCRIPTION: {os.path.basename(audio_path)}")
    print("=" * 80)

    # 1. Convert to 16kHz mono WAV via ffmpeg pipe
    temp_wav = f"openflow/scratch/{base_name}_16k.wav"
    print(f"[Step 1] Converting {audio_path} to 16kHz mono PCM...")
    cmd = [
        "ffmpeg", "-i", audio_path,
        "-ar", "16000", "-ac", "1",
        temp_wav, "-y"
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 2. Load audio metadata & data
    info = sf.info(temp_wav)
    total_sec = info.duration
    sr = info.samplerate
    print(f"  Duration: {total_sec // 60:.0f}m {total_sec % 60:.1f}s ({total_sec:.1f} seconds total)")

    # 3. Load ASR & Normalizer
    print("[Step 2] Loading IndicConformer ASR & MIRA Normalizer...")
    snap = snapshot_download("sachinmallick/openflow-odia-asr-int8")
    or_folder = os.path.join(snap, "or")
    asr = IndicCTC(or_folder, threads=4)
    normalizer = get_dialect_normalizer()

    # 4. Stream and Transcribe in chunks
    chunk_samples = int(chunk_sec * sr)
    total_samples = info.frames
    num_chunks = int(np.ceil(total_samples / chunk_samples))
    print(f"[Step 3] Processing {num_chunks} chunks ({chunk_sec}s each)...")

    full_script_lines = []
    dialogue_pairs = []
    word_counts = {}
    emotions = {"statement": 0, "question": 0, "exclamatory": 0}
    total_words = 0

    t_start = time.perf_counter()

    with sf.SoundFile(temp_wav) as f:
        for chunk_idx in range(num_chunks):
            data = f.read(chunk_samples, dtype="float32")
            if len(data) < 1600:  # skip under 0.1s
                continue

            t_cur = chunk_idx * chunk_sec
            ts_str = format_timestamp(t_cur)

            # Transcribe
            raw_text = asr.text(data, beam=True)
            if not raw_text.strip():
                continue

            # MIRA Normalization & Emotion
            norm_res = normalizer.normalize(raw_text)
            clean_text = norm_res["normalized"]
            emotion = norm_res.get("emotion", "statement")
            if emotion in emotions:
                emotions[emotion] += 1

            # Count words & particles
            words = clean_text.split()
            total_words += len(words)
            for w in words:
                word_counts[w] = word_counts.get(w, 0) + 1

            line = f"[{ts_str}] {clean_text}"
            full_script_lines.append(line)

            # Build dialogue pair for continuous model learning
            if len(full_script_lines) >= 2:
                dialogue_pairs.append({
                    "messages": [
                        {"role": "user", "content": full_script_lines[-2].split("] ", 1)[-1]},
                        {"role": "assistant", "content": clean_text}
                    ],
                    "timestamp": ts_str,
                    "emotion": emotion
                })

            if (chunk_idx + 1) % 15 == 0 or (chunk_idx + 1) == num_chunks:
                pct = ((chunk_idx + 1) / num_chunks) * 100
                elapsed = time.perf_counter() - t_start
                speed_x = (t_cur + chunk_sec) / max(0.1, elapsed)
                print(f"  Progress: {pct:5.1f}% [{ts_str} / {format_timestamp(total_sec)}] | Speed: {speed_x:4.1f}x real-time | Words: {total_words}")

    total_proc_time = time.perf_counter() - t_start
    overall_speed = total_sec / max(0.1, total_proc_time)

    # 5. Save Outputs
    # A. Full text transcript
    with open(txt_out, "w", encoding="utf-8") as f:
        f.write(f"# Full Audio Transcript: {base_name}\n")
        f.write(f"# Total Duration: {total_sec // 60:.0f}m {total_sec % 60:.1f}s\n")
        f.write(f"# Transcribed in {total_proc_time:.1f}s ({overall_speed:.1f}x real-time speed)\n\n")
        f.write("\n".join(full_script_lines))

    # B. Dialogue pairs JSONL
    with open(jsonl_out, "w", encoding="utf-8") as f:
        for pair in dialogue_pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    # C. Linguistic Statistics
    top_particles = {
        k: word_counts.get(k, 0)
        for k in ["ପରା", "ବେ", "ସେଇଠୁ", "ଆଜ୍ଞା", "ଭାଇନା", "ମାନେ", "ହଁ", "ଆଚ୍ଛା", "ଠିକ୍", "ଧତ୍", "ବାବୁ"]
    }
    stats = {
        "file": base_name,
        "duration_seconds": round(total_sec, 2),
        "transcription_seconds": round(total_proc_time, 2),
        "speed_factor": round(overall_speed, 1),
        "total_words_spoken": total_words,
        "speech_rate_words_per_minute": round((total_words / total_sec) * 60, 1),
        "emotions_breakdown": emotions,
        "key_discourse_particles": top_particles
    }
    with open(stats_out, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    # Clean up temp wav
    if os.path.exists(temp_wav):
        try:
            os.remove(temp_wav)
        except Exception:
            pass

    print("\n" + "=" * 80)
    print(f"🎉 TRANSCRIPTION COMPLETE: {base_name}")
    print(f"⏱️  Duration      : {total_sec // 60:.0f}m {total_sec % 60:.1f}s transcribed in {total_proc_time:.1f}s ({overall_speed:.1f}x speed)")
    print(f"📝 Total Words   : {total_words:,} words (Rate: {stats['speech_rate_words_per_minute']} wpm)")
    print(f"🎭 Emotions      : {emotions}")
    print(f"💬 Top Particles : {top_particles}")
    print(f"📄 Full Script   : {txt_out}")
    print(f"📦 Training Pairs: {jsonl_out} ({len(dialogue_pairs)} pairs)")
    print("=" * 80)

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to input audio file")
    args = parser.parse_args()
    transcribe_full_file(args.input)
