"""
prosody_tags.py — Non-Verbal & Emotional Prosody Tokens for MIRA ALM
===================================================================
Enables explicit conditioning on human vocal nuances:
- Breathing & inhalation: <breath>, <deep_breath>
- Emotional laughter: <chuckle>, <giggle>, <laugh>
- Conversational cadence: <pause_short>, <pause_long>, <hesitation>
- Intonation dynamics: <question_rise>, <emphatic>, <warm_drop>
"""

import re
from typing import List, Tuple, Dict

# Special tokens mapped to unique token IDs reserved for non-verbal acoustic conditioning
SPECIAL_PROSODY_TOKENS = [
    "<pad>",
    "<bos>",
    "<eos>",
    "<text_start>",
    "<text_end>",
    "<audio_start>",
    "<audio_end>",
    "<prompt_start>",
    "<prompt_end>",
    # Non-verbal vocal actions
    "<breath>",
    "<chuckle>",
    "<giggle>",
    "<laugh>",
    "<sigh>",
    "<throat_clear>",
    # Conversational phrasing markers
    "<pause_short>",     # 40ms catch-breath
    "<pause_medium>",    # 120ms clause boundary
    "<pause_long>",      # 250ms thought transition
    "<question_rise>",   # Tonal lift at Odia/Hindi question end
    "<emphatic>",        # Vocal intensity boost
    "<warm_whisper>"     # Intimate vocal timbre
]

PROSODY_TOKEN_TO_ID = {tok: idx for idx, tok in enumerate(SPECIAL_PROSODY_TOKENS)}
ID_TO_PROSODY_TOKEN = {idx: tok for idx, tok in enumerate(SPECIAL_PROSODY_TOKENS)}

_PROSODY_REGEX = re.compile(r'(<[a-z_]+>)')

def extract_prosody_spans(text: str) -> List[Tuple[str, bool]]:
    """
    Parses a string into chunks of (content, is_prosody_tag).
    Example:
      "ଆଚ୍ଛା <chuckle> ସତ କହିବାକୁ ଗଲେ <pause_short> ମୋତେ ବହୁତ ଭଲ ଲାଗିଲା ।"
    Returns:
      [("ଆଚ୍ଛା ", False), ("<chuckle>", True), (" ସତ କହିବାକୁ ଗଲେ ", False), ...]
    """
    parts = _PROSODY_REGEX.split(text)
    spans = []
    for p in parts:
        if not p:
            continue
        if p in PROSODY_TOKEN_TO_ID:
            spans.append((p, True))
        else:
            spans.append((p, False))
    return spans

def strip_prosody_tags(text: str) -> str:
    """Removes prosody markers for plain text processing."""
    return _PROSODY_REGEX.sub('', text)

if __name__ == '__main__':
    t = "ହଁ ଆଜ୍ଞା! <chuckle> ମସାଲା ଦୋସା ରେଡି ଅଛି। <pause_short> BPUT ହଷ୍ଟେଲରେ deliver ହେବ <question_rise>?"
    spans = extract_prosody_spans(t)
    print("Parsed Spans:")
    for s, is_tag in spans:
        print(f"  {'[TAG] ' if is_tag else '[TEXT]'} {s}")

