"""Odia research benchmark behind the landing page's "Research" section.

On the first N clips of Google FLEURS Odia (dev split, CC-BY-4.0) it measures, per engine:
  understanding  word / character error rate against the Odia transcript
  writing        share of output letters that are Odia script (U+0B00-0B7F)
  speed          real-time factor (processing time / audio length) on this PC's CPU
  translation    chrF and BLEU of the English output against FLEURS's English sentence
Writes docs/data/odia-research.json. Run from the repo's parent:  python -m openflow.research_odia [N]
"""
import csv
import io
import json
import os
import platform
import sys
import time
import urllib.request

import sacrebleu  # research only; the app never imports it

from openflow.bench_odia import BASE, edits, fleurs_clips, norm
from openflow.engine import model_manager, translator
from openflow.engine.transcriber import Transcriber

OUT = os.path.join(os.path.dirname(__file__), "docs", "data", "odia-research.json")


def odia_share(text: str) -> float:
    letters = [c for c in text if c.isalpha() or 0x0B00 <= ord(c) <= 0x0B7F]
    return sum(0x0B00 <= ord(c) <= 0x0B7F for c in letters) / len(letters) if letters else 0.0


def tsv(split_lang: str):
    with urllib.request.urlopen(BASE.replace("or_in", split_lang) + "dev.tsv") as r:
        return list(csv.reader(io.TextIOWrapper(r, encoding="utf-8"), delimiter="\t"))


def run(name, model, lang, clips):
    t = Transcriber(model_size=model, device="cpu", compute_type="int8", language=lang)
    t.transcribe(clips[0][0])  # warm-up
    rows = []
    for audio, ref in clips:
        start = time.perf_counter()
        hyp = t.transcribe(audio)[0]
        rows.append({"hyp": hyp, "secs": time.perf_counter() - start, "dur": len(audio) / 16000})
    print(f"  {name}: done")
    return rows


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    english = {row[0]: row[2] for row in tsv("en_us")}
    odia_rows = {row[3]: row[0] for row in tsv("or_in")}
    clips = list(fleurs_clips(n))
    refs_en = [english.get(odia_rows.get(ref), "") for _, ref in clips]
    print(f"{len(clips)} clips, {sum(len(a) for a, _ in clips) / 16000:.0f} s of audio")

    asr = {"Whisper base": run("Whisper base", "base", "or", clips),
           "Whisper small": run("Whisper small", "small", "or", clips),
           "OpenFlow Odia": run("OpenFlow Odia", "odia", "or", clips)}
    result = {"clips": len(clips), "audio_seconds": round(sum(len(a) for a, _ in clips) / 16000, 1),
              "cpu": platform.processor(), "asr": {}, "translation": {}}
    for name, rows in asr.items():
        per_wer, we = [], [0, 0, 0, 0]
        for (_, ref), row in zip(clips, rows):
            r, h = norm(ref), norm(row["hyp"])
            w, c = edits(r.split(), h.split()), edits(r.replace(" ", ""), h.replace(" ", ""))
            we = [we[0] + w, we[1] + len(r.split()), we[2] + c, we[3] + len(r.replace(" ", ""))]
            per_wer.append(round(100 * w / max(1, len(r.split())), 1))
        result["asr"][name] = {
            "wer": round(100 * we[0] / we[1], 1), "cer": round(100 * we[2] / we[3], 1),
            "odia_script": round(100 * sum(odia_share(x["hyp"]) for x in rows) / len(rows), 1),
            "rtf": round(sum(x["secs"] for x in rows) / sum(x["dur"] for x in rows), 3),
            "ms_per_clip": round(1000 * sum(x["secs"] for x in rows) / len(rows)),
            "per_clip_wer": per_wer, "example": rows[0]["hyp"],
        }

    def score(name, hyps):
        result["translation"][name] = {
            "chrf": round(sacrebleu.corpus_chrf(hyps, [refs_en]).score, 1),
            "bleu": round(sacrebleu.corpus_bleu(hyps, [refs_en]).score, 1), "example": hyps[0]}
        print(f"  {name}: chrF {result['translation'][name]['chrf']}")

    for name, model in (("Whisper base translate", "base"), ("Whisper small translate", "small")):
        score(name, [x["hyp"] for x in run(name, model, "translate", clips)])
    it2 = translator.OdiaToEnglish(os.path.join(model_manager.cached_path("odia-en"), model_manager.TRANSLATOR_DIR),
                                   threads=min(8, os.cpu_count() or 4))
    score("OpenFlow Odia + IndicTrans2", [it2.translate(x["hyp"]) for x in asr["OpenFlow Odia"]])
    score("IndicTrans2 on the true transcript", [it2.translate(ref) for _, ref in clips])  # ceiling with perfect ASR

    result["example_ref"] = {"odia": clips[0][1], "english": refs_en[0]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: {m: {x: y for x, y in v.items() if x not in ("per_clip_wer", "example")}
                          for m, v in result[k].items()} for k in ("asr", "translation")}, indent=1))


if __name__ == "__main__":
    assert odia_share("ଭଲ abc") == 0.4 and odia_share("123") == 0.0
    main()
