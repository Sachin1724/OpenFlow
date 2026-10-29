"""
odia_mix.py — English words in English letters inside Odia dictation
=====================================================================
The Odia model writes everything in Odia script, so "business friendly" comes out as
"ବିଜନେସ ଫ୍ରେଣ୍ଡଲି". odia_english.tsv.gz (build_odia_english.py) maps the Odia spellings of
25k common English words, generated from their CMUdict pronunciations, back to English.

A word is switched only when its spelling matches and English is the likelier reading:
native-only letters, common Odia words and short words that are not English function words
stay in Odia script. ponytail: word-by-word lookup, no context; homophones take the more
frequent word ("no" for "know") and misheard English stays in Odia script.
"""

import gzip
import os

VIRAMA = "୍"
CONS = set(chr(c) for c in range(0x0B15, 0x0B3A)) | {"ୟ", "ୱ"}
_MAP = str.maketrans({"ୀ": "ି", "ୂ": "ୁ", "ଈ": "ଇ", "ଊ": "ଉ", "ଶ": "ସ", "ଷ": "ସ", "ଣ": "ନ", "ଂ": "ନ", "ଙ": "ନ",
                      "ଵ": "ୱ", "ୈ": "େ", "ୌ": "ୋ", VIRAMA: None, "‌": None, "‍": None, "଼": None, "ଁ": None, "ଃ": None})
NATIVE = set("ଖଘଛଝଞଠଢଧଯଋୠଐଔ")  # letters Odia spellings of English words never use (nor କ୍ଷ)
SHORT = set("i a is it in on of to the so and but you we my me he she do go no ok or at as be by if up us am an "
            "all are was has had have not now how who why what when this that then than there they our your yes".split())
# Common Odia words that sound like English ones (ଫୁଲ flower, not "full"; ମୋର my, not "more")
ODIA = set("ଟି ଟା ଏ ମୋର କଣ ବନ ଆର ଦାନ କାର ଶୋ କଷ୍ଟ ଦି ଫୁଲ ବାଟ ମାନ ଦାମ ଦାମ୍ ପ୍ର ସାନ ବାଣ କେଶ ସନ ସନ୍ ପର ସେଲ୍ "
           "ଦୋଷ ମାନି ସାପ ଷ୍ଟାର ଏସ୍ ଏସ ଏନ୍ ଏନ ଏମ୍ ଏମ ଓ ତ ଦଶ ଆଠ ବନାନ ମାପ ହାନ ମାଈ ଆଶ ଆଶ୍".split())
SUFFIXES = ("ର", "ରେ", "ରୁ", "କୁ", "ଟା", "ଟି")  # କାମ+ର "of work", not "camera"
OVERRIDE = {"ଅଫ": "of", "ଓକେ": "OK", "ହଭ": "have", "ଏମବିଏ": "MBA"}
MARGIN = 1.0  # English must be e^1 likelier than the Odia reading
TABLE_PATH = os.path.join(os.path.dirname(__file__), "odia_english.tsv.gz")


def key(word: str) -> str:
    """Spelling with the variation Odia writers use for English sounds folded away."""
    return word.translate(_MAP)


_OVERRIDE = {key(k): v for k, v in OVERRIDE.items()}
_table = None


def _load() -> dict:
    global _table
    if _table is None:
        with gzip.open(TABLE_PATH, "rt", encoding="utf-8") as f:
            _table = {k: (w, float(lp)) for k, w, lp in (line.rstrip("\n").split("\t") for line in f)}
    return _table


def english(word: str, lm=None):
    """The English word an Odia-script word spells, or None to keep it in Odia script."""
    k = key(word)
    if k in _OVERRIDE:
        return _OVERRIDE[k]
    hit = _load().get(k)
    if not hit or word in ODIA or NATIVE & set(word) or "କ୍ଷ" in word:
        return None
    en, en_lp = hit
    if en not in SHORT and (len(en) < 3 or sum(c in CONS for c in word) < 2 or not set(en) & set("aeiouy")):
        return None
    if lm is not None:
        if any(word.endswith(s) and lm.words.get(word[:-len(s)], 1 << 30) < 5000 for s in SUFFIXES):
            return None
        or_lp = lm.score("", word) - lm.BACKOFF if word in lm.words else lm.unk
        if en_lp <= or_lp + MARGIN:
            return None
    return "I" if en == "i" else en


def to_mixed(text: str, lm=None) -> str:
    return " ".join(english(w, lm) or w for w in text.split())


if __name__ == "__main__":
    out = to_mixed("ବିଜନେସ ଫ୍ରେଣ୍ଡଲି ନଥିଲା ଆଉ ମୋର ଫୁଲ ଅଫ ଦ ୱର୍ଲ୍ଡ")
    assert out == "business friendly ନଥିଲା ଆଉ ମୋର ଫୁଲ of the world", out
    print("ok")
