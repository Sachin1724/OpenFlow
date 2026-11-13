"""
entity_clarification.py — Proactive Entity Clarification & Spelling Loops
========================================================================
Implements Fish Audio-style proactive verification for proper nouns, names,
and landmark addresses in Odisha when ASR acoustic confidence dips below 88%.

Examples:
- Customer says: "My name is Shijia" -> MIRA asks: "Is that SHIJIA like S-H-I-J-I-A... or S-H-I-J-A?"
- Customer says: "ମଲ୍ଲିକ ବାବୁ" -> MIRA asks: "କ୍ଷମା କରିବେ, ନାମଟି କ'ଣ 'ମଲ୍ଲିକ' ନା 'ମହାନ୍ତି' ?"
- Customer says: "ନୟାପଲ୍ଲୀ" -> MIRA clarifies landmark: "ଆପଣଙ୍କ ଠିକଣା 'ନୟାପଲ୍ଲୀ ବ୍ରିଟ୍ କଲୋନୀ' ନା 'ନୂଆପଲ୍ଲୀ' ?"
"""

import re
from typing import Dict, Any, List, Optional, Tuple


# Common ambiguous phonetic confusion clusters in Odisha
ODISHA_NAME_CONFUSIONS = {
    "mallick": ["Mallick", "Mohanty", "Malla"],
    "mohanty": ["Mohanty", "Mallick", "Mahapatra"],
    "jena": ["Jena", "Behera", "Nayak"],
    "routray": ["Routray", "Rout", "Roy"],
    "patnaik": ["Patnaik", "Panda", "Panigrahi"],
    "shijia": ["S-H-I-J-I-A", "S-H-I-J-A"]
}

ODISHA_LANDMARK_CONFUSIONS = {
    "nayapalli": ["Nayapalli (ନୟାପଲ୍ଲୀ)", "Nuapalli (ନୂଆପଲ୍ଲୀ)"],
    "saheed_nagar": ["Saheed Nagar (ସହିଦ ନଗର)", "Satya Nagar (ସତ୍ୟ ନଗର)"],
    "bput": ["BPUT Mahanadi Hall", "BPUT Brahmani Hall", "BPUT Academic Block"],
    "master_canteen": ["Master Canteen Square", "Railway Station Road"]
}


class EntityClarificationLoop:
    def __init__(self, confidence_threshold: float = 0.88):
        self.threshold = confidence_threshold
        self.pending_clarification: Optional[Dict[str, Any]] = None

    def evaluate_entity(
        self,
        entity_type: str,
        extracted_value: str,
        acoustic_confidence: float
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """
        Evaluates whether an extracted entity requires proactive clarification.
        Returns: (needs_clarification, prompt_odia, clarification_context)
        """
        val_clean = extracted_value.strip().lower()

        # Check for phonetic confusion matches or sub-threshold confidence
        if acoustic_confidence >= self.threshold:
            # High confidence, no clarification needed
            return False, None, None

        # Build proactive clarification options
        candidates = []
        for key, alternatives in ODISHA_NAME_CONFUSIONS.items():
            if key in val_clean:
                candidates = alternatives
                break

        if not candidates and entity_type == "address":
            for key, alternatives in ODISHA_LANDMARK_CONFUSIONS.items():
                if key in val_clean:
                    candidates = alternatives
                    break

        if not candidates:
            # Generic spelling breakdown clarification
            spelled = "-".join(list(extracted_value.upper()))
            candidates = [extracted_value.capitalize(), f"{spelled} (spelled out)"]

        # Formulate proactive Odia / English disambiguation prompt
        if entity_type == "customer_name":
            if "s-h-i-j" in candidates[0].lower():
                prompt = f"Is that {extracted_value.upper()} like {candidates[0]}... or {candidates[1]}?"
            else:
                c1, c2 = candidates[0], candidates[1] if len(candidates) > 1 else candidates[0]
                prompt = f"କ୍ଷମା କରିବେ, ନାମଟି କ'ଣ '{c1}' ନା '{c2}' ? ଦୟାକରି ଥରେ ସ୍ପଷ୍ଟ କରନ୍ତୁ ।"
        elif entity_type == "address":
            c1, c2 = candidates[0], candidates[1] if len(candidates) > 1 else candidates[0]
            prompt = f"ଆପଣଙ୍କ ଡେଲିଭରୀ ଠିକଣା କ'ଣ '{c1}' ନା '{c2}' ?"
        else:
            prompt = f"ଦୟାକରି ଆପଣଙ୍କ {entity_type} ଥରେ ସ୍ପଷ୍ଟ ଭାବେ କହିବେ କି ?"

        ctx = {
            "entity_type": entity_type,
            "original_value": extracted_value,
            "confidence": round(acoustic_confidence, 3),
            "candidates": candidates,
            "prompt": prompt
        }
        self.pending_clarification = ctx
        return True, prompt, ctx

    def resolve_clarification(self, user_reply: str) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Processes user's resolution to a pending clarification.
        Returns: (is_resolved, resolved_value, response_meta)
        """
        if not self.pending_clarification:
            return True, user_reply.strip(), {"status": "no_pending_clarification"}

        ctx = self.pending_clarification
        reply_low = user_reply.lower().strip()
        candidates = ctx["candidates"]

        resolved = candidates[0]
        # Match user preference
        for c in candidates:
            clean_c = re.sub(r'[^a-zA-Z0-9\u0B00-\u0B7F]', '', c).lower()
            clean_r = re.sub(r'[^a-zA-Z0-9\u0B00-\u0B7F]', '', reply_low)
            if clean_c in clean_r or clean_r in clean_c:
                resolved = c
                break

        if "second" in reply_low or "ଦୁଇ" in reply_low or "ପର" in reply_low:
            resolved = candidates[1] if len(candidates) > 1 else candidates[0]
        elif "first" in reply_low or "ଏକ" in reply_low or "ପ୍ରଥମ" in reply_low:
            resolved = candidates[0]

        # Clean display
        resolved_clean = re.sub(r'\(.*?\)', '', resolved).strip()
        self.pending_clarification = None

        confirm_msg = f"ଧନ୍ୟବାଦ, ମୁଁ '{resolved_clean}' ରେକର୍ଡ କରିନେଲି ।"
        return True, resolved_clean, {
            "status": "resolved",
            "entity_type": ctx["entity_type"],
            "resolved_value": resolved_clean,
            "confirm_odia": confirm_msg
        }

