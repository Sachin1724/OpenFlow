"""
phonetic_translit.py — Native English-to-Odia Phonetic Transliteration & Acronym Expander
========================================================================================
Converts embedded English terms, modern tech vocabulary, academic fields, and acronyms
into native spoken Odia phonetic script so Odia neural TTS speaks them cleanly and naturally
(e.g., 'BPUT' -> 'ବି ପି ୟୁ ଟି', 'Mechanical Engineering' -> 'ମେକାନିକାଲ୍ ଇଞ୍ଜିନିୟରିଂ').
Also provides high-precision Odia <-> Devanagari Brahmic phonetic transliteration
enabling cross-lingual transfer from Hindi/Multilingual Audio Language Models (F5-TTS, Chatterbox).
"""

import os
import sys
import re
from typing import Optional



# ==============================================================================
# Direct Brahmic script mapping: Odia (0x0B00-0x0B7F) <-> Devanagari (0x0900-0x097F)
# ==============================================================================
ODIA_TO_DEVA = {
    # Independent Vowels
    'ଅ': 'अ', 'ଆ': 'आ', 'ଇ': 'इ', 'ଈ': 'ई', 'ଉ': 'उ', 'ଊ': 'ऊ',
    'ଋ': 'ऋ', 'ୠ': 'ॠ', 'ଌ': 'ऌ', 'ୡ': 'ॡ',
    'ଏ': 'ए', 'ଐ': 'ऐ', 'ଓ': 'ओ', 'ଔ': 'औ',

    # Consonants
    'କ': 'क', 'ଖ': 'ख', 'ଗ': 'ग', 'ଘ': 'घ', 'ଙ': 'ङ',
    'ଚ': 'च', 'ଛ': 'छ', 'ଜ': 'ज', 'ଝ': 'झ', 'ଞ': 'ञ',
    'ଟ': 'ट', 'ଠ': 'ठ', 'ଡ': 'ड', 'ଢ': 'ढ', 'ଣ': 'ण',
    'ତ': 'त', 'ଥ': 'थ', 'ଦ': 'द', 'ଧ': 'ध', 'ନ': 'न',
    'ପ': 'प', 'ଫ': 'फ', 'ବ': 'ब', 'ଭ': 'भ', 'ମ': 'म',
    'ଯ': 'य', 'ର': 'र', 'ଲ': 'ल', 'ଳ': 'ळ', 'ଵ': 'व',
    'ଶ': 'श', 'ଷ': 'ष', 'ସ': 'स', 'ହ': 'ह',

    # Additional Consonants / Nukta forms
    'ୟ': 'य', 'ଡ଼': 'ड़', 'ଢ଼': 'ढ़', 'ୱ': 'व',

    # Dependent Vowel Signs (Matras)
    'ା': 'ा', 'ି': 'ि', 'ୀ': 'ी', 'ୁ': 'ु', 'ୂ': 'ू',
    'ୃ': 'ृ', 'ୄ': 'ॄ', 'େ': 'े', 'ୈ': 'ै', 'ୋ': 'ो', 'ୌ': 'ौ',

    # Various Signs
    '୍': '्',  # Virama
    'ଂ': 'ं',  # Anusvara
    'ଃ': 'ः',  # Visarga
    'ଁ': 'ँ',  # Candrabindu
    'ଽ': 'ऽ',  # Avagraha

    # Digits
    '୦': '०', '୧': '१', '୨': '२', '୩': '३', '୪': '४',
    '୫': '५', '୬': '६', '୭': '७', '୮': '८', '୯': '९',

    # Punctuation / Avagraha
    '।': '।', '॥': '॥',
}

DEVA_TO_ODIA = {v: k for k, v in ODIA_TO_DEVA.items() if k not in ('ୟ', 'ୱ')}
# Special overrides for reverse
DEVA_TO_ODIA['ळ'] = 'ଳ'
DEVA_TO_ODIA['व'] = 'ବ'
DEVA_TO_ODIA['य'] = 'ଯ'

def odia_to_devanagari(text: str) -> str:
    """Translates Odia text to Devanagari script preserving word order and punctuation."""
    return "".join(ODIA_TO_DEVA.get(ch, ch) for ch in text)

def devanagari_to_odia(text: str) -> str:
    """Translates Devanagari text back to Odia script."""
    return "".join(DEVA_TO_ODIA.get(ch, ch) for ch in text)


# Direct Phonetic Romanization Mapping for Audio Language Models (like Chatterbox)
_ODIA_CONSONANTS_ROMAN = {
    'କ': 'k', 'ଖ': 'kh', 'ଗ': 'g', 'ଘ': 'gh', 'ଙ': 'ng',
    'ଚ': 'ch', 'ଛ': 'chh', 'ଜ': 'j', 'ଝ': 'jh', 'ଞ': 'ny',
    'ଟ': 't', 'ଠ': 'th', 'ଡ': 'd', 'ଢ': 'dh', 'ଣ': 'n',
    'ତ': 't', 'ଥ': 'th', 'ଦ': 'd', 'ଧ': 'dh', 'ନ': 'n',
    'ପ': 'p', 'ଫ': 'ph', 'ବ': 'b', 'ଭ': 'bh', 'ମ': 'm',
    'ଯ': 'j', 'ୟ': 'y', 'ର': 'r', 'ଲ': 'l', 'ଳ': 'l', 'ଵ': 'v', 'ୱ': 'w',
    'ଶ': 'sh', 'ଷ': 'sh', 'ସ': 's', 'ହ': 'h', 'ଡ଼': 'd', 'ଢ଼': 'dh'
}
_ODIA_VOWELS_ROMAN = {
    'ଅ': 'a', 'ଆ': 'aa', 'ଇ': 'i', 'ଈ': 'ee', 'ଉ': 'u', 'ଊ': 'oo',
    'ଋ': 'ru', 'ଏ': 'e', 'ଐ': 'ai', 'ଓ': 'o', 'ଔ': 'au'
}
_ODIA_MATRAS_ROMAN = {
    'ା': 'aa', 'ି': 'i', 'ୀ': 'ee', 'ୁ': 'u', 'ୂ': 'oo',
    'ୃ': 'ru', 'େ': 'e', 'ୈ': 'ai', 'ୋ': 'o', 'ୌ': 'au'
}

def odia_to_roman(text: str) -> str:
    """
    Transliterates native Odia text into readable Latin/Romanized phonetic script
    for consumption by English-backbone Audio Language Models (e.g. Chatterbox).
    """
    clean_text = text.replace('ଢ଼', 'dh').replace('ଡ଼', 'd')
    res = []
    i = 0
    n = len(clean_text)
    while i < n:
        ch = clean_text[i]
        if ch in _ODIA_CONSONANTS_ROMAN:
            cons = _ODIA_CONSONANTS_ROMAN[ch]
            if i + 1 < n:
                nxt = clean_text[i+1]
                if nxt in _ODIA_MATRAS_ROMAN:
                    res.append(cons + _ODIA_MATRAS_ROMAN[nxt])
                    i += 2
                    continue
                elif nxt == '୍':  # Virama / halanta
                    res.append(cons)
                    i += 2
                    continue
            res.append(cons + 'a')
            i += 1
        elif ch in _ODIA_VOWELS_ROMAN:
            res.append(_ODIA_VOWELS_ROMAN[ch])
            i += 1
        elif ch == 'ଂ':
            res.append('ng')
            i += 1
        elif ch == 'ଃ':
            res.append('h')
            i += 1
        elif ch == '।':
            res.append('.')
            i += 1
        else:
            res.append(ch)
            i += 1
    out = ''.join(res)
    # Strip any dangling non-ASCII characters to guarantee clean tokenization
    return re.sub(r'[^\x00-\x7F]+', '', out)


# English Letter Names for Spoken Acronyms (e.g. B-P-U-T, A-I, K-Y-C)
ENGLISH_ACRONYM_LETTERS = {
    "A": "ଏ",
    "B": "ବି",
    "C": "ସି",
    "D": "ଡି",
    "E": "ଇ",
    "F": "ଏଫ୍",
    "G": "ଜି",
    "H": "ଏଚ୍",
    "I": "ଆଇ",
    "J": "ଜେ",
    "K": "କେ",
    "L": "ଏଲ୍",
    "M": "ଏମ୍",
    "N": "ଏନ୍",
    "O": "ଓ",
    "P": "ପି",
    "Q": "କ୍ୟୁ",
    "R": "ଆର୍",
    "S": "ଏସ୍",
    "T": "ଟି",
    "U": "ୟୁ",
    "V": "ଭି",
    "W": "ଡବ୍ଲ୍ୟୁ",
    "X": "ଏକ୍ସ",
    "Y": "ୱାଇ",
    "Z": "ଜେଡ୍"
}

# Curated High-Precision Spoken English Vocabulary (Phonetic Loanwords)
CURATED_PHONETICS = {
    # Academic & Technical Disciplines
    "bput": "ବି ପି ୟୁ ଟି",
    "engineering": "ଇଞ୍ଜିନିୟରିଂ",
    "engineer": "ଇଞ୍ଜିନିୟର",
    "engineers": "ଇଞ୍ଜିନିୟର୍ସ",
    "mechanical": "ମେକାନିକାଲ୍",
    "civil": "ସିଭିଲ୍",
    "electrical": "ଇଲେକ୍ଟ୍ରିକାଲ୍",
    "electronic": "ଇଲେକ୍ଟ୍ରୋନିକ୍",
    "electronics": "ଇଲେକ୍ଟ୍ରୋନିକ୍ସ",
    "computer": "କମ୍ପ୍ୟୁଟର",
    "science": "ସାଇନ୍ସ",
    "technology": "ଟେକ୍ନୋଲୋଜି",
    "technologies": "ଟେକ୍ନୋଲୋଜିଜ୍",
    "artificial": "ଆର୍ଟିଫିସିଆଲ୍",
    "intelligence": "ଇଣ୍ଟେଲିଜେନ୍ସ",
    "innovation": "ଇନୋଭେସନ୍",
    "innovations": "ଇନୋଭେସନ୍ସ",
    "innovative": "ଇନୋଭେଟିଭ୍",
    "research": "ରିସର୍ଚ୍ଚ",
    "robotics": "ରୋବୋଟିକ୍ସ",
    "design": "ଡିଜାଇନ୍",
    "coding": "କୋଡିଂ",
    "code": "କୋଡ୍",
    "program": "ପ୍ରୋଗ୍ରାମ୍",
    "programming": "ପ୍ରୋଗ୍ରାମିଂ",
    "software": "ସଫ୍ଟୱେୟାର",
    "hardware": "ହାର୍ଡୱେୟାର",
    "developer": "ଡେଭଲପର",
    "development": "ଡେଭଲପମେଣ୍ଟ",
    "data": "ଡାଟା",
    "database": "ଡାଟାବେସ୍",
    "machine": "ମେସିନ୍",
    "learning": "ଲର୍ଣ୍ଣିଂ",
    "network": "ନେଟୱାର୍କ",
    "system": "ସିଷ୍ଟମ୍",
    "systems": "ସିଷ୍ଟମ୍ସ",
    "application": "ଆପ୍ଲିକେସନ୍",
    "applications": "ଆପ୍ଲିକେସନ୍ସ",
    "app": "ଆପ୍",
    "apps": "ଆପ୍ସ",
    "web": "ୱେବ୍",
    "website": "ୱେବସାଇଟ୍",
    "cloud": "କ୍ଲାଉଡ୍",
    "server": "ସର୍ଭର୍",
    "digital": "ଡିଜିଟାଲ୍",
    "online": "ଅନଲାଇନ୍",
    "internet": "ଇଣ୍ଟରନେଟ୍",
    "model": "ମଡେଲ୍",
    "models": "ମଡେଲ୍ସ",
    "algorithm": "ଆଲଗୋରିଦମ୍",

    # Action & Creative Verbs
    "build": "ବିଲ୍ଡ",
    "building": "ବିଲ୍ଡିଂ",
    "builder": "ବିଲ୍ଡର",
    "create": "କ୍ରିଏଟ୍",
    "creating": "କ୍ରିଏଟିଂ",
    "solve": "ସଲ୍ଭ",
    "solving": "ସଲ୍ଭିଂ",
    "solution": "ସଲ୍ୟୁସନ୍",
    "solutions": "ସଲ୍ୟୁସନ୍ସ",
    "problem": "ପ୍ରୋବ୍ଲେମ୍",
    "problems": "ପ୍ରୋବ୍ଲେମ୍ସ",
    "real": "ରିଅଲ୍",
    "world": "ୱାର୍ଲ୍ଡ",
    "real-world": "ରିଅଲ୍-ୱାର୍ଲ୍ଡ",
    "project": "ପ୍ରୋଜେକ୍ଟ",
    "projects": "ପ୍ରୋଜେକ୍ଟସ",
    "idea": "ଆଇଡିଆ",
    "ideas": "ଆଇଡିଆଜ୍",
    "start": "ଷ୍ଟାର୍ଟ",
    "startup": "ଷ୍ଟାର୍ଟଅପ୍",
    "startups": "ଷ୍ଟାର୍ଟଅପ୍ସ",
    "launch": "ଲଞ୍ଚ",
    "test": "ଟେଷ୍ଟ",
    "testing": "ଟେଷ୍ଟିଂ",
    "update": "ଅପଡେଟ୍",
    "upgrade": "ଅପଗ୍ରେଡ୍",
    "verify": "ଭେରିଫାଏ",
    "verified": "ଭେରିଫାଏଡ୍",
    "verification": "ଭେରିଫିକେସନ୍",
    "support": "ସପୋର୍ଟ",
    "service": "ସର୍ଭିସ୍",
    "services": "ସର୍ଭିସେସ୍",
    "team": "ଟିମ୍",
    "future": "ଫ୍ୟୁଚର୍",
    "success": "ସକ୍ସେସ୍",
    "successful": "ସକ୍ସେସଫୁଲ୍",
    "challenge": "ଚ୍ୟାଲେଞ୍ଜ",
    "opportunity": "ଅପର୍ଚୁନିଟି",
    "platform": "ପ୍ଲାଟଫର୍ମ",

    # Campus & Lifestyle
    "rourkela": "ରାଉରକେଲା",
    "bhubaneswar": "ଭୁବନେଶ୍ୱର",
    "cuttack": "କଟକ",
    "sambalpur": "ସମ୍ବଲପୁର",
    "berhampur": "ବ୍ରହ୍ମପୁର",
    "college": "କଲେଜ୍",
    "university": "ୟୁନିଭର୍ସିଟି",
    "student": "ଷ୍ଟୁଡେଣ୍ଟ",
    "students": "ଷ୍ଟୁଡେଣ୍ଟସ",
    "campus": "କ୍ୟାମ୍ପସ୍",
    "hostel": "ହଷ୍ଟେଲ୍",
    "hall": "ହଲ୍",
    "residence": "ରେସିଡେନ୍ସ",
    "class": "କ୍ଲାସ୍",
    "semester": "ସେମିଷ୍ଟାର",
    "exam": "ଏକ୍ସାମ୍",
    "degree": "ଡିଗ୍ରୀ",
    "branch": "ବ୍ରାଞ୍ଚ",
    "lab": "ଲ୍ୟାବ୍",

    # Everyday Objects, Food & Commerce
    "phone": "ଫୋନ୍",
    "mobile": "ମୋବାଇଲ୍",
    "call": "କଲ୍",
    "calling": "କଲିଂ",
    "message": "ମେସେଜ୍",
    "help": "ହେଲ୍ପ",
    "time": "ଟାଇମ୍",
    "office": "ଅଫିସ୍",
    "work": "ୱାର୍କ",
    "doctor": "ଡାକ୍ତର",
    "hospital": "ହସ୍ପିଟାଲ୍",
    "school": "ସ୍କୁଲ୍",
    "bus": "ବସ୍",
    "train": "ଟ୍ରେନ୍",
    "car": "କାର୍",
    "bike": "ବାଇକ୍",
    "road": "ରୋଡ୍",
    "order": "ଅର୍ଡର",
    "orders": "ଅର୍ଡରସ",
    "deliver": "ଡେଲିଭର",
    "delivery": "ଡେଲିଭରୀ",
    "booking": "ବୁକିଂ",
    "book": "ବୁକ୍",
    "cart": "କାର୍ଟ",
    "address": "ଆଡ୍ରେସ୍",
    "dosa": "ଦୋସା",
    "biryani": "ବିରିୟାନୀ",
    "chicken": "ଚିକେନ୍",
    "masala": "ମସାଲା",
    "total": "ଟୋଟାଲ୍",
    "bill": "ବିଲ୍",
    "discount": "ଡିସକାଉଣ୍ଟ",
    "price": "ପ୍ରାଇସ୍",
    "rate": "ରେଟ୍",
    "item": "ଆଇଟମ୍",
    "items": "ଆଇଟମ୍ସ",
    "hotel": "ହୋଟେଲ୍",
    "restaurant": "ରେଷ୍ଟୁରାଣ୍ଟ",
    "menu": "ମେନୁ",
    "payment": "ପେମେଣ୍ଟ",
    "cash": "କ୍ୟାଶ୍",
    "card": "କାର୍ଡ",
    "bank": "ବ୍ୟାଙ୍କ",
    "account": "ଆକାଉଣ୍ଟ",
    "customer": "କଷ୍ଟମର",
    "mira": "ମୀରା",
    "audio": "ଅଡିଓ",
    "video": "ଭିଡିଓ",
    "voice": "ଭଏସ୍",
    "speech": "ସ୍ପିଚ୍",
    "cricket": "କ୍ରିକେଟ୍",
    "match": "ମ୍ୟାଚ୍",
    "fast": "ଫାଷ୍ଟ",
    "best": "ବେଷ୍ଟ",
    "super": "ସୁପର୍",
    "ready": "ରେଡି",
    "ok": "ଓକେ",
    "okay": "ଓକେ",
    "yes": "ୟେସ୍",
    "no": "ନୋ",
    "hi": "ହାଏ",
    "hello": "ହେଲୋ",
    "thanks": "ଥାଙ୍କସ୍",
    "thank": "ଥାଙ୍କ",
    "you": "ୟୁ",
    "please": "ପ୍ଲିଜ୍"
}

# Phonetic G2P replacement rules for novel words
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
    ("ou", "ାଉ"), ("ow", "ାଉ"), ("tion", "ସନ୍"), ("sion", "ସନ୍"),
    ("a", "ା"), ("e", "େ"), ("i", "ି"), ("o", "ୋ"), ("u", "ୁ")
]

def transliterate_acronym(acronym: str) -> str:
    """Spells out uppercase acronyms letter-by-letter in Odia (e.g. BPUT -> ବି ପି ୟୁ ଟି)."""
    clean_acro = re.sub(r'[^A-Z]', '', acronym)
    letters = [ENGLISH_ACRONYM_LETTERS[ch] for ch in clean_acro if ch in ENGLISH_ACRONYM_LETTERS]
    return " ".join(letters)

def transliterate_word(word: str) -> str:
    """Translates a single English word into its natural Odia phonetic representation."""
    raw = word.strip()
    if not raw:
        return ""

    # 1. Hyphenated compound words (e.g. Real-world -> ରିଅଲ୍-ୱାର୍ଲ୍ଡ)
    if "-" in raw:
        parts = raw.split("-")
        return "-".join(transliterate_word(p) for p in parts)

    # 2. Check for Acronyms (e.g. BPUT, AI, KYC, OTP, IIT, NIT, BTech, B.Tech)
    if len(raw) >= 2 and (raw.isupper() or ('.' in raw and re.sub(r'\.', '', raw).isupper())):
        return transliterate_acronym(raw)

    # Special case for mixed case acronyms like BTech
    if raw.lower() in ["btech", "b.tech"]:
        return "ବି ଟେକ୍"
    if raw.lower() in ["mtech", "m.tech"]:
        return "ଏମ୍ ଟେକ୍"

    w = raw.lower()

    # 3. Direct dictionary match
    if w in CURATED_PHONETICS:
        return CURATED_PHONETICS[w]

    # 4. Morphological matching (plural -s, -ing, -ed)
    if w.endswith("s") and len(w) > 3 and w[:-1] in CURATED_PHONETICS:
        base = CURATED_PHONETICS[w[:-1]]
        return base + "୍" if base.endswith(("ସ", "ଜ")) else base + "ସ"

    if w.endswith("ing") and len(w) > 4 and w[:-3] in CURATED_PHONETICS:
        return CURATED_PHONETICS[w[:-3]] + "ିଂ"

    if w.endswith("ed") and len(w) > 3 and w[:-2] in CURATED_PHONETICS:
        return CURATED_PHONETICS[w[:-2]] + "୍"

    # 5. Rule-based phonetic fallback with halant preservation
    res = w
    for eng, odia in CONSONANTS:
        res = res.replace(eng, odia)
    for eng, odia in VOWELS:
        res = res.replace(eng, odia)
    res = re.sub(r"[a-z]", "", res)
    return res if res else raw


_ODIA_DIGITS = {
    '0': 'ଶୂନ', '1': 'ଏକ', '2': 'ଦୁଇ', '3': 'ତିନି', '4': 'ଚାରି',
    '5': 'ପାଞ୍ଚ', '6': 'ଛଅ', '7': 'ସାତ', '8': 'ଆଠ', '9': 'ନଅ'
}

def normalize_smart_numbers(text: str) -> str:
    """
    Intelligently converts raw numbers, currency (₹, Rs), percentages, and phone numbers
    into authentic spoken Odia words before sending to acoustic models.
    """
    if not text:
        return ""

    # 1. Currency: ₹120 or Rs. 250 -> ... ଟଙ୍କା
    def _curr(m):
        raw = m.group(1) or m.group(2)
        val = int(raw)
        try:
            import indic_tiny_tts.textnorm as tn
            return tn.numbers.cardinal(val, 'or') + ' ଟଙ୍କା'
        except Exception:
            return f"{val} ଟଙ୍କା"

    t = re.sub(r'[₹]\s*(\d+)|(?:Rs\.?|INR)\s*(\d+)', _curr, text)

    # 2. 10-digit Indian Mobile Phone Numbers -> Digit-by-digit spoken Odia
    def _phone(m):
        return ' '.join(_ODIA_DIGITS.get(d, d) for d in m.group(0))

    t = re.sub(r'\b[6-9]\d{9}\b', _phone, t)

    # 3. Percentages: 50% -> ପଚାଶ ପ୍ରତିଶତ
    def _pct(m):
        val = int(m.group(1))
        try:
            import indic_tiny_tts.textnorm as tn
            return tn.numbers.cardinal(val, 'or') + ' ପ୍ରତିଶତ'
        except Exception:
            return f"{val} ପ୍ରତିଶତ"

    t = re.sub(r'(\d+)\s*%', _pct, t)

    # 4. Standalone numbers (e.g. 2 dosa, 15 items) -> Odia Cardinal
    def _card(m):
        val = int(m.group(0))
        if val < 10000000:
            try:
                import indic_tiny_tts.textnorm as tn
                return tn.numbers.cardinal(val, 'or')
            except Exception:
                return m.group(0)
        return m.group(0)

    t = re.sub(r'\b\d+\b', _card, t)
    return t


# ---------------------------------------------------------------------------
# Odia Ligatures & Spoken Consonant Cluster Normalization (Schwa Suppression)
# ---------------------------------------------------------------------------
# Eliminates robotic, disjoint syllable separation (e.g. 'ବି-ଲ-କୁ-ଲ' -> 'ବିଲ୍କୁଲ୍' [Bilkul])
# Ensures loanwords and conversational vocabulary are pronounced tightly and connectedly.
ODIA_PHONETIC_LIGATURE_MAP = {
    # 1. High-frequency conversational adverbs & discourse markers
    "ବିଲକୁଲ": "ବିଲ୍କୁଲ୍",
    "ବିଲକୁଲ୍": "ବିଲ୍କୁଲ୍",
    "ଜଲଦି": "ଜଲ୍‌ଦି",
    "ଜଲ୍ଦି": "ଜଲ୍‌ଦି",
    "ମୁସକିଲ": "ମୁସ୍କିଲ୍",
    "ମୁସ୍କିଲ": "ମୁସ୍କିଲ୍",
    "ସରକାର": "ସର୍କାର୍",
    "ସରକାରୀ": "ସର୍କାରୀ",
    "ବାସ": "ବାସ୍",
    "ଖାସ": "ଖାସ୍",
    "ପାସ": "ପାସ୍",
    "ସାଫ": "ସାଫ୍",
    "ଚେକ": "ଚେକ୍",
    "ପ୍ୟାକ": "ପ୍ୟାକ୍",
    
    # 2. Modern loanwords & conversational terms
    "ଅର୍ଡର": "ଅର୍ଡର୍",
    "ଅଫିସ": "ଅଫିସ୍",
    "ହଷ୍ଟେଲ": "ହଷ୍ଟେଲ୍",
    "ପାର୍ସଲ": "ପାର୍ସଲ୍",
    "ଡେଲିଭର": "ଡେଲିଭର୍",
    "ଡେଲିଭରି": "ଡେଲିଭରୀ",
    "କନଫର୍ମ": "କନ୍‌ଫର୍ମ୍",
    "କନ୍ଫର୍ମ": "କନ୍‌ଫର୍ମ୍",
    "ପରଫେକ୍ଟ": "ପର୍‌ଫେକ୍ଟ",
    "ନମ୍ବର": "ନମ୍ବର୍",
    "ସିଷ୍ଟମ": "ସିଷ୍ଟମ୍",
    "ପ୍ରୋଗ୍ରାମ": "ପ୍ରୋଗ୍ରାମ୍",
    "ଟାଇମ": "ଟାଇମ୍",
    "ଟିମ": "ଟିମ୍",
    "ଫିଲ୍ମ": "ଫିଲ୍ମ୍",
    "ନ୍ୟୁଜ": "ନ୍ୟୁଜ୍",
    "ଲାଇଭ": "ଲାଇଭ୍",
    "ଫୋନ": "ଫୋନ୍",
    "ପ୍ଲାନ": "ପ୍ଲାନ୍",
    "କଲ": "କଲ୍",
    "ବଲ": "ବଲ୍",
    "ସ୍କୁଲ": "ସ୍କୁଲ୍",
    "ମ୍ୟାଡାମ": "ମ୍ୟାଡାମ୍",
    "ମ୍ୟାଡମ": "ମ୍ୟାଡାମ୍",
    "ମେସେଜ": "ମେସେଜ୍",
    "ମ୍ୟାସେଜ": "ମେସେଜ୍",
    "ଟ୍ରାଫିକ": "ଟ୍ରାଫିକ୍",
    "ପୋଲିସ": "ପୋଲିସ୍",
    "ଚ୍ୟାନେଲ": "ଚ୍ୟାନେଲ୍",
    "କମ୍ପ୍ଲିଟ": "କମ୍ପ୍ଲିଟ୍",
    "ପର୍ସେଣ୍ଟ": "ପର୍ସେଣ୍ଟ୍",
    "ଏପିସୋଡ": "ଏପିସୋଡ୍",
    "ବ୍ୟାଙ୍କ": "ବ୍ୟାଙ୍କ୍",
    "କାର୍ଡ": "କାର୍ଡ୍",
    "ଫ୍ରେଣ୍ଡ": "ଫ୍ରେଣ୍ଡ୍",
    "ବେଷ୍ଟ": "ବେଷ୍ଟ୍",
    "ଫାଷ୍ଟ": "ଫାଷ୍ଟ୍",
    "ଲାଷ୍ଟ": "ଲାଷ୍ଟ୍",
    "ସର୍ଭିସ": "ସର୍ଭିସ୍",
    "କ୍ଲିନିକ": "କ୍ଲିନିକ୍",
    "ଲୋକେସନ": "ଲୋକେସନ୍",
    "ଆଡ୍ରେସ": "ଆଡ୍ରେସ୍",
    "ୱେବସାଇଟ": "ୱେବ୍‌ସାଇଟ୍",
    "ଡିଷ୍ଟ୍ରିକ": "ଡିଷ୍ଟ୍ରିକ୍ଟ",
    "ଡାକ୍ତର": "ଡାକ୍ଟର୍",
    "ଟେବୁଲ": "ଟେବୁଲ୍",
    "ବୋତଲ": "ବୋତଲ୍",
    "ବିଜନେସ": "ବିଜ୍‌ନେସ୍"
}

def normalize_odia_ligatures(text: str) -> str:
    """
    Normalizes words with inherent vowel separation (e.g. 'ବିଲକୁଲ' -> 'ବିଲ୍କୁଲ୍')
    so that TTS models do not pronounce syllables separately as 'bi-la-ku-la',
    but speak them tightly and natively as 'bilkul'.
    """
    if not text:
        return ""
    
    # Replace known words using whole-word boundary patterns for Odia script
    for word, replacement in ODIA_PHONETIC_LIGATURE_MAP.items():
        pattern = r'(?<![଀-୿])' + re.escape(word) + r'(?![଀-୿])'
        text = re.sub(pattern, replacement, text)
        
    return text


def prepare_text_for_tts(text: str) -> str:
    """
    Cleans generated text and converts embedded English words, acronyms, currency,
    numbers, phone numbers, and Odia ligatures into natural spoken Odia phonetics.
    Guarantees clean, broadcast-quality pronunciation of English and Odia mixed speech.
    """
    # 1. Strip replacement characters and dangling UTF-8 bytes
    clean = text.replace("\ufffd", "").replace("", "").strip()

    # 2. Smart Inverse Text Normalization (Numbers, ₹ Currency, Phone Numbers, %)
    clean = normalize_smart_numbers(clean)

    # 3. Transliterate standalone English words and hyphenated compounds
    def _rep(match):
        w = match.group(0)
        return transliterate_word(w)

    # Match English words, acronyms, and hyphenated terms (e.g., BPUT, Real-world)
    clean = re.sub(r'[a-zA-Z]+(?:-[a-zA-Z]+)*|\b[a-zA-Z](?:\.[a-zA-Z])+\b', _rep, clean)
    
    # 4. Odia Ligatures & Spoken Consonant Cluster Normalization under Reinforcement Learning
    try:
        from engine.pronunciation_rl import PronunciationRLAgent
        global _rl_pronunciation_agent
        if '_rl_pronunciation_agent' not in globals() or _rl_pronunciation_agent is None:
            _rl_pronunciation_agent = PronunciationRLAgent()
        clean = _rl_pronunciation_agent.normalize_text_rl(clean)
    except Exception:
        clean = normalize_odia_ligatures(clean)
    
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


if __name__ == "__main__":
    sample_odia = "ନମସ୍କାର ଆଜ୍ଞା ! ମୁଁ ମୀରା, ଆପଣଙ୍କ ଓଡ଼ିଆ ସାଥୀ । ଆଜି ଆପଣ କ'ଣ ଖାଇବାକୁ ପସନ୍ଦ କରିବେ ?"
    deva = odia_to_devanagari(sample_odia)
    print("Odia original  :", sample_odia)
    print("Devanagari phon:", deva)
    back = devanagari_to_odia(deva)
    print("Back to Odia   :", back)
