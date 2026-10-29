"""Builds the Odia word LM that the IndicConformer beam search uses (engine/indic_asr.py: WordLM).

Text: AI4Bharat IndicCorpV2 Odia (data/or.txt). Any line sharing a 6-word run with a FLEURS Odia
dev or test sentence is dropped, so the benchmark sentences never leak into the LM.
Run from the repo's parent:  python -m openflow.build_odia_lm <or.txt> <fleurs dev.tsv> <fleurs test.tsv> <out.npz>
"""
import csv
import sys
import unicodedata
from collections import Counter

import numpy as np

MIN_UNI, MIN_BI, MAX_VOCAB = 3, 4, 400_000
CHUNK = 2_000_000  # words per bigram counting chunk


def odia_words(line: str) -> list:
    """The words the ASR can output: Odia letters and signs only, NFC, no punctuation or digits."""
    line = unicodedata.normalize("NFC", line)
    return "".join(c if 0x0B01 <= ord(c) <= 0x0B65 or 0x0B70 <= ord(c) <= 0x0B77 else " " for c in line).split()


def grams(words, n=6):
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def main(corpus, dev, test, out):
    held = set()
    for path in (dev, test):
        with open(path, encoding="utf-8") as f:
            for row in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE):
                held |= grams(odia_words(row[3]))
    print(f"{len(held)} held-out 6-grams from FLEURS dev+test")

    def lines():
        dropped = 0
        with open(corpus, encoding="utf-8", errors="ignore") as f:
            for line in f:
                w = odia_words(line)
                if len(w) < 2:
                    continue
                if grams(w) & held:
                    dropped += 1
                    continue
                yield w
        print(f"dropped {dropped} lines that overlap FLEURS")

    uni = Counter()
    for w in lines():
        uni.update(w)
    vocab = [w for w, c in uni.most_common(MAX_VOCAB) if c >= MIN_UNI]
    ids = {w: i for i, w in enumerate(vocab)}
    total = sum(uni[w] for w in vocab)
    print(f"{sum(uni.values())} words, {len(uni)} distinct, vocab {len(vocab)}")

    keys, counts, buf = np.empty(0, np.int64), np.empty(0, np.int64), []

    def flush():
        nonlocal keys, counts
        k, c = np.unique(np.array(buf, np.int64), return_counts=True)
        keys, inv = np.unique(np.concatenate([keys, k]), return_inverse=True)
        counts = np.bincount(inv, weights=np.concatenate([counts, c])).astype(np.int64)
        buf.clear()

    for w in lines():
        seq = [ids.get(x, -1) for x in w]
        buf.extend((a << 22) | b for a, b in zip(seq, seq[1:]) if a >= 0 and b >= 0)
        if len(buf) > CHUNK:
            flush()
    flush()
    keep = counts >= MIN_BI
    keys, counts = keys[keep], counts[keep]
    first = np.array([uni[w] for w in vocab], np.float64)
    bi = np.log(counts / first[keys >> 22])
    uni_lp = np.log(first / total)
    unk = float(np.log(MIN_UNI / total)) - 2.0  # rarer than anything kept
    np.savez_compressed(out, words="\n".join(vocab), uni=uni_lp.astype(np.float16), bi_keys=keys,
                        bi=bi.astype(np.float16), unk=unk)
    print(f"{len(keys)} bigrams -> {out}")


if __name__ == "__main__":
    assert odia_words("ଭଲ, କାମ। abc ୨୦") == ["ଭଲ", "କାମ"]
    main(*sys.argv[1:5])
