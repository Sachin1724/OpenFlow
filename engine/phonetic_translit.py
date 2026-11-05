"""
phonetic_translit.py — High-Performance English-to-Odia Phonetic Transliteration
==================================================================================
Converts English words (loanwords, modern tech terms, names) into authentic Odia
phonetic script for offline Text-to-Speech (TTS) models (e.g. Meta MMS-TTS) that
only contain Odia Unicode characters (\u0B00-\u0B7F).
"""

import os
import re
import gzip
from pathlib import Path

TSV_PATH = os.path.join(os.path.dirname(__file__), "odia_english.tsv.gz")

_EN_TO_ODIA = {}

def _init_dict():
    global _EN_TO_ODIA
    if _EN_TO_ODIA:
        return

    # 1. Reverse mapping from odia_english 25,000 word corpus
    if os.path.exists(TSV_PATH):
        try:
            with gzip.open(TSV_PATH, "rt", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split("\t")
                    if len(parts) >= 2:
                        or_word, en_word = parts[0], parts[1].lower()
                        if en_word not in _EN_TO_ODIA:
                            _EN_TO_ODIA[en_word] = or_word
        except Exception:
            pass

    # 2. High-precision curated Indian colloquial loanwords & conversational phrases
    CURATED = {
        # Everyday Food / Objects
        "tea": "ଚା",
        "coffee": "କଫି",
        "cilantro": "ଧନିଆ",
        "phone": "ଫୋନ୍",
        "mobile": "ମୋବାଇଲ୍",
        "call": "କଲ୍",
        "calling": "କଲିଂ",
        "message": "ମେସେଜ୍",
        "help": "ହେଲ୍ପ",
        "time": "ଟାଇମ୍",
        "office": "ଅଫିସ୍",
        "work": "ଓ୍ୱାର୍କ",
        "doctor": "ଡାକ୍ତର",
        "hospital": "ହସ୍ପିଟାଲ୍",
        "school": "ସ୍କୁଲ୍",
        "college": "କଲେଜ୍",
        "bus": "ବସ୍",
        "train": "ଟ୍ରେନ୍",
        "car": "କାର୍",
        "bike": "ବାଇକ୍",
        "road": "ରୋଡ୍",
        "police": "ପୋଲିସ୍",

        # Tech / Social Media / Media
        "ai": "ଏଆଇ",
        "assistant": "ଆସିଷ୍ଟାଣ୍ଟ",
        "mira": "ମୀରା",
        "match": "ମ୍ୟାଚ୍",
        "cricket": "କ୍ରିକେଟ୍",
        "football": "ଫୁଟବଲ୍",
        "youtube": "ୟୁଟ୍ୟୁବ୍",
        "video": "ଭିଡିଓ",
        "podcast": "ପଡକାଷ୍ଟ",
        "online": "ଅନଲାଇନ୍",
        "internet": "ଇଣ୍ଟରନେଟ୍",
        "computer": "କମ୍ପ୍ୟୁଟର",
        "laptop": "ଲାପଟପ୍",
        "game": "ଗେମ୍",

        # Conversational Emotions / Fillers
        "tension": "ଟେନସନ୍",
        "problem": "ପ୍ରୋବ୍ଲେମ୍",
        "sorry": "ସରି",
        "thank": "ଥାଙ୍କ",
        "thanks": "ଥାଙ୍କସ୍",
        "you": "ୟୁ",
        "please": "ପ୍ଲିଜ୍",
        "super": "ସୁପର୍",
        "ready": "ରେଡି",
        "ok": "ଓକେ",
        "okay": "ଓକେ",
        "yes": "ୟେସ୍",
        "no": "ନୋ",
        "hi": "ହାଏ",
        "hello": "ହେଲୋ",
        "bye": "ବାଏ"
    }
    _EN_TO_ODIA.update(CURATED)

# Phonetic G2P replacement rules
CONSONANTS = [
    ("sh", "ଶ"), ("ch", "ଚ"), ("th", "ଥ"), ("ph", "ଫ"), ("kh", "ଖ"), ("gh", "ଘ"),
    ("jh", "ଜ"), ("bh", "ଭ"), ("dh", "ଦ"), ("wh", "ୱ"),
    ("b", "ବ"), ("c", "କ"), ("d", "ଡ"), ("f", "ଫ"), ("g", "ଗ"), ("h", "ହ"),
    ("j", "ଜ"), ("k", "କ"), ("l", "ଲ"), ("m", "ମ"), ("n", "ନ"), ("p", "ପ"),
    ("q", "କ"), ("r", "ର"), ("s", "ସ"), ("t", "ଟ"), ("v", "ଭ"), ("w", "ୱ"),
    ("x", "କ୍ସ"), ("y", "ୟ"), ("z", "ଜ")
]
VOWELS = [
    ("ee", "ି"), ("oo", "ୁ"), ("ea", "ି"), ("ai", "ାଇ"), ("ay", "େ"),
    ("ou", "ାଉ"), ("ow", "ାଉ"), ("a", "ା"), ("e", "େ"), ("i", "ି"),
    ("o", "ୋ"), ("u", "ୁ")
]

def transliterate_word(word: str) -> str:
    """Translates a single English word into its Odia phonetic representation."""
    _init_dict()
    w = word.lower().strip()
    if not w:
        return ""
    if w in _EN_TO_ODIA:
        return _EN_TO_ODIA[w]

    res = w
    for eng, odia in CONSONANTS:
        res = res.replace(eng, odia)
    for eng, odia in VOWELS:
        res = res.replace(eng, odia)
    res = re.sub(r"[a-z]", "", res)
    return res if res else word


def prepare_text_for_tts(text: str) -> str:
    """
    Cleans generated text and converts all embedded English words into Odia phonetics.
    Guarantees that MMS-TTS speaks out loud every word, including middle English words.
    """
    _init_dict()

    # 1. Strip replacement characters and dangling UTF-8 bytes
    clean = text.replace("\ufffd", "").replace("", "").strip()

    # 2. Strip glued Latin fragments caused by BPE byte corruption (e.g. 'ଞj୍ତର' -> 'ଞ୍ତର')
    clean = re.sub(r'([\u0B00-\u0B7F]+)[a-zA-Z]+', r'\1', clean)
    clean = re.sub(r'[a-zA-Z]+([\u0B00-\u0B7F]+)', r'\1', clean)

    # 3. Transliterate standalone English words into Odia script
    def _rep(match):
        w = match.group(0)
        return transliterate_word(w)

    clean = re.sub(r'[a-zA-Z]+', _rep, clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean
