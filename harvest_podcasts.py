"""
harvest_podcasts.py — Download, extract, and align real-world podcasts for Odia, Hindi, and English
==================================================================================================
Extracts high-quality conversational speech samples and subtitles from YouTube to build:
1. Ground-truth evaluation benchmarks (measuring exact Word Error Rate).
2. Spoken-to-written training datasets for fine-tuning our offline micro-writer.
"""

import os
import re
import json
import subprocess
import wave
import numpy as np

PODCAST_SOURCES = [
    {
        "id": "s07oNhx0O5o",
        "lang": "odia",
        "title": "Antara Chakraborty Odia Podcast",
        "url": "https://youtu.be/s07oNhx0O5o",
        "audio_format": "139",
    },
    {
        "id": "TjPPIf-M6KE_en",
        "lang": "en",
        "title": "Sam Altman & Raj Shamani (English)",
        "url": "https://www.youtube.com/watch?v=TjPPIf-M6KE",
        "audio_format": "139-1",
    },
    {
        "id": "TjPPIf-M6KE_hi",
        "lang": "hi",
        "title": "Sam Altman & Raj Shamani (Hindi Dubbed)",
        "url": "https://www.youtube.com/watch?v=TjPPIf-M6KE",
        "audio_format": "139-0",
    }
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "podcasts")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def download_audio_track(url: str, format_id: str, out_path: str):
    """Downloads audio track via yt-dlp."""
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        print(f"[Harvest] Audio already cached: {out_path}")
        return True
    
    print(f"[Harvest] Downloading {url} (format {format_id}) -> {out_path}...")
    cmd = [
        "yt-dlp", "-y",
        "-f", format_id,
        "-o", out_path,
        "--no-write-subs", "--no-write-auto-subs",
        url
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return os.path.exists(out_path) and os.path.getsize(out_path) > 1000


def extract_wav_clip(m4a_path: str, start_sec: float, dur_sec: float, out_wav: str):
    """Extracts 16kHz mono 16-bit PCM WAV clip."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start_sec),
        "-i", m4a_path,
        "-t", str(dur_sec),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        out_wav
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_wav


def main():
    ensure_dir(DATA_DIR)
    clips_manifest = []

    print("=" * 80)
    print("OPENFLOW PODCAST HARVESTING & BENCHMARK PIPELINE")
    print(f"Target Directory: {DATA_DIR}")
    print("=" * 80)

    # 1. Check existing downloaded tracks in scratch
    scratch_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratch")
    odia_m4a = os.path.join(scratch_dir, "odia_podcast.m4a")
    en_m4a = os.path.join(scratch_dir, "podcast_full.m4a")
    hi_m4a = os.path.join(scratch_dir, "podcast_hi.m4a")

    # 2. Extract multiple real-world evaluation clips (30s each)
    samples = [
        {"name": "odia_clip_1", "src": odia_m4a, "start": 120, "dur": 30, "lang": "odia"},
        {"name": "odia_clip_2", "src": odia_m4a, "start": 300, "dur": 30, "lang": "odia"},
        {"name": "en_clip_1", "src": en_m4a, "start": 60, "dur": 30, "lang": "en"},
        {"name": "en_clip_2", "src": en_m4a, "start": 180, "dur": 30, "lang": "en"},
        {"name": "hi_clip_1", "src": hi_m4a, "start": 60, "dur": 30, "lang": "hi"},
        {"name": "hi_clip_2", "src": hi_m4a, "start": 180, "dur": 30, "lang": "hi"},
    ]

    for s in samples:
        if os.path.exists(s["src"]):
            out_wav = os.path.join(DATA_DIR, f"{s['name']}.wav")
            extract_wav_clip(s["src"], s["start"], s["dur"], out_wav)
            clips_manifest.append({
                "clip_name": s["name"],
                "wav_file": out_wav,
                "language": s["lang"],
                "duration_seconds": s["dur"],
                "start_offset": s["start"]
            })
            print(f"Extracted: {s['name']}.wav ({s['dur']}s, lang={s['lang']})")

    manifest_file = os.path.join(DATA_DIR, "manifest.json")
    with open(manifest_file, "w", encoding="utf-8") as f:
        json.dump(clips_manifest, f, indent=2)

    print(f"\nManifest saved to: {manifest_file} ({len(clips_manifest)} audio clips ready)")


if __name__ == "__main__":
    main()
