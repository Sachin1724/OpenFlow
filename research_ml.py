"""Broader ML research behind docs/research.html. Writes docs/data/ml-research.json.

Everything is measured on this PC's CPU (int8), one model per fresh process so memory figures are honest:
  english / hindi   word + character error rate, speed and memory per engine on Google FLEURS dev clips (CC-BY-4.0)
  silence           how often an engine invents text from recordings that contain no speech, with and without
                    the silence guard (synthetic non-speech: silence, hiss, hum, clicks)
  odia_clips        what each Odia engine heard, clip by clip, against the true transcript
Run from the repo's parent:  python -m openflow.research_ml [clips_per_language]
"""
import csv
import io
import json
import multiprocessing as mp
import os
import platform
import sys
import tarfile
import time
import urllib.request

import numpy as np
import psutil
import soundfile

from openflow.bench_odia import edits, norm

OUT = os.path.join(os.path.dirname(__file__), "docs", "data", "ml-research.json")
FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/{}/"
PROMPT = "Indian English and Hinglish dictation in natural Latin/Roman script. Use standard punctuation."  # the app's own


def clips(lang: str, n: int):
    """First n FLEURS dev clips of a language: (float32 audio at 16 kHz, reference transcript)."""
    base = FLEURS.format(lang)
    with urllib.request.urlopen(base + "dev.tsv") as r:
        refs = {row[1]: row[3] for row in csv.reader(io.TextIOWrapper(r, encoding="utf-8"), delimiter="\t")}
    out = []
    with urllib.request.urlopen(base + "audio/dev.tar.gz") as r, tarfile.open(fileobj=r, mode="r|gz") as tar:
        for m in tar:
            name = m.name.rsplit("/", 1)[-1]
            if m.isfile() and name in refs:
                audio, sr = soundfile.read(io.BytesIO(tar.extractfile(m).read()), dtype="float32")
                assert sr == 16000, sr
                out.append((audio, refs[name]))
                if len(out) == n:
                    break
    return out


def silence_set():
    """60 five-second recordings with no speech in them."""
    rng = np.random.default_rng(7)
    n, sets = 16000 * 5, []
    t = np.arange(n) / 16000
    for i in range(10):
        sets.append(("silence", np.zeros(n, np.float32)))
    for db in (-60, -50, -40, -30):  # room hiss, quiet to loud
        for _ in range(5):
            sets.append((f"hiss {db} dB", (rng.standard_normal(n) * 10 ** (db / 20)).astype(np.float32)))
    for _ in range(10):  # low rumble (air-con, traffic): brown noise
        b = np.cumsum(rng.standard_normal(n)); b = (b - b.mean()) / np.abs(b).max() * 0.02
        sets.append(("rumble", b.astype(np.float32)))
    for _ in range(10):  # mains hum with a little hiss
        sets.append(("hum", (0.02 * np.sin(2 * np.pi * 50 * t) + rng.standard_normal(n) * 0.002).astype(np.float32)))
    for _ in range(10):  # keyboard-like clicks
        a = np.zeros(n, np.float32)
        for at in rng.integers(0, n - 800, 12):
            a[at:at + 800] += (rng.standard_normal(800) * np.exp(-np.arange(800) / 90) * 0.3).astype(np.float32)
        sets.append(("clicks", a))
    return sets


def job(spec):
    """One model in a fresh process: returns its measurements."""
    from openflow.engine.transcriber import Transcriber
    kind, model, lang = spec["kind"], spec["model"], spec["lang"]
    t = Transcriber(model_size=model, device="cpu", compute_type="int8", language=lang)
    if kind == "silence":
        t._load_model()
        data = spec["audio"]
        rows = {"before": [], "after": []}
        for label, audio in data:
            s = time.perf_counter()
            segs, _ = t.model.transcribe(audio, beam_size=1, best_of=1, temperature=0.0, language=None, task="transcribe",
                                         vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300),
                                         condition_on_previous_text=False, without_timestamps=True, initial_prompt=PROMPT)
            text = " ".join(x.text.strip() for x in segs).strip()
            rows["before"].append((label, text, time.perf_counter() - s))
            s = time.perf_counter()
            text = t.transcribe(audio, None, PROMPT)[0]
            rows["after"].append((label, text, time.perf_counter() - s))
        return {"loaded": t._current_loaded_name, "rows": rows}
    audio_clips = spec["clips"]
    t.transcribe(audio_clips[0][0])  # warm-up
    rows = []
    for audio, ref in audio_clips:
        s = time.perf_counter()
        hyp = t.transcribe(audio)[0]
        rows.append({"hyp": hyp, "secs": time.perf_counter() - s, "dur": len(audio) / 16000})
    return {"loaded": t._current_loaded_name, "rows": rows, "rss_mb": round(psutil.Process().memory_info().rss / 2 ** 20)}


def run(spec):
    with mp.get_context("spawn").Pool(1, maxtasksperchild=1) as pool:
        return pool.apply(job, (spec,))


def score(name, label, data, out):
    per, we = [], [0, 0, 0, 0]
    for (_, ref), row in zip(data["clips"], out["rows"]):
        r, h = norm(ref), norm(row["hyp"])
        w, c = edits(r.split(), h.split()), edits(r.replace(" ", ""), h.replace(" ", ""))
        we = [we[0] + w, we[1] + len(r.split()), we[2] + c, we[3] + len(r.replace(" ", ""))]
        per.append(round(100 * w / max(1, len(r.split())), 1))
    rows = out["rows"]
    return {"label": label, "loaded": out["loaded"], "wer": round(100 * we[0] / we[1], 1), "cer": round(100 * we[2] / we[3], 1),
            "rtf": round(sum(x["secs"] for x in rows) / sum(x["dur"] for x in rows), 3),
            "ms_per_clip": round(1000 * sum(x["secs"] for x in rows) / len(rows)), "rss_mb": out["rss_mb"], "per_clip_wer": per}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    result = {"meta": {"cpu": platform.processor(), "cores": psutil.cpu_count(logical=False), "threads": psutil.cpu_count(),
                       "ram_gb": round(psutil.virtual_memory().total / 2 ** 30), "precision": "int8, CPU only",
                       "date": time.strftime("%Y-%m-%d"), "dataset": "Google FLEURS dev split (CC-BY-4.0)"}}
    for key, lang, code, engines in (
            ("english", "en_us", "en", (("Whisper tiny", "tiny"), ("Whisper base", "base"), ("Whisper small", "small"), ("Parakeet", "parakeet"))),
            ("hindi", "hi_in", "hi", (("Whisper base", "base"), ("Whisper small", "small")))):
        data = {"clips": clips(lang, n)}
        result[key] = {"clips": len(data["clips"]), "audio_seconds": round(sum(len(a) for a, _ in data["clips"]) / 16000, 1), "engines": {}}
        for label, model in engines:
            print(f"{key}: {label}", flush=True)
            out = run({"kind": "asr", "model": model, "lang": code, "clips": data["clips"]})
            result[key]["engines"][label] = score(label, label, data, out)
            print("  ", {k: v for k, v in result[key]["engines"][label].items() if k != "per_clip_wer"}, flush=True)

    print("silence test", flush=True)
    sil = silence_set()
    out = run({"kind": "silence", "model": "small", "lang": "auto", "audio": sil})
    summary = {"recordings": len(sil), "model": out["loaded"], "kinds": sorted({k for k, _ in sil})}
    for phase in ("before", "after"):
        rows = out["rows"][phase]
        texts = [(k, x) for k, x, _ in rows if x.strip()]
        summary[phase] = {"with_text": len(texts), "seconds": round(sum(s for _, _, s in rows), 1),
                          "examples": sorted({x for _, x in texts})[:6],
                          "by_kind": {k: sum(1 for kk, x in texts if kk == k) for k in summary["kinds"]}}
    result["silence"] = summary
    print("  ", {k: (v if k not in ("kinds",) else "…") for k, v in summary.items()}, flush=True)

    print("odia clips", flush=True)
    odia = clips("or_in", 30)
    per_clip = [{"ref": ref, "engines": {}, "wer": {}} for _, ref in odia]
    for label, model in (("Whisper base", "base"), ("Whisper small", "small"), ("OpenFlow Odia", "odia")):
        out = run({"kind": "asr", "model": model, "lang": "or", "clips": odia})
        for pc, (_, ref), row in zip(per_clip, odia, out["rows"]):
            r, h = norm(ref), norm(row["hyp"])
            pc["engines"][label] = row["hyp"]
            pc["wer"][label] = round(100 * edits(r.split(), h.split()) / max(1, len(r.split())), 1)
        print("  ", label, flush=True)
    result["odia_clips"] = per_clip

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("saved", OUT)


if __name__ == "__main__":
    main()
