"""MIRA benchmark: does the fine-tuned SmolLM2-135M writer make dictation better, and is it safe to ship?

Odia: FLEURS Odia dev clips -> IndicConformer (the app's Odia engine) -> raw / refine_odia rules / MIRA,
scored against the human transcripts (word error rate, lower is better).
English: held-out spoken-style sentences (not in data/mira_train.jsonl). The ship-blocker is MIRA
answering English dictation in Odia script, or dropping/adding content.
Run from the repo's parent:  python -m openflow.bench_mira [N_ODIA_CLIPS] [model_dir]
"""
import os
import re
import sys
import time

from openflow.bench_odia import fleurs_clips, norm, edits
from openflow.engine.local_llm import LocalLLM, MIRA_SYSTEM
from openflow.engine.odia_refine import refine_odia
from openflow.engine.transcriber import Transcriber

ODIA = re.compile("[଀-୿]")
ENGLISH = [
    "um so i was thinking we could move the standup to ten thirty tomorrow if that works for everyone",
    "please send me the quarterly report by friday uh the one with the revenue numbers",
    "hey can you check if the build is passing on the main branch i think the tests are failing",
    "so basically the customer wants a refund for the order they placed last week",
    "i'll be late to the meeting today because my train is delayed by twenty minutes",
    "the api returns a four oh four when the user id is missing from the request",
    "can we schedule a call with the design team on monday afternoon",
    "uh remind me to buy milk eggs and bread on the way home",
    "we need to update the readme with the new installation steps before the release",
    "thanks for your help yesterday the presentation went really well",
    "let's push the deadline to next wednesday so we have time for testing",
    "my laptop battery dies very fast after the latest windows update",
    "you know the new feature should support both dark mode and light mode",
    "please book two tickets to bhubaneswar for the twenty fifth of december",
    "i think we should use postgres instead of mongodb for this project",
    "the doctor said i need to take the medicine twice a day after meals",
    "could you review my pull request when you get a chance",
    "so the plan is to launch the android app in january and the ios app later",
    "write down that the server migration is scheduled for saturday night",
    "honestly the food at that restaurant was amazing we should go again",
]


def wer(refs, hyps):
    e = n = 0
    for r, h in zip(refs, hyps):
        r, h = norm(r).split(), norm(h).split()
        e, n = e + edits(r, h), n + len(r)
    return 100 * e / max(1, n)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    folder = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "models", "mira_ct2_int8")
    mira = LocalLLM(folder, threads=min(8, os.cpu_count() or 4))
    mira.refine_dictation("warm up", "smart_clean")

    # English: script leaks and content changes
    leaks, ms = 0, []
    print("English (held out)")
    for s in ENGLISH:
        start = time.perf_counter()
        out = mira.refine_dictation(s, "smart_clean")
        ms.append(1000 * (time.perf_counter() - start))
        leak = bool(ODIA.search(out))
        leaks += leak
        ratio = len(out.split()) / len(s.split())
        flag = "ODIA" if leak else ("LEN" if not 0.6 <= ratio <= 1.4 else "")
        print(f"  {flag:4} {s}\n       -> {out}")
    print(f"English: {leaks}/{len(ENGLISH)} answered in Odia script, median {sorted(ms)[len(ms) // 2]:.0f} ms\n")

    # Odia: does MIRA lower the error rate of the app's Odia engine?
    clips = list(fleurs_clips(n))
    asr = Transcriber(model_size="odia", device="cpu", compute_type="int8", language="or")
    asr.transcribe(clips[0][0])
    refs, raw = [c[1] for c in clips], [asr.transcribe(a)[0] for a, _ in clips]
    rules = [refine_odia(h) for h in raw]
    ms = []
    out = []
    for h in raw:
        start = time.perf_counter()
        out.append(mira.refine_dictation(h, "dialect_normalize_standard_odia"))
        ms.append(1000 * (time.perf_counter() - start))
    print(f"Odia, {len(clips)} FLEURS clips (WER, lower is better)")
    print(f"  raw IndicConformer   {wer(refs, raw):5.1f}%")
    print(f"  + refine_odia rules  {wer(refs, rules):5.1f}%")
    print(f"  + MIRA               {wer(refs, out):5.1f}%   median {sorted(ms)[len(ms) // 2]:.0f} ms")
    lost = sum(not ODIA.search(o) for o in out)
    print(f"  MIRA outputs without Odia script: {lost}/{len(out)}")
    for i in range(3):
        print(f"\n  ref:  {refs[i]}\n  raw:  {raw[i]}\n  mira: {out[i]}")


if __name__ == "__main__":
    main()
