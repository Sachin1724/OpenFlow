"""
odia_refine.py - Speech-to-Writing refinement for Odia dictation.

refiner.py is English/Hinglish only (it contains no Odia characters at all), and
formatter.format() early-returns for every non-English language, so Odia dictation was
reaching the editor as raw ASR output. This is the Odia half of that pipeline:

  1. Verbal clutter      - hesitation sounds a speaker never meant to type
  2. Verbal backspaces   - "ଚାରିଟାରେ ... ନା ନା, ପାଞ୍ଚଟାରେ" -> "ପାଞ୍ଚଟାରେ"
  3. Numerals & currency - "ପାଞ୍ଚ ଶହ ଟଙ୍କା" -> "₹500",  "ଦୁଇ କୋଟି ଟଙ୍କା" -> "₹2 କୋଟି"
  4. English acronyms    - a run of single Odia letters is respaced: "ବିପିୟୁଟି" -> "ବି ପି ୟୁ ଟି"

Everything here is pure text, regex and dict lookups: no model, no network, sub-millisecond,
so it can run on the dictation hot path.

Deliberately NOT removed: ହଁ and ନା. They are "yes" and "no" -- content words, not fillers.
Stripping them would invert the meaning of a dictated sentence, which is far worse than
leaving a filler in.
"""

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Run directly (python engine/odia_refine.py) the package parent is not on the path, so the
# phonetic_translit import below would fail. Same bootstrap the other engine modules use.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Hesitation sounds only. Each is a word a speaker emits while thinking, never one they
# intend to appear in writing. Bounded by Odia word edges so they cannot eat part of a
# real word (ମାନେ as a standalone hesitation vs ମାନେ inside ସେମାନେ "they").
_ODIA_FILLER_WORDS = [
    "ମାନେ",      # "I mean" / "that is" used as a pause
    "ଆଚ୍ଛା",     # "okay"/"right" as a discourse filler
    "ଆଁ",        # "uh"
    "ଉଁ",        # "um"
    "ହୁଁ",       # "mm" backchannel
    "କଣ କି",     # "what is it" while groping for a word
    "ସେଇଟା",     # "that thing" as a placeholder
]

# A filler only counts when it stands alone as a word. Odia does not use spaces inside a
# word, so a space / punctuation / string boundary on both sides is the right fence; this
# is what keeps ସେମାନେ ("they") from being truncated to ସେ by the ମାନେ pattern.
_FENCE = r"(?:^|(?<=[\s,।?!]))"
_FENCE_END = r"(?=$|[\s,।?!])"
_FILLER_PATTERNS = [re.compile(_FENCE + re.escape(w) + _FENCE_END) for w in _ODIA_FILLER_WORDS]

# Markers that retract the ONE word just spoken: "ଚାରିଟାରେ ନା ନା ପାଞ୍ଚଟାରେ" replaces four
# o'clock with five and keeps the rest of the sentence. ନା ନା (doubled) is a correction;
# a single ନା is the ordinary word "no" and is left alone.
_WORD_CORRECTION_MARKERS = [
    "ନା ନା ନା",
    "ନା ନା",
    "ନୁହେଁ ନୁହେଁ",
    "ରହ ରହ",         # "wait, wait" -- doubled, like ନା ନା: a single ରହ is the verb "stay"
]

# Markers that retract the whole clause, not just a word.
_CLAUSE_CORRECTION_MARKERS = [
    "ଭୁଲ ହେଲା",      # "that was wrong"
    "ଛାଡ଼ ଛାଡ଼",       # "drop it, drop it" -- a single ଛାଡ଼ is the verb "leave"
]

_ODIA_UNITS: Dict[str, int] = {
    "ଶୂନ": 0, "ଏକ": 1, "ଗୋଟିଏ": 1, "ଦୁଇ": 2, "ତିନି": 3, "ଚାରି": 4, "ପାଞ୍ଚ": 5,
    "ଛଅ": 6, "ସାତ": 7, "ଆଠ": 8, "ନଅ": 9, "ଦଶ": 10, "ଏଗାର": 11, "ବାର": 12,
    "ତେର": 13, "ଚଉଦ": 14, "ପନ୍ଦର": 15, "ଷୋହଳ": 16, "ସତର": 17, "ଅଠର": 18,
    "ଉଣେଇଶ": 19, "କୋଡ଼ିଏ": 20, "ତିରିଶ": 30, "ଚାଳିଶ": 40, "ପଚାଶ": 50,
    "ଷାଠିଏ": 60, "ସତୁରି": 70, "ଅଶି": 80, "ନବେ": 90,
}

# ponytail: units 1-20 plus round tens, which covers money amounts and counts people
# actually dictate. Compound tens (ଏକାଉଶ 21, ବତିଶ 32, ...) fall through unchanged rather
# than being guessed at -- add the table if a user hits it.

# ଶହ and ହଜାର multiply out to digits. ଲକ୍ଷ and କୋଟି stay as words, because Indian
# convention writes ₹2 କୋଟି, not ₹20000000.
_MULTIPLY_SCALES: Dict[str, int] = {"ଶହ": 100, "ହଜାର": 1000}
_KEEP_SCALES = ("ଲକ୍ଷ", "କୋଟି")

_CURRENCY_WORDS = ("ଟଙ୍କା", "ଟାଙ୍କା")


def clean_odia_fillers(text: str) -> str:
    """Strips hesitation sounds, then repairs the punctuation and spacing they leave behind."""
    if not text:
        return ""
    cleaned = text
    for pattern in _FILLER_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    # A removed filler can leave ", ," or a comma against a danda or at the start.
    cleaned = re.sub(r"\s*,\s*(?=,)", "", cleaned)
    cleaned = re.sub(r"^\s*[,।]\s*", "", cleaned)
    cleaned = re.sub(r"\s*,\s*(?=।)", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def resolve_odia_self_corrections(text: str) -> str:
    """Applies verbal backspaces, keeping the replacement and dropping what was retracted.

    Word markers retract only the token immediately before them, so the rest of the
    sentence survives: "ବୈଠକ ଚାରିଟାରେ ନା ନା ପାଞ୍ଚଟାରେ" -> "ବୈଠକ ପାଞ୍ଚଟାରେ". Deleting the
    whole clause prefix instead would silently eat the subject.
    """
    if not text:
        return ""
    s = text

    # Longest marker first, so ନା ନା ନା is consumed before ନା ନା can match part of it.
    for marker in _WORD_CORRECTION_MARKERS:
        # The retracted token, optional comma, the marker, and the gap after it all go.
        s = re.sub(
            # _FENCE_END: the marker must end a word, or ରହ would match inside ରହିବି.
            r"(?:[^\s।?!]+)[,]?\s+" + re.escape(marker) + _FENCE_END + r"[,\s]*",
            "",
            s,
        )

    for marker in _CLAUSE_CORRECTION_MARKERS:
        # Clause starts at the string start or after a danda / question / exclamation, so
        # this never eats the previous finished sentence. The clause's leading whitespace is
        # captured and kept: the lookbehind is zero-width, so dropping it would weld the
        # replacement onto the preceding danda.
        s = re.sub(
            r"(^|(?<=[।?!]))(\s*)[^।?!]*?" + _FENCE + re.escape(marker) + _FENCE_END + r"[,\s]*",
            r"\1\2",
            s,
        )

    s = re.sub(r"^\s*[,।]\s*", "", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def _words_to_number(tokens: List[str]) -> Tuple[int, str]:
    """Folds a run of Odia number words into (value, kept_scale_word).

    kept_scale_word is "" for plain numbers, or ଲକ୍ଷ / କୋଟି when the value should stay
    written with its scale word."""
    total = 0
    current = 0
    keep = ""
    for tok in tokens:
        if tok in _ODIA_UNITS:
            current += _ODIA_UNITS[tok]
        elif tok in _MULTIPLY_SCALES:
            current = (current or 1) * _MULTIPLY_SCALES[tok]
            total += current
            current = 0
        elif tok in _KEEP_SCALES:
            keep = tok
    return total + current, keep


def format_odia_numerals(text: str) -> str:
    """Rewrites spoken Odia number words as digits, and ଟଙ୍କା as a ₹ prefix.

    "ପାଞ୍ଚ ଶହ ଟଙ୍କା"   -> "₹500"
    "ଦୁଇ କୋଟି ଟଙ୍କା"   -> "₹2 କୋଟି"
    "ତିନି ହଜାର ଲୋକ"    -> "3000 ଲୋକ"
    """
    if not text:
        return ""

    number_words = set(_ODIA_UNITS) | set(_MULTIPLY_SCALES) | set(_KEEP_SCALES)
    out: List[str] = []
    # Split on whitespace but keep trailing punctuation attached to its word, so a danda
    # ending the sentence survives the rewrite.
    tokens = text.split(" ")
    i = 0
    while i < len(tokens):
        raw = tokens[i]
        core = raw.strip(",।?!")
        if core not in number_words:
            out.append(raw)
            i += 1
            continue

        run: List[str] = []
        trailing = ""
        j = i
        while j < len(tokens):
            c = tokens[j].strip(",।?!")
            if c not in number_words:
                break
            run.append(c)
            trailing = tokens[j][len(c):]
            j += 1

        is_currency = False
        if j < len(tokens) and tokens[j].strip(",।?!") in _CURRENCY_WORDS:
            is_currency = True
            trailing = tokens[j][len(tokens[j].strip(",।?!")):]
            j += 1

        value, keep = _words_to_number(run)
        rendered = f"{value} {keep}".strip() if keep else str(value)
        if is_currency:
            rendered = "₹" + rendered
        out.append(rendered + trailing)
        i = j

    return " ".join(out)


def respace_odia_acronyms(text: str) -> str:
    """An English acronym dictated into Odia comes back as one glued cluster
    (ବିପିୟୁଟି); writing convention spaces the letters (ବି ପି ୟୁ ଟି)."""
    if not text:
        return ""
    try:
        from .phonetic_translit import ENGLISH_ACRONYM_LETTERS
    except ImportError:
        from engine.phonetic_translit import ENGLISH_ACRONYM_LETTERS

    # Longest letter-forms first, so ୟୁ is matched before ୟ.
    forms = sorted(set(ENGLISH_ACRONYM_LETTERS.values()), key=len, reverse=True)
    alt = "|".join(re.escape(f) for f in forms)
    # Only a run of 3+ letter-forms that fills a whole word is an acronym. Two is far too
    # common inside ordinary Odia words to touch.
    cluster = re.compile(_FENCE + r"(?:" + alt + r"){3,}" + _FENCE_END)

    def _space_out(m: "re.Match") -> str:
        s, parts = m.group(0), []
        while s:
            for f in forms:
                if s.startswith(f):
                    parts.append(f)
                    s = s[len(f):]
                    break
            else:
                return m.group(0)  # not cleanly decomposable; leave it alone
        return " ".join(parts)

    return cluster.sub(_space_out, text)


def refine_odia(text: str, strip_fillers: bool = True) -> str:
    """The full Odia refinement pass, in the order the stages depend on each other.

    Corrections run before filler removal, because some correction markers sit next to
    fillers and removing the filler first would break the marker's clause boundary.
    Numerals run before acronym respacing so a number word is never mistaken for a
    letter cluster.
    """
    if not text or not text.strip():
        return ""
    s = resolve_odia_self_corrections(text)
    if strip_fillers:
        s = clean_odia_fillers(s)
    s = format_odia_numerals(s)
    s = respace_odia_acronyms(s)
    return s.strip()


if __name__ == "__main__":
    # Fillers go; ହଁ and ନା stay, and a filler substring inside a real word is untouched.
    assert clean_odia_fillers("ମାନେ ମୁଁ ଆସିବି") == "ମୁଁ ଆସିବି"
    assert clean_odia_fillers("ହଁ ମୁଁ ଆସିବି") == "ହଁ ମୁଁ ଆସିବି", "ହଁ is 'yes', not a filler"
    assert clean_odia_fillers("ସେମାନେ ଆସିବେ") == "ସେମାନେ ଆସିବେ", "must not split ସେମାନେ"
    assert clean_odia_fillers("ଆଚ୍ଛା, ଠିକ ଅଛି") == "ଠିକ ଅଛି"

    # Verbal backspace keeps the correction and drops only the retracted word.
    assert resolve_odia_self_corrections("ଚାରିଟାରେ ନା ନା ପାଞ୍ଚଟାରେ") == "ପାଞ୍ଚଟାରେ"
    # The rest of the sentence survives -- ବୈଠକ is the subject, not part of the retraction.
    assert resolve_odia_self_corrections(
        "ବୈଠକ ଚାରିଟାରେ ନା ନା ପାଞ୍ଚଟାରେ ହେବ ।") == "ବୈଠକ ପାଞ୍ଚଟାରେ ହେବ ।"
    # A single ନା is the word "no" and must survive.
    assert resolve_odia_self_corrections("ନା ମୁଁ ଯିବି ନାହିଁ") == "ନା ମୁଁ ଯିବି ନାହିଁ"
    # A finished sentence before the correction is not eaten.
    assert resolve_odia_self_corrections("ମୁଁ ଆସିବି । ଚାରିଟା ନା ନା ପାଞ୍ଚଟା") == "ମୁଁ ଆସିବି । ପାଞ୍ଚଟା"
    # Clause markers still discard the whole clause they end.
    assert resolve_odia_self_corrections("ଚାରିଟାରେ ବୈଠକ ଛାଡ଼ ଛାଡ଼ ପାଞ୍ଚଟାରେ") == "ପାଞ୍ଚଟାରେ"
    assert resolve_odia_self_corrections("ଚାରିଟା ରହ ରହ ପାଞ୍ଚଟା") == "ପାଞ୍ଚଟା"
    # Markers are whole words, and the single verbs "stay" / "leave" are content, not corrections.
    assert resolve_odia_self_corrections("ମୁଁ ଘରେ ରହିବି") == "ମୁଁ ଘରେ ରହିବି", "ରହ inside ରହିବି"
    assert resolve_odia_self_corrections("ସେ ଘର ଛାଡ଼ି ଚାଲିଗଲା") == "ସେ ଘର ଛାଡ଼ି ଚାଲିଗଲା", "ଛାଡ଼ inside ଛାଡ଼ି"
    assert resolve_odia_self_corrections("ତୁମେ ଏଠି ରହ ମୁଁ ଆସୁଛି") == "ତୁମେ ଏଠି ରହ ମୁଁ ଆସୁଛି"
    assert resolve_odia_self_corrections("ମୋତେ ଛାଡ଼ ।") == "ମୋତେ ଛାଡ଼ ।"

    # Numerals and currency.
    assert format_odia_numerals("ପାଞ୍ଚ ଶହ ଟଙ୍କା") == "₹500"
    assert format_odia_numerals("ଦୁଇ କୋଟି ଟଙ୍କା") == "₹2 କୋଟି"
    assert format_odia_numerals("ତିନି ହଜାର ଲୋକ") == "3000 ଲୋକ"
    assert format_odia_numerals("ମୋତେ ଦୁଇ ଶହ ଟଙ୍କା ଦିଅ ।") == "ମୋତେ ₹200 ଦିଅ ।"
    assert format_odia_numerals("ଭଲ ଅଛି") == "ଭଲ ଅଛି"

    # Acronym respacing: 3+ glued letter-forms only.
    assert respace_odia_acronyms("ବିପିୟୁଟି ରେ ପଢ଼ିଛି") == "ବି ପି ୟୁ ଟି ରେ ପଢ଼ିଛି"
    assert respace_odia_acronyms("ଭଲ ଅଛି") == "ଭଲ ଅଛି"

    # Whole pipeline, and the empty case.
    assert refine_odia("ମାନେ ମୋତେ ପାଞ୍ଚ ଶହ ଟଙ୍କା ଦିଅ ।") == "ମୋତେ ₹500 ଦିଅ ।"
    assert refine_odia("") == ""
    assert refine_odia("   ") == ""
    print("odia_refine tests OK")
