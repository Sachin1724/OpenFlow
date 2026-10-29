"""Accuracy of 'Odia + English words' on real code-mixed speech (odia_mix_gold.tsv).

The words are what the Odia model wrote for 5 clips of an Odia-English business podcast, each
labelled with what mixed output should show. Run:  python -m openflow.test_odia_mix
"""
import os

from openflow.engine import model_manager
from openflow.engine.odia_mix import english

GOLD = os.path.join(os.path.dirname(__file__), "odia_mix_gold.tsv")


def _lm():
    from huggingface_hub import try_to_load_from_cache
    from openflow.engine.indic_asr import WordLM
    path = try_to_load_from_cache(model_manager._repo("odia"), "or/lm.npz")
    return WordLM(path) if isinstance(path, str) else None


def score(lm=None) -> dict:
    s = {"english": 0, "english_ok": 0, "english_wrong": 0, "odia": 0, "odia_switched": 0, "misses": [], "wrong": []}
    with open(GOLD, encoding="utf-8") as f:
        rows = [line.rstrip("\n").split("\t") for line in f if not line.startswith("#")]
    for word, want in rows:
        if want == "-":
            continue
        got = english(word, lm)
        if want == word:  # an Odia word: must stay in Odia script
            s["odia"] += 1
            if got:
                s["odia_switched"] += 1
                s["wrong"].append(f"{word}->{got}")
        else:
            s["english"] += 1
            if got == want:
                s["english_ok"] += 1
            elif got:
                s["english_wrong"] += 1
                s["wrong"].append(f"{word}->{got} (want {want})")
            else:
                s["misses"].append(f"{word} ({want})")
    return s


def test_mixed_output_accuracy():
    s = score(_lm())
    # floors at the first measured values: raise them as the converter improves, never lower them
    assert s["english_ok"] / s["english"] >= 0.70, s
    assert s["odia_switched"] == 0, s["wrong"]
    assert s["english_wrong"] <= 12, s["wrong"]


if __name__ == "__main__":
    s = score(_lm())
    print(f"English words written in English: {s['english_ok']}/{s['english']} "
          f"({100 * s['english_ok'] / s['english']:.0f}%), wrong English word: {s['english_wrong']}, "
          f"left in Odia script: {len(s['misses'])}")
    print(f"Odia words kept in Odia: {s['odia'] - s['odia_switched']}/{s['odia']}")
    print("wrong:", ", ".join(s["wrong"]))
    print("missed:", ", ".join(s["misses"]))
