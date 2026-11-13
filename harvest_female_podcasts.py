"""
harvest_female_podcasts.py - Extract clean female conversational speech turns
from YouTube Odia podcasts, separating male host/interviewers.

Videos:
1. JOHE54OedMM (Podcast With Elina Samantray)
2. rCO7_fGfsSE (Podcast With Sameera)
3. rlRdJGCAjNM (Odia Festivals)
"""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import scipy.signal as ss
import soundfile as sf
import librosa
from huggingface_hub import snapshot_download

# Ensure openflow imports work
sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.indic_asr import IndicCTC
from engine.dialect_normalizer import get_dialect_normalizer

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data" / "podcasts" / "female_harvest"
CLIPS_DIR = DATA_DIR / "clips"
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

FEMALE_MIN_F0 = 175.0   # Female vocal folds typically vibrate > 175 Hz (male host is ~110-155 Hz)
MIN_DUR = 2.0
MAX_DUR = 12.0
MIN_CHARS_PER_S = 2.5

VIDEOS = [
    DATA_DIR / "vk_9y8bmRGI.wav",
    DATA_DIR / "Bi8bbkPbvLU.wav",
]


def find_speech_turns(audio: np.ndarray, sr: int = 24000,
                      min_dur: float = 2.0, max_dur: float = 12.0,
                      sil_thresh: float = 0.015, min_sil_dur: float = 0.35):
    """Segment continuous podcast audio into clean candidate speech turns based on silence."""
    hop = int(sr * 0.02)         # 20ms frame hop
    frame_len = int(sr * 0.04)   # 40ms frame length
    n_frames = (len(audio) - frame_len) // hop

    chunk_frames = 10000
    energies = []
    for i in range(0, n_frames, chunk_frames):
        end = min(n_frames, i + chunk_frames)
        idx = np.arange(i, end)[:, None] * hop + np.arange(frame_len)[None, :]
        frames = audio[idx]
        rms = np.sqrt(np.mean(frames**2, axis=1))
        energies.append(rms)
    energies = np.concatenate(energies)
    is_speech = energies > sil_thresh

    min_sil_frames = int(min_sil_dur * sr / hop)
    min_speech_frames = int(min_dur * sr / hop)
    max_speech_frames = int(max_dur * sr / hop)

    turns = []
    in_speech = False
    start_frame = 0
    sil_count = 0

    for f, active in enumerate(is_speech):
        if active:
            if not in_speech:
                in_speech = True
                start_frame = f
            sil_count = 0
        else:
            if in_speech:
                sil_count += 1
                if sil_count >= min_sil_frames or (f - start_frame) >= max_speech_frames:
                    end_frame = f - sil_count
                    dur_frames = end_frame - start_frame
                    if dur_frames >= min_speech_frames:
                        s_idx = start_frame * hop
                        e_idx = min(len(audio), end_frame * hop + frame_len)
                        turns.append((s_idx, e_idx))
                    in_speech = False
                    sil_count = 0
    return turns


def get_f0(sub16: np.ndarray, sr: int = 16000) -> float:
    """Extract median fundamental frequency using librosa YIN."""
    try:
        f0 = librosa.yin(sub16, fmin=70, fmax=380, sr=sr)
        voiced = f0[np.isfinite(f0) & (f0 > 70)]
        return float(np.median(voiced)) if len(voiced) > 10 else 0.0
    except Exception:
        return 0.0


def main():
    print("=== MIRA Female Podcast Harvester & Diarizer ===")
    print("Initializing IndicCTC ASR and Dialect Normalizer...")
    snap = snapshot_download("sachinmallick/openflow-odia-asr-int8")
    asr = IndicCTC(os.path.join(snap, "or"), threads=4)
    norm = get_dialect_normalizer()

    out_manifest = DATA_DIR / "manifest_female_batch2.jsonl"
    combined_manifest = DATA_DIR / "manifest_female_combined.jsonl"
    all_female_rows = []
    total_fem_dur = 0.0
    total_male_dropped = 0

    for vid_path in VIDEOS:
        if not vid_path.exists():
            print(f"[WARN] File not found: {vid_path}")
            continue

        vid_name = vid_path.stem
        print(f"\n--- Processing {vid_name} ---")
        t0 = time.time()
        audio, sr = sf.read(str(vid_path), dtype="float32")
        print(f"Loaded {len(audio)/sr/60:.2f} min ({len(audio)/sr:.1f}s) in {time.time()-t0:.2f}s")

        turns = find_speech_turns(audio, sr, min_dur=MIN_DUR, max_dur=MAX_DUR)
        print(f"Detected {len(turns)} candidate turns. Diarizing & filtering female turns (F0 >= {FEMALE_MIN_F0} Hz)...")

        fem_count = 0
        male_count = 0

        for idx, (s, e) in enumerate(turns):
            sub = audio[s:e]
            dur = (e - s) / sr
            sub16 = ss.resample_poly(sub, 2, 3).astype("float32")

            f0 = get_f0(sub16, sr=16000)
            if f0 < FEMALE_MIN_F0:
                # Discard male interviewer/host speech
                male_count += 1
                continue

            # Transcribe female speech
            raw_text = asr.text(sub16, beam=True).strip()
            if not raw_text:
                continue

            clean_text = norm.normalize(raw_text)["normalized"]
            if len(clean_text) / dur < MIN_CHARS_PER_S:
                continue

            clip_filename = f"{vid_name}_fem_{fem_count:04d}.wav"
            clip_path = CLIPS_DIR / clip_filename
            sf.write(str(clip_path), sub, sr)

            row = {
                "wav": str(clip_path).replace("\\", "/"),
                "speaker": f"{vid_name}_female",
                "text": clean_text,
                "dur": round(dur, 2),
                "f0": round(f0, 1),
                "gender": "female",
            }
            all_female_rows.append(row)
            total_fem_dur += dur
            fem_count += 1

            if fem_count % 25 == 0:
                print(f"  [{vid_name}] Kept {fem_count} female turns ({fem_count*dur/60:.1f}m) | Discarded {male_count} male turns")

        total_male_dropped += male_count
        print(f"Finished {vid_name}: Kept {fem_count} pure female turns, filtered out {male_count} male turns.")

    with open(out_manifest, "w", encoding="utf-8") as f:
        for r in all_female_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Append to combined manifest
    with open(combined_manifest, "a", encoding="utf-8") as f:
        for r in all_female_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n==========================================")
    print(f"HARVEST COMPLETE:")
    print(f"Total pure female turns harvested: {len(all_female_rows)}")
    print(f"Total female speech duration: {total_fem_dur/3600:.2f} hours ({total_fem_dur/60:.1f} minutes)")
    print(f"Total male turns filtered out: {total_male_dropped}")
    print(f"Manifest written to: {out_manifest}")
    print(f"==========================================")


if __name__ == "__main__":
    main()

