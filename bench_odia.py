"""Odia accuracy benchmark: word and character error rate for each engine on real Odia speech.

Streams the first N clips of Google FLEURS Odia (dev split, CC-BY-4.0) without downloading the
whole 230 MB archive, then runs them through the same Transcriber the app uses.
Run from the repo's parent:  python -m openflow.bench_odia [N] [whisper_model]
"""
import csv
import io
import sys
import tarfile
import time
import unicodedata
import urllib.request

import soundfile  # bench only; the app never reads files

from openflow.engine import model_manager
from openflow.engine.transcriber import Transcriber

BASE = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/or_in/"


def fleurs_clips(n: int):
    with urllib.request.urlopen(BASE + "dev.tsv") as r:
        refs = {row[1]: row[3] for row in csv.reader(io.TextIOWrapper(r, encoding="utf-8"), delimiter="\t")}
    with urllib.request.urlopen(BASE + "audio/dev.tar.gz") as r, tarfile.open(fileobj=r, mode="r|gz") as tar:
        for m in tar:
            name = m.name.rsplit("/", 1)[-1]
            if not m.isfile() or name not in refs:
                continue
            audio, sr = soundfile.read(io.BytesIO(tar.extractfile(m).read()), dtype="float32")  # FLEURS is float WAV
            assert sr == 16000, sr
            yield audio, refs[name]
            n -= 1
            if n == 0:
                return


def norm(s: str) -> str:
    # strip punctuation/symbols by Unicode category: `\w` would also drop Odia vowel signs (ି, ା)
    return " ".join("".join(" " if unicodedata.category(c)[0] in "PS" else c for c in s.lower()).split())


def edits(a, b) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    whisper = sys.argv[2] if len(sys.argv) > 2 else next(
        (m for m in model_manager.list_downloaded_models() if m not in ("odia", "parakeet")), "base")
    clips = list(fleurs_clips(n))
    print(f"{len(clips)} FLEURS Odia clips, {sum(len(a) for a, _ in clips) / 16000:.0f} s of audio\n")
    for model in ("odia", whisper):
        t = Transcriber(model_size=model, device="cpu", compute_type="int8", language="or")
        t.transcribe(clips[0][0])  # warm-up
        we = wn = ce = cn = 0
        took = 0.0
        for audio, ref in clips:
            start = time.perf_counter()
            hyp = t.transcribe(audio)[0]
            took += time.perf_counter() - start
            r, h = norm(ref), norm(hyp)
            we, wn = we + edits(r.split(), h.split()), wn + len(r.split())
            ce, cn = ce + edits(r.replace(" ", ""), h.replace(" ", "")), cn + len(r.replace(" ", ""))
        print(f"{t._current_loaded_name:>10}: WER {100 * we / wn:5.1f}%  CER {100 * ce / cn:5.1f}%  "
              f"avg {1000 * took / len(clips):.0f} ms/clip")
        print(f"{'':>10}  ref: {clips[0][1]}\n{'':>10}  hyp: {t.transcribe(clips[0][0])[0]}\n")


if __name__ == "__main__":
    assert edits("kitten", "sitting") == 3 and norm("ଭଲ, ଅଛି!") == "ଭଲ ଅଛି"
    main()
