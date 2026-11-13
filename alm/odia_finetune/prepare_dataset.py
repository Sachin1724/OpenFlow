"""prepare_dataset.py - extracts (wav, text) pairs from the or_F/or_M WebDataset shards
(sulabhkatiyar/indic-tts-mini-24k, AI4Bharat Rasa Odia voices) into a flat local manifest
that chatterbox's SpeechFineTuningDataset-style loader can consume.
"""
import io
import json
import sys
import tarfile
from pathlib import Path

import pandas as pd
import soundfile as sf
from huggingface_hub import hf_hub_download

OUT_DIR = Path(__file__).resolve().parent / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)
WAV_DIR = OUT_DIR / "wavs"
WAV_DIR.mkdir(parents=True, exist_ok=True)

VOICES = ["or_F", "or_M"]
SHARD_COUNTS = {"or_F": 3, "or_M": 3}


def load_index(voice: str) -> pd.DataFrame:
    p = hf_hub_download(repo_id="sulabhkatiyar/indic-tts-mini-24k", filename=f"index/parts/{voice}.parquet", repo_type="dataset")
    return pd.read_parquet(p)


def main():
    manifest = []
    for voice in VOICES:
        df = load_index(voice)
        # only the training split -- val/eval/test stay untouched for honest eval later
        df = df[df["split"] == "train"]
        print(f"[{voice}] {len(df)} training utterances", file=sys.stderr)

        by_shard = {}
        for _, row in df.iterrows():
            by_shard.setdefault(row["shard"], []).append(row)

        for shard_rel, rows in by_shard.items():
            tar_path = hf_hub_download(repo_id="sulabhkatiyar/indic-tts-mini-24k", filename=shard_rel, repo_type="dataset")
            by_offset = {r["member_offset"]: r for r in rows}
            with tarfile.open(tar_path, "r") as tf:
                for member in tf.getmembers():
                    if member.offset_data not in by_offset:
                        continue
                    row = by_offset[member.offset_data]
                    fobj = tf.extractfile(member)
                    if fobj is None:
                        continue
                    data = fobj.read()
                    wav, sr = sf.read(io.BytesIO(data), dtype="float32")
                    out_wav = WAV_DIR / f"{voice}_{row['id']}.wav"
                    sf.write(str(out_wav), wav, sr)
                    manifest.append({"audio": str(out_wav), "text": row["text"], "voice": voice})
            print(f"[{voice}] extracted shard {shard_rel}: {len(manifest)} total so far", file=sys.stderr)

    manifest_path = OUT_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    print(f"Saved {len(manifest)} utterances to {manifest_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
