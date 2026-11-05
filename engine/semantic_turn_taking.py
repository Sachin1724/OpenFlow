"""
semantic_turn_taking.py — Intelligent Odia Conversational Turn-Taking & Clause Analyzer
======================================================================================
Solves the two biggest voice-to-voice problems:
1. "Don't Cut Me Off": Detects incomplete syntactic thoughts so AI waits for user to finish thinking.
2. "Don't Stop When I Nod": Ignores short user backchannels ("ହଁ", "ଆଚ୍ଛା") while AI is speaking.
"""

from typing import Dict, Any, Tuple

# Words that indicate the user is mid-thought and holding the conversational floor
INCOMPLETE_CONJUNCTIONS = {
    "ଏବଂ", "ଆଉ", "କିନ୍ତୁ", "ଯଦି", "କାରଣ", "ତେଣୁ", "କିମ୍ବା", "ବା", "ଯେମିତି", 
    "ଯାହା", "ଯେଉଁଠି", "ତଥାପି", "ଅଥବା", "ମାନେ", "ଯେ", "ବୋଲି"
}

INCOMPLETE_POSTPOSITIONS = {
    "ର", "ରେ", "କୁ", "ଙ୍କୁ", "ପାଇଁ", "ଉପରେ", "ତଳେ", "ସହିତ", "ଦ୍ୱାରା", "ପାଖରେ", "ଭିତରେ"
}

# Short affirmations users utter while listening to an assistant (should NOT cause barge-in)
USER_BACKCHANNEL_TOKENS = {
    "ହଁ", "ହଁହଁ", "ହୁଁ", "ଆଚ୍ଛା", "ଠିକ୍", "ହଁଜ୍ଞା", "ହଁ ଆଜ୍ଞା", "ଠିକ୍ ଅଛି", "କୁହନ୍ତୁ", "ବୁଝିଲି", "ଶୁଣୁଛି"
}


class SemanticTurnTaker:
    """Evaluates conversational flow, clause completeness, and backchannels for Odia dialogue."""

    def evaluate_pause(self, current_transcript: str) -> Dict[str, Any]:
        """
        Evaluates whether an observed pause in user speech is a genuine sentence completion
        or a mid-utterance cognitive pause where the AI should wait patiently.
        """
        text = current_transcript.strip()
        if not text:
            return {"action": "WAIT_USER", "reason": "empty", "timeout_ms": 1500}

        tokens = text.split()
        last_word = tokens[-1]

        # 1. Trailing conjunction or connector (e.g. "ମୁଁ ଯାଇଥିଲି ଆଉ...")
        if last_word in INCOMPLETE_CONJUNCTIONS:
            return {
                "action": "WAIT_USER",
                "reason": f"trailing_conjunction: '{last_word}'",
                "timeout_ms": 1400,
                "is_complete": False
            }

        # 2. Trailing postposition (e.g. "ସେହି ଘର ର...")
        if last_word in INCOMPLETE_POSTPOSITIONS:
            return {
                "action": "WAIT_USER",
                "reason": f"trailing_postposition: '{last_word}'",
                "timeout_ms": 1200,
                "is_complete": False
            }

        # 3. Trailing comma or hesitation ellipsis
        if text.endswith((",", "...", "…", "-")):
            return {
                "action": "WAIT_USER",
                "reason": "trailing_punctuation_pause",
                "timeout_ms": 1100,
                "is_complete": False
            }

        # 4. Syntactically complete sentence
        return {
            "action": "CLAIM_TURN",
            "reason": "syntactically_complete",
            "timeout_ms": 350,
            "is_complete": True
        }

    def is_user_backchannel_during_ai_speech(self, user_utterance: str, duration_sec: float) -> Tuple[bool, str]:
        """
        Checks if speech detected while AI is speaking is simply an audio nod ("ହଁ", "ଆଚ୍ଛା").
        Returns (is_backchannel, reason). If True, AI continues speaking without interruption.
        """
        clean = user_utterance.strip().replace("।", "").replace(".", "").replace("!", "")
        tokens = clean.split()

        # If more than 3 words or lasting > 1.2s, treat as potential genuine interruption (barge-in)
        if len(tokens) > 3 or duration_sec > 1.2:
            return False, "extended_utterance_barge_in"

        # Check if all tokens are listening backchannels
        if all(tok in USER_BACKCHANNEL_TOKENS for tok in tokens):
            return True, f"user_backchannel: '{clean}'"

        # Check single known backchannel
        if clean in USER_BACKCHANNEL_TOKENS:
            return True, f"user_backchannel: '{clean}'"

        return False, "genuine_interruption"
