"""
acoustic_lid_router.py — Real-Time Multilingual Code-Switching & Acoustic Router
================================================================================
Enables seamless mid-call code-switching between Odia, Sambalpuri, Hindi, and English
without dropping shopping cart state or conversational context.

Examples:
- Customer orders in Odia: "ଗୋଟେ ବିରିୟାନୀ ପ୍ୟାକ୍ କର"
- Switches to English: "Can you speak in English, please? Does it contain nuts?"
- MIRA immediately responds in English: "Sure! The Chicken Biryani is nut-free. Would you like anything else?"
- Switches to Hindi: "भैया इसमें रायता भी जोड़ दो"
- MIRA acknowledges in Hindi: "जी बिल्कुल, रायता जोड़ दिया गया है।"
"""

import re
from typing import Dict, Any, Tuple, Optional


# Multilingual Acoustic Profile Configuration
LANG_PROFILES: Dict[str, Dict[str, Any]] = {
    "or": {
        "name": "Standard Odia",
        "lang_id": 4,
        "default_female_row": 8,
        "default_male_row": 9,
        "sample_rate": 24000,
        "script": "Oriya"
    },
    "ory_sambalpuri": {
        "name": "Sambalpuri (Kosali)",
        "lang_id": 4,
        "default_female_row": 8,
        "default_male_row": 9,
        "sample_rate": 24000,
        "script": "Oriya"
    },
    "hi": {
        "name": "Hindi",
        "lang_id": 1,
        "default_female_row": 2,
        "default_male_row": 3,
        "sample_rate": 24000,
        "script": "Devanagari"
    },
    "en": {
        "name": "Indian English",
        "lang_id": 0,
        "default_female_row": 0,
        "default_male_row": 1,
        "sample_rate": 24000,
        "script": "Latin"
    }
}


class AcousticLIDRouter:
    def __init__(self, default_lang: str = "or"):
        self.current_lang = default_lang

    def detect_language(self, text: str) -> Tuple[str, float, str]:
        """
        Classifies incoming utterance language and detects explicit switch commands.
        Returns: (detected_lang_code, confidence, detection_reason)
        """
        t_low = text.lower().strip()

        # 1. Explicit Switch Commands
        if any(w in t_low for w in ["speak in english", "in english", "can you speak english", "english please"]):
            return "en", 1.0, "explicit_command"
        if any(w in t_low for w in ["speak in hindi", "hindi please", "हिंदी में", "ହିନ୍ଦୀରେ"]):
            return "hi", 1.0, "explicit_command"
        if any(w in t_low for w in ["speak in odia", "odia please", "ଓଡ଼ିଆରେ"]):
            return "or", 1.0, "explicit_command"
        if any(w in t_low for w in ["sambalpuri", "ସମ୍ବଲପୁରୀ", "ଜୁହାର", "କେନ୍ତା"]):
            return "ory_sambalpuri", 0.98, "dialect_marker"

        # 2. Unicode Script Frequency Analysis
        odia_chars = len(re.findall(r'[\u0B00-\u0B7F]', text))
        hindi_chars = len(re.findall(r'[\u0900-\u097F]', text))
        latin_chars = len(re.findall(r'[a-zA-Z]', text))

        total_chars = max(odia_chars + hindi_chars + latin_chars, 1)

        odia_ratio = odia_chars / total_chars
        hindi_ratio = hindi_chars / total_chars
        latin_ratio = latin_chars / total_chars

        # Sambalpuri lexical markers
        sambalpuri_markers = ["କେନ୍ତା", "ଆମର୍", "ସମକୁଁ", "କରୁନ୍", "ଖାଉନ୍", "ହେନ୍ତା", "ନାଇଁନ"]
        if any(m in text for m in sambalpuri_markers):
            return "ory_sambalpuri", 0.95, "sambalpuri_lexicon"

        if odia_ratio >= 0.45:
            return "or", round(odia_ratio, 2), "odia_script"
        elif hindi_ratio >= 0.45:
            return "hi", round(hindi_ratio, 2), "devanagari_script"
        elif latin_ratio >= 0.60:
            # Check for Romanized Hindi / Hinglish keywords
            hinglish_markers = ["bhaiya", "bhai", "nahi", "chahiye", "kardo", "dalna", "pyaaz"]
            if any(h in t_low for h in hinglish_markers):
                return "hi", 0.85, "hinglish_phonetics"
            return "en", round(latin_ratio, 2), "latin_script"

        # Maintain continuity
        return self.current_lang, 0.70, "continuity_prior"

    def update_session_language(self, text: str) -> Tuple[str, bool, str]:
        """
        Updates session language if a switch is detected.
        Returns: (active_language_code, has_switched, reason)
        """
        detected, conf, reason = self.detect_language(text)
        has_switched = (detected != self.current_lang) and (conf >= 0.80)

        if has_switched:
            self.current_lang = detected

        return self.current_lang, has_switched, reason

    def get_acoustic_routing_params(self, gender: str = "female") -> Dict[str, Any]:
        """
        Returns MultiCondMatcha conditioning parameters for the active language.
        """
        prof = LANG_PROFILES.get(self.current_lang, LANG_PROFILES["or"])
        spk_row = prof["default_female_row"] if gender == "female" else prof["default_male_row"]
        return {
            "lang_code": self.current_lang,
            "lang_name": prof["name"],
            "lang_id": prof["lang_id"],
            "spk_row": spk_row,
            "gender": gender,
            "sample_rate": prof["sample_rate"]
        }

