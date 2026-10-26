import re
from typing import List, Dict, Any, Optional

FILLER_WORDS = [
    r"\b(um+)\b",
    r"\b(uh+)\b",
    r"\b(erm+)\b",
    r"\b(ah+)\b",
    r"\b(you know)\b",
    r"\b(like)\b(?=\s+(?:I|we|he|she|they|it|you|um|uh|the|a|this))",
    r"\b(sort of|kind of)\b",
    r"\b(basically)\b(?=\s*,?)",
    r"\b(I mean)\b(?=\s*,?)",
]


class TextFormatter:
    def __init__(self, dictionary_entries: Optional[List[Dict[str, Any]]] = None):
        self.dictionary = dictionary_entries or []

    def set_dictionary(self, entries: List[Dict[str, Any]]):
        self.dictionary = entries

    def format(self, text: str, tone_preset: str = "smart_clean", language: str = "en") -> str:
        if not text or not text.strip():
            return ""

        raw = text.strip()

        # Filler/tone rules are English-only; Whisper already punctuates other languages.
        if tone_preset == "verbatim" or language != "en":
            return self._apply_dictionary(raw)

        cleaned = raw

        # Step 1: Remove filler words
        if tone_preset in ["smart_clean", "developer", "email", "bullets"]:
            for pattern in FILLER_WORDS:
                cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

            # Clean up residual commas and spaces
            cleaned = re.sub(r"\s*,\s*,+", ", ", cleaned)
            cleaned = re.sub(r"^\s*,\s*", "", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Step 2: Custom vocabulary dictionary replacements
        cleaned = self._apply_dictionary(cleaned)

        # Step 3: Preset-specific transformation
        if tone_preset == "developer":
            cleaned = self._format_developer(cleaned)
        elif tone_preset == "email":
            cleaned = self._format_email(cleaned)
        elif tone_preset == "bullets":
            cleaned = self._format_bullets(cleaned)
        else:
            cleaned = self._format_smart_clean(cleaned)

        return cleaned

    def _apply_dictionary(self, text: str) -> str:
        result = text
        for entry in self.dictionary:
            phrase = entry.get("phrase_match", "")
            replacement = entry.get("replace_with", "")
            case_sens = bool(entry.get("case_sensitive", 0))

            if not phrase or not replacement:
                continue

            flags = 0 if case_sens else re.IGNORECASE
            pattern = r"\b" + re.escape(phrase) + r"\b"
            result = re.sub(pattern, replacement, result, flags=flags)
        return result

    def _format_smart_clean(self, text: str) -> str:
        if not text:
            return ""

        # Sentence capitalization
        sentences = re.split(r"([.?!]\s+)", text)
        result = []
        for s in sentences:
            if s and s[0].isalpha():
                s = s[0].upper() + s[1:]
            result.append(s)
        formatted = "".join(result)

        if formatted and formatted[-1].isalnum():
            formatted += "."

        return formatted

    def _format_developer(self, text: str) -> str:
        s = text

        # Syntax substitutions
        substitutions = [
            (r"\bopen parenthesis\b", "("),
            (r"\bclose parenthesis\b", ")"),
            (r"\bopen bracket\b", "["),
            (r"\bclose bracket\b", "]"),
            (r"\bopen brace\b", "{"),
            (r"\bclose brace\b", "}"),
            (r"\bdot ([a-zA-Z0-9_]+)\b", r".\1"),
            (r"\barrows\b|\bfat arrow\b", "=>"),
            (r"\bthin arrow\b", "->"),
            (r"\bequals equals\b|\bdouble equals\b", "=="),
            (r"\btriple equals\b", "==="),
            (r"\bnot equals\b", "!="),
            (r"\bplus equals\b", "+="),
            (r"\bminus equals\b", "-="),
        ]
        for pat, repl in substitutions:
            s = re.sub(pat, repl, s, flags=re.IGNORECASE)

        # "camel case word1 word2" -> word1Word2
        def _to_camel(m):
            words = m.group(1).split()
            if not words:
                return ""
            return words[0].lower() + "".join(w.capitalize() for w in words[1:])

        s = re.sub(r"\bcamel case ([a-zA-Z0-9]+(?:\s+[a-zA-Z0-9]+){1,4})", _to_camel, s, flags=re.IGNORECASE)

        # "snake case word1 word2" -> word1_word2
        def _to_snake(m):
            words = m.group(1).split()
            return "_".join(w.lower() for w in words)

        s = re.sub(r"\bsnake case ([a-zA-Z0-9]+(?:\s+[a-zA-Z0-9]+){1,4})", _to_snake, s, flags=re.IGNORECASE)

        return self._format_smart_clean(s)

    def _format_email(self, text: str) -> str:
        s = self._format_smart_clean(text)

        # Detect greeting
        greeting_match = re.match(r"^(Hi|Hello|Hey|Dear)\s+([A-Z][a-z]+)[,.]?\s*", s, flags=re.IGNORECASE)
        if greeting_match:
            greeting = f"{greeting_match.group(1).capitalize()} {greeting_match.group(2)},\n\n"
            body = s[greeting_match.end():]
        else:
            greeting = ""
            body = s

        # Detect signoff
        signoff_patterns = [
            (r"[,.]?\s*\b(best regards|kind regards|warm regards)[,.]?\s*$", "\n\nBest regards,"),
            (r"[,.]?\s*\b(thanks|thank you)[,.]?\s*$", "\n\nThanks,"),
            (r"[,.]?\s*\b(cheers)[,.]?\s*$", "\n\nCheers,"),
            (r"[,.]?\s*\b(sincerely)[,.]?\s*$", "\n\nSincerely,"),
        ]
        for pat, repl in signoff_patterns:
            if re.search(pat, body, flags=re.IGNORECASE):
                body = re.sub(pat, repl, body, flags=re.IGNORECASE)
                break

        return greeting + body

    def _format_bullets(self, text: str) -> str:
        # Split on list trigger words
        split_pat = r"(?:\b(?:firstly|first|secondly|second|thirdly|third|finally|next|also|additionally|number \d+|point \d+)\b[:,-]?)"
        parts = re.split(split_pat, text, flags=re.IGNORECASE)

        items = [p.strip() for p in parts if p.strip()]
        if len(items) <= 1:
            sentences = [s.strip() for s in re.split(r"[.?!]\s+", text) if s.strip()]
            if len(sentences) > 1:
                items = sentences
            else:
                items = [text.strip()]

        lines = []
        for item in items:
            if item:
                capitalized = item[0].upper() + item[1:]
                if not capitalized.endswith((".", "!", "?")):
                    capitalized += "."
                lines.append(f"• {capitalized}")

        return "\n".join(lines)
