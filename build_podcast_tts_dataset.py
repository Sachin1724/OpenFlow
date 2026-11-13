"""
build_podcast_tts_dataset.py - Turn Odia YouTube podcasts into a TTS fine-tuning set.

Pipeline: yt-dlp -> 24kHz wav -> ERes2Net diarization -> IndicCTC transcript
          -> per-speaker turn clips + manifest.jsonl

Reuses engine.indic_asr, engine.dialect_normalizer and the centroid diarizer from
scratch/test_speaker_diarization.py. Run:  python build_podcast_tts_dataset.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import scipy.signal as ss
import sherpa_onnx
from huggingface_hub import snapshot_download

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.indic_asr import IndicCTC
from engine.dialect_normalizer import get_dialect_normalizer

URLS = [
    "https://youtu.be/2VFkxUSSOBU",   # multi-speaker Odia podcast
    "https://youtu.be/pmIgLz7oWyE",   # two male + one female
    "https://youtu.be/Y3t3HzpFcNE",
    "https://youtu.be/m3OoKUH2OzM",
    "https://youtu.be/lGI2Pkl5Sso",
]

OUT = Path("data/podcasts/user_harvest")
CLIPS = OUT / "clips"
SPK_MODEL = Path.home() / ".openflow" / "models" / "speaker-eres2net.onnx"
CHUNK_S = 5.0          # diarization granularity
MIN_TURN_S, MAX_TURN_S = 2.0, 15.0
SAME_SPEAKER_COS = 0.52


def fetch(url: str) -> Path:
    """Download bestaudio, decode to 24kHz mono wav (TTS native rate)."""
    vid = url.rsplit("/", 1)[-1].split("?")[0]
    wav = OUT / f"{vid}.wav"
    if wav.exists():
        return wav
    raw = OUT / f"{vid}.m4a"
    if not raw.exists():
        # visionos is the only client still serving audio URLs without a JS runtime;
        # 403s are rate-limiting, so retry and pace the requests.
        subprocess.run(["yt-dlp", "--extractor-args", "youtube:player_client=visionos",
                        "-f", "bestaudio", "--retries", "10", "--extractor-retries", "5",
                        "--sleep-requests", "2", "--quiet", "--no-warnings", "--progress",
                        "-o", str(raw), url], check=True)
    subprocess.run(["ffmpeg", "-i", str(raw), "-ar", "24000", "-ac", "1", str(wav), "-y"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return wav


def snap_to_silence(audio: np.ndarray, idx: int, sr: int, window_s: float = 0.4) -> int:
    """Nudge a cut point to the quietest 20ms inside +/-window_s so words aren't clipped."""
    w = int(window_s * sr)
    lo, hi = max(0, idx - w), min(len(audio), idx + w)
    if hi - lo < sr // 20:
        return idx
    step = sr // 50
    seg = audio[lo:hi]
    frames = [(np.abs(seg[i:i + step]).mean(), i) for i in range(0, len(seg) - step, step)]
    return lo + min(frames)[1] if frames else idx


def diarize(audio24: np.ndarray, asr: IndicCTC, norm, extractor):
    """Yield (speaker_id, start_sample, end_sample, text) merged turns at 24kHz."""
    sr24 = 24000
    a16 = ss.resample_poly(audio24, 2, 3).astype(np.float32)   # 24k -> 16k for ASR + embeddings
    sr16, step = 16000, int(CHUNK_S * 16000)

    centroids, chunks = [], []
    for i in range(0, len(a16) - step, step):
        sub = a16[i:i + step]
        if np.sqrt(np.mean(sub ** 2)) < 0.01:
            chunks.append((None, i))
            continue
        st = extractor.create_stream()
        st.accept_waveform(sr16, sub)
        st.input_finished()
        emb = np.array(extractor.compute(st), dtype=np.float32)
        emb /= np.linalg.norm(emb) + 1e-9
        if centroids:
            sims = [float(c @ emb) for c in centroids]
            best = int(np.argmax(sims))
            if max(sims) >= SAME_SPEAKER_COS:
                spk = best
                upd = centroids[best] * 0.8 + emb * 0.2
                centroids[best] = upd / (np.linalg.norm(upd) + 1e-9)
            else:
                centroids.append(emb)
                spk = len(centroids) - 1
        else:
            centroids.append(emb)
            spk = 0
        chunks.append((spk, i))

    # merge consecutive same-speaker chunks into turns, cut at silence, transcribe
    run_spk, run_start = None, 0
    for spk, i in chunks + [(None, len(a16))]:
        if spk == run_spk:
            continue
        if run_spk is not None:
            dur = (i - run_start) / sr16
            if MIN_TURN_S <= dur <= MAX_TURN_S:
                s24 = snap_to_silence(audio24, int(run_start / sr16 * sr24), sr24)
                e24 = snap_to_silence(audio24, int(i / sr16 * sr24), sr24)
                text = asr.text(a16[run_start:i], beam=True).strip()
                if text:
                    yield run_spk, s24, e24, norm.normalize(text)["normalized"]
        run_spk, run_start = spk, i


def main():
    CLIPS.mkdir(parents=True, exist_ok=True)
    snap = snapshot_download("sachinmallick/openflow-odia-asr-int8")
    asr = IndicCTC(os.path.join(snap, "or"), threads=4)
    norm = get_dialect_normalizer()
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(SPK_MODEL), num_threads=2))

    manifest, total_s = [], 0.0
    with open(OUT / "manifest.jsonl", "w", encoding="utf-8") as mf:
        for url in URLS:
            try:
                wav = fetch(url)
            except Exception as exc:
                print(f"[SKIP] {url}: {exc}")
                continue
            vid = wav.stem
            audio, sr = sf.read(wav, dtype="float32")
            print(f"[{vid}] {len(audio)/sr/60:.1f} min loaded, diarizing...")
            for n, (spk, s, e, text) in enumerate(diarize(audio, asr, norm, extractor)):
                clip = CLIPS / f"{vid}_spk{spk}_{n:04d}.wav"
                sf.write(clip, audio[s:e], sr)
                dur = (e - s) / sr
                total_s += dur
                row = {"wav": str(clip).replace("\\", "/"), "speaker": f"{vid}_spk{spk}",
                       "text": text, "dur": round(dur, 2)}
                mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                manifest.append(row)
            print(f"[{vid}] {len(manifest)} turns, {total_s/3600:.2f} h so far")

    spk_hours = {}
    for r in manifest:
        spk_hours[r["speaker"]] = spk_hours.get(r["speaker"], 0) + r["dur"]
    print(f"\nDONE: {len(manifest)} clips, {total_s/3600:.2f} h -> {OUT/'manifest.jsonl'}")
    for s, d in sorted(spk_hours.items(), key=lambda x: -x[1]):
        print(f"  {s:28s} {d/60:6.1f} min")


if __name__ == "__main__":
    main()
