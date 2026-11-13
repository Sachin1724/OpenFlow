"""
merge_speakers.py - Fix diarization fragmentation in the harvested podcast set.

The online greedy diarizer in build_podcast_tts_dataset.py spawns a new cluster on
every crosstalk/laughter chunk, so one person ends up spread over many speaker IDs.
This re-embeds each finished clip and agglomerates globally per video, then tags each
merged cluster male/female by median F0 so clips can map onto the TTS speaker rows.

Writes data/podcasts/user_harvest/manifest_merged.jsonl
"""
import json
from collections import defaultdict
from pathlib import Path

import librosa
import numpy as np
import sherpa_onnx
import soundfile as sf
from sklearn.cluster import AgglomerativeClustering

OUT = Path("data/podcasts/user_harvest")
SPK_MODEL = Path.home() / ".openflow" / "models" / "speaker-eres2net.onnx"
SPEAKERS_PER_VIDEO = 4  # host + 1-2 guests; a threshold needs tuning, a count does not
F0_TOL_HZ = 25.0        # drop clips whose own pitch strays from the cluster median
FEMALE_F0_HZ = 165.0
MIN_CHARS_PER_S = 3.0   # below this the ASR almost certainly dropped words


def gender_of(f0_hz: float) -> str:
    return "female" if f0_hz >= FEMALE_F0_HZ else "male"


def usable(text: str, dur: float) -> bool:
    """Reject clips whose transcript is too sparse for the audio length."""
    return dur > 0 and len(text.strip()) / dur >= MIN_CHARS_PER_S


def median_f0(a16: np.ndarray, sr: int = 16000) -> float:
    try:
        f0 = librosa.yin(a16, fmin=60, fmax=400, sr=sr)
        voiced = f0[np.isfinite(f0) & (f0 > 60)]
        return float(np.median(voiced)) if len(voiced) else 0.0
    except Exception:
        return 0.0


def main():
    rows = [json.loads(l) for l in open(OUT / "manifest.jsonl", encoding="utf-8")]
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(SPK_MODEL), num_threads=4))

    per_video = defaultdict(list)
    for r in rows:
        audio, sr = sf.read(r["wav"], dtype="float32")
        a16 = librosa.resample(audio, orig_sr=sr, target_sr=16000)
        st = extractor.create_stream()
        st.accept_waveform(16000, a16)
        st.input_finished()
        emb = np.array(extractor.compute(st), dtype=np.float32)
        r["_emb"] = emb / (np.linalg.norm(emb) + 1e-9)
        r["_f0"] = median_f0(a16)
        per_video[Path(r["wav"]).stem.split("_spk")[0]].append(r)
    print(f"embedded {len(rows)} clips across {len(per_video)} videos")

    merged, kept = [], 0
    for vid, group in per_video.items():
        X = np.stack([r["_emb"] for r in group])
        k = min(SPEAKERS_PER_VIDEO, len(group))
        labels = AgglomerativeClustering(
            n_clusters=k, metric="cosine", linkage="average").fit_predict(X)
        for lab in set(labels):
            idx = [i for i, l in enumerate(labels) if l == lab]
            f0s = [group[i]["_f0"] for i in idx if group[i]["_f0"] > 0]
            spk_f0 = float(np.median(f0s)) if f0s else 0.0
            for i in idx:
                r = group[i]
                if not usable(r["text"], r["dur"]):
                    continue
                if spk_f0 and r["_f0"] and abs(r["_f0"] - spk_f0) > F0_TOL_HZ:
                    continue   # ponytail: pitch outlier = wrong person in this cluster
                merged.append({"wav": r["wav"], "text": r["text"], "dur": r["dur"],
                               "speaker": f"{vid}_s{lab}", "gender": gender_of(spk_f0),
                               "f0": round(spk_f0, 1)})
                kept += 1

    with open(OUT / "manifest_merged.jsonl", "w", encoding="utf-8") as f:
        for r in merged:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    agg = defaultdict(lambda: [0.0, 0, "", 0.0])
    for r in merged:
        a = agg[r["speaker"]]
        a[0] += r["dur"]; a[1] += 1; a[2] = r["gender"]; a[3] = r["f0"]
    print(f"\n{kept}/{len(rows)} clips kept, {sum(r['dur'] for r in merged)/3600:.2f} h")
    print(f"{len(agg)} merged speakers (was {len(set(r['speaker'] for r in rows))})\n")
    for s, (d, n, g, f0) in sorted(agg.items(), key=lambda x: -x[1][0])[:15]:
        print(f"  {s:22s} {d/60:6.1f} min  {n:4d} clips  {g:6s} F0={f0:5.1f}Hz")


if __name__ == "__main__":
    main()
