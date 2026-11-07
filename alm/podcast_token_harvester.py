"""
podcast_token_harvester.py — Converts Harvested Odia Podcasts into Discrete Audio Codec Tokens
=============================================================================================
Encodes real-world conversational audio slices into discrete RVQ token files (.pt / .npy)
for training and in-context zero-shot voice prompting.
"""

import os
import sys
import json
import torch
import torchaudio
from pathlib import Path
from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alm.audio_tokenizer import AudioTokenizer

TOKEN_CACHE_DIR = SCRIPT_DIR / "tokens"
TOKEN_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def harvest_podcast_tokens():
    """
    Harvests discrete audio tokens from all local podcast audio slices.
    """
    tokenizer = AudioTokenizer()
    print("=" * 80)
    print("🎙️ HARVESTING DISCRETE AUDIO TOKENS FROM NATIVE ODIA PODCASTS")
    print("=" * 80)

    # Key podcast slices available in repository
    source_dir = REPO_ROOT / "scratch"
    wav_files = list(source_dir.glob("*.wav"))
    
    # Filter for real native voice slices
    target_files = [
        f for f in wav_files if any(k in f.name for k in [
            "smita", "kishore", "gulua", "sambalpuri", "podcast", "natural_clean"
        ])
    ]

    print(f"Found {len(target_files)} target conversational audio slices.")
    manifest = []

    for wav_path in target_files:
        try:
            info = torchaudio.info(str(wav_path))
            dur = info.num_frames / info.sample_rate
            if dur < 1.0:
                continue

            # Tokenize into discrete codebook tokens
            codes = tokenizer.encode_file(str(wav_path)) # [1, 8, T]
            stem = wav_path.stem
            out_token_path = TOKEN_CACHE_DIR / f"{stem}_tokens.pt"
            
            torch.save({
                "stem": stem,
                "duration_s": dur,
                "codes": codes.cpu(), # [1, 8, T]
                "num_frames": codes.shape[-1],
                "sample_rate": tokenizer.sample_rate
            }, out_token_path)

            manifest.append({
                "stem": stem,
                "wav_path": str(wav_path),
                "token_path": str(out_token_path),
                "duration_s": round(dur, 2),
                "num_frames": codes.shape[-1]
            })
            print(f"  ✓ Tokenized: {stem:35s} | {dur:5.2f}s -> {codes.shape[-1]} frames ({codes.shape[1]} codebooks)")

        except Exception as e:
            print(f"  ✗ Failed {wav_path.name}: {e}")

    # Write manifest
    manifest_path = TOKEN_CACHE_DIR / "podcast_tokens_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n" + "=" * 80)
    print(f"✅ Tokenization Complete! Manifest saved to: {manifest_path}")
    print(f"Total harvest: {len(manifest)} files, {sum(m['duration_s'] for m in manifest):.1f}s of discrete audio tokens.")
    print("=" * 80)
    return manifest

if __name__ == '__main__':
    harvest_podcast_tokens()

