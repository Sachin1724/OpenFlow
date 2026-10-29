"""Builds engine/odia_english.tsv.gz, the Odia-spelling -> English table engine/odia_mix.py uses.

Pronunciations: CMUdict (cmudict.dict). Frequencies: Norvig's count_1w.txt (Google Web 1T unigrams).
Each of the 25k most frequent English words with a pronunciation is spelled in Odia script the ways
Odia writers do (a schwa may be written or not, "z" as ଜ or ସ, ...); a spelling shared by several
words goes to the most frequent one.
Run from the repo's parent:  python -m openflow.build_odia_english <cmudict.dict> <count_1w.txt>
"""
import gzip
import itertools
import math
import re
import sys

from openflow.engine.odia_mix import TABLE_PATH, key

N_WORDS = 25_000
C = {"B": "ବ", "CH": "ଚ", "D": "ଡ", "DH": "ଦ", "F": "ଫ", "G": "ଗ", "HH": "ହ", "JH": "ଜ", "K": "କ", "L": "ଲ",
     "M": "ମ", "N": "ନ", "NG": ["ଙ୍ଗ", "ଂ"], "P": "ପ", "R": "ର", "S": "ସ", "SH": "ଶ", "T": "ଟ", "TH": "ଥ", "V": ["ଭ", "ୱ"],
     "W": "ୱ", "Y": "ୟ", "Z": ["ଜ", "ସ"], "ZH": "ଜ"}
# vowel -> (independent letter, sign after a consonant) alternatives; "" = the inherent a
V = {"AA": [("ଆ", "ା")], "AE": [("ଆ", "ା"), ("ଏ", "େ"), ("ଆ", "ୟା")], "AH": [("ଅ", ""), ("ଆ", "ା"), ("ଏ", "େ")],
     "AO": [("ଅ", ""), ("ଓ", "ୋ"), ("ଆ", "ା")], "AW": [("ଆଉ", "ାଉ")], "AY": [("ଆଇ", "ାଇ")],
     "EH": [("ଏ", "େ")], "ER": [("ଅର", "ର")], "EY": [("ଏ", "େ")], "IH": [("ଇ", "ି")], "IY": [("ଇ", "ି")],
     "OW": [("ଓ", "ୋ")], "OY": [("ଅଏ", "ଏ")], "UH": [("ଉ", "ୁ")], "UW": [("ଉ", "ୁ")]}


def spellings(phones) -> set:
    opts, after_consonant = [], False
    for p in phones:
        base = re.sub(r"\d", "", p)
        if base in V:
            alts = V[base] + ([("ଇ", "ି"), ("ଉ", "ୁ")] if p == "AH0" else [])  # unstressed: middle ମିଡିଲ, ୟୁ
            opts.append([sign if after_consonant else letter for letter, sign in alts])
            after_consonant = False
        else:
            c = C[base]
            opts.append(c if isinstance(c, list) else [c])
            after_consonant = True
    return {key("".join(combo)) for combo in itertools.islice(itertools.product(*opts), 64)}


def main(cmudict, counts):
    pron = {}
    with open(cmudict, encoding="utf-8") as f:
        for line in f:
            parts = line.split("#")[0].split()
            pron.setdefault(re.sub(r"\(\d+\)$", "", parts[0]), []).append(parts[1:])
    with open(counts, encoding="utf-8") as f:
        rows = [(w, int(c)) for w, c in (line.split("\t") for line in f)]
    total = sum(c for _, c in rows)
    table, kept = {}, 0
    for w, c in rows:
        if w not in pron or (len(w) == 1 and w not in ("a", "i")):
            continue
        lp = math.log(c / total)
        for ph in pron[w]:
            for k in spellings(ph):
                if k not in table or table[k][1] < lp:
                    table[k] = (w, lp)
        kept += 1
        if kept >= N_WORDS:
            break
    with gzip.open(TABLE_PATH, "wt", encoding="utf-8", compresslevel=9) as f:
        f.writelines(f"{k}\t{w}\t{lp:.2f}\n" for k, (w, lp) in sorted(table.items()))
    print(f"{kept} words, {len(table)} spellings -> {TABLE_PATH}")


if __name__ == "__main__":
    assert key("ବିଜନେସ") in spellings("B IH1 Z N AH0 S".split())  # business
    main(*sys.argv[1:3])
