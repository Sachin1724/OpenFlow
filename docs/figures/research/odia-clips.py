"""Per-clip Odia results for the page's clip explorer: docs/figures/research/odia-clips.json.

Why this exists: since v1.1.8 the app always routes Odia speech to the Odia engine, so asking Transcriber for "Whisper
base on Odia" returns the Odia engine's text again. The explorer needs what Whisper itself writes for Odia speech,
so Whisper is called directly here, the way the original benchmark did (no language, the app's Odia prompt, greedy).
The OpenFlow Odia rows are taken from docs/data/ml-research.json (the real Odia engine).
Run from the repo's parent:  python -m openflow.docs.figures.research.odia-clips  or simply:  python docs/figures/research/odia-clips.py
"""
import json
import os
import sys
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.dirname(REPO))
import faster_whisper  # noqa: E402

from openflow.bench_odia import edits, norm  # noqa: E402
from openflow.engine import model_manager  # noqa: E402
from openflow.engine.transcriber import _THREADS  # noqa: E402
from openflow.research_ml import clips  # noqa: E402

PROMPT = ("Indian English, Hinglish, Hindi, and Odia speech. "
          "Accurately transcribe Hindi and Odia phrases in clean Latin/Roman script or Devanagari. "
          "Common terms: kya, kyu, kaise, kuch, nahi, haan, theek, accha, bhai, yaar, kete, kan, kemiti, kichi, ghare, aama, bhala. "
          "Never output Urdu or Arabic script.")
OUT = os.path.join(REPO, "docs", "figures", "research", "odia-clips.json")


def whisper_rows(name, data):
    model = faster_whisper.WhisperModel(model_manager.cached_path(name), device="cpu", compute_type="int8", cpu_threads=_THREADS)
    out = []
    for audio, _ in data:
        segs, _info = model.transcribe(audio, beam_size=1, best_of=1, temperature=0.0, language=None, task="transcribe",
                                       vad_filter=True, vad_parameters=dict(min_silence_duration_ms=300),
                                       condition_on_previous_text=False, without_timestamps=True, initial_prompt=PROMPT)
        out.append(" ".join(s.text.strip() for s in segs).strip())
    return out


def main():
    ml = json.load(open(os.path.join(REPO, "docs", "data", "ml-research.json"), encoding="utf-8"))
    ours = {c["ref"]: c["engines"]["OpenFlow Odia"] for c in ml["odia_clips"]}
    data = clips("or_in", len(ml["odia_clips"]))
    assert [r for _, r in data] == [c["ref"] for c in ml["odia_clips"]], "clip order differs from ml-research.json"
    rows = [{"ref": ref, "engines": {}, "wer": {}} for _, ref in data]
    for label, name in (("Whisper base", "base"), ("Whisper small", "small")):
        t = time.time()
        for row, hyp in zip(rows, whisper_rows(name, data)):
            row["engines"][label] = hyp
        print(label, f"{time.time() - t:.0f}s", flush=True)
    for row in rows:
        row["engines"]["OpenFlow Odia"] = ours[row["ref"]]
        for label, hyp in row["engines"].items():
            r, h = norm(row["ref"]), norm(hyp)
            row["wer"][label] = round(100 * edits(r.split(), h.split()) / max(1, len(r.split())), 1)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    for label in rows[0]["engines"]:
        w = sorted(r["wer"][label] for r in rows)
        print(f"{label}: median word error {w[len(w) // 2]}% over {len(rows)} clips")


if __name__ == "__main__":
    main()
