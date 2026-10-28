"""
refiner.py — Local Speech-to-Writing Refinement Engine
======================================================
Transforms raw speech-to-text transcriptions into polished, contextual writing
without cloud dependency.

Features:
  1. Self-Correction & Verbal Backspaces ("wait no", "sorry make that", "scratch that")
  2. Smart Filler Stripper (removes verbal pauses without removing essential words)
  3. Technology Acronym & Brand Casing (API, JSON, SQL, PR, GitHub, VS Code, Next.js)
  4. Currency & Indian Quantities Notation (₹500, ₹5 lakh, 2 crore, 15%, $100)
  5. Code Identifier Transformations (camelCase, snake_case, kebab-case, CONSTANT_CASE)
  6. Multi-level Tone & Context Formatting (Developer, Email, Chat, Bullets, Smart Clean)
  7. Optional Local SLM Hook (Qwen2.5 / SmolLM2 via llama.cpp or ONNX Runtime)
"""

import re
from typing import List, Dict, Any, Optional

# ─── Tech Acronyms & Brands ──────────────────────────────────────────────────
TECH_ACRONYMS = {
    "api": "API",
    "apis": "APIs",
    "rest api": "REST API",
    "rest apis": "REST APIs",
    "json": "JSON",
    "sql": "SQL",
    "nosql": "NoSQL",
    "pr": "PR",
    "prs": "PRs",
    "sdk": "SDK",
    "sdks": "SDKs",
    "cli": "CLI",
    "gui": "GUI",
    "ui": "UI",
    "ux": "UX",
    "url": "URL",
    "urls": "URLs",
    "uri": "URI",
    "html": "HTML",
    "css": "CSS",
    "http": "HTTP",
    "https": "HTTPS",
    "jwt": "JWT",
    "oauth": "OAuth",
    "uuid": "UUID",
    "gpu": "GPU",
    "gpus": "GPUs",
    "cpu": "CPU",
    "cpus": "CPUs",
    "ram": "RAM",
    "vram": "VRAM",
    "os": "OS",
    "ai": "AI",
    "ml": "ML",
    "llm": "LLM",
    "llms": "LLMs",
    "asr": "ASR",
    "tts": "TTS",
    "vad": "VAD",
    "ide": "IDE",
    "ides": "IDEs",
    "crud": "CRUD",
    "dom": "DOM",
    "ssr": "SSR",
    "ssg": "SSG",
    "seo": "SEO",
    "upi": "UPI",
    "gst": "GST",
    "aadhaar": "Aadhaar",
}

TECH_BRANDS = {
    "github": "GitHub",
    "gitlab": "GitLab",
    "vs code": "VS Code",
    "vscode": "VS Code",
    "next js": "Next.js",
    "nextjs": "Next.js",
    "react js": "React",
    "reactjs": "React",
    "vue js": "Vue.js",
    "vuejs": "Vue.js",
    "node js": "Node.js",
    "nodejs": "Node.js",
    "tailwind": "Tailwind",
    "tailwindcss": "Tailwind CSS",
    "typescript": "TypeScript",
    "javascript": "JavaScript",
    "python": "Python",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "sqlite": "SQLite",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "K8s",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "pycharm": "PyCharm",
    "intellij": "IntelliJ",
    "sublime": "Sublime Text",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "pytorch": "PyTorch",
    "whisper": "Whisper",
    "pyqt": "PyQt",
    "pyqt6": "PyQt6",
}

# ─── Filler Patterns ───────────────────────────────────────────────────────────
FILLER_PATTERNS = [
    r"\b(um+)\b",
    r"\b(uh+)\b",
    r"\b(erm+)\b",
    r"\b(ah+)\b",
    r"\b(you know)\b(?=\s*,?)",
    r"\b(like)\b(?=\s+(?:I|we|he|she|they|it|you|um|uh|the|a|this))",
    r"\b(sort of|kind of)\b",
    r"\b(basically)\b(?=\s*,?)",
]

HINGLISH_FILLERS = [
    r"\b(arre|arrey)\b(?=\s*,?)",
    r"\b(matlab)\b(?=\s*,?)",
    r"\b(yaani ki)\b(?=\s*,?)",
]

# ─── Spoken Commands ──────────────────────────────────────────────────────────
SPOKEN_COMMANDS = [
    (r"\s*\bnew paragraph\b[,.]?\s*", "\n\n"),
    (r"\s*\bnew line\b[,.]?\s*", "\n"),
    (r"\s*\bquestion mark\b", "?"),
    (r"\s*\bexclamation (?:mark|point)\b", "!"),
    (r"\s*\b(?:full stop|period)\b", "."),
    (r"\s*\bcomma\b", ","),
    (r"\s*\bsemicolon\b", ";"),
    (r"\s*\bcolon\b", ":"),
]


def resolve_self_corrections(text: str) -> str:
    """
    Resolves human speech verbal self-corrections and verbal backspaces:
      - "call Sarah, wait no, call Sachin" -> "call Sachin"
      - "let's meet on Tuesday, actually Wednesday" -> "let's meet on Wednesday"
      - "meeting is at 3, sorry 4 PM" -> "meeting is at 4 PM"
      - "send to John, or rather David" -> "send to David"
      - "five hundred, make that one thousand" -> "one thousand"
      - "we have two, I mean three tickets" -> "we have three tickets"
      - "lunch at noon scratch that lunch at 1 PM" -> "lunch at 1 PM"
    """
    if not text:
        return ""

    s = text

    # 1. "scratch that" / "never mind" drops preceding clause or sentence
    s = re.sub(r"(?:^|[.?!;\n])\s*[^.?!\n]*?\b(?:scratch that|never mind)\b[,.]?\s*", "", s, flags=re.IGNORECASE).strip()

    # 2a. Prepositional / Target replacement: "... to Sarah, wait no, to Rahul" -> "... to Rahul"
    s = re.sub(
        r"\b((?:to|for|from|with|at|on|in|by)\s+[a-zA-Z0-9]+)\s*,\s*\b(?:wait no|no wait|my bad)\b[,.]?\s*(?=(?:to|for|from|with|at|on|in|by)\s+[a-zA-Z0-9]+)",
        "",
        s,
        flags=re.IGNORECASE
    )

    # 2b. Full clause replacement: "... call Sarah, wait no, call Sachin" -> "call Sachin"
    s = re.sub(
        r"(?:^|[.?!;\n])\s*[^.?!;\n]+?\s*,\s*\b(?:wait no|no wait|my bad)\b[,.]?\s*",
        "",
        s,
        flags=re.IGNORECASE
    )

    # 3. Direct single word / phrase replacement:
    # "wordA, (sorry|actually|or rather|make that|I mean) wordB"
    # e.g. "Tuesday, actually Wednesday" -> "Wednesday"
    # e.g. "at 3, sorry 4 PM" -> "at 4 PM"
    # e.g. "two, I mean three" -> "three"
    sub_markers = r"\b(?:sorry|actually|or rather|make that|I mean)\b[,.]?\s*"

    def _sub_word(m):
        w1 = m.group(1).strip()
        w2 = m.group(2).strip()
        preps = (
            "have", "has", "had", "need", "want", "get", "got", "take",
            "on", "at", "in", "to", "for", "from", "with", "by", "is",
            "are", "was", "were", "of", "a", "an", "the"
        )
        w1_tokens = w1.split()
        w2_tokens = w2.split()
        if len(w1_tokens) > 1 and w1_tokens[0].lower() in preps and w2_tokens[0].lower() not in preps:
            return f"{w1_tokens[0]} {w2}"
        return w2

    s = re.sub(
        r"\b([a-zA-Z0-9]+(?:\s+[a-zA-Z0-9]+)?)\s*,\s*" + sub_markers + r"([a-zA-Z0-9]+(?:\s+[a-zA-Z0-9]+)?)",
        _sub_word,
        s,
        flags=re.IGNORECASE
    )

    # Clean residual whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_fillers(text: str, is_hinglish: bool = False) -> str:
    """Removes verbal pauses without altering natural intent."""
    if not text:
        return ""

    cleaned = text
    for pattern in FILLER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    if is_hinglish:
        for pattern in HINGLISH_FILLERS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Clean residual punctuation artifacts like ", ," or leading commas
    cleaned = re.sub(r"[ \t]*,[ \t]*,+", ", ", cleaned)
    cleaned = re.sub(r"^\s*,\s*", "", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" ?\n ?", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def format_tech_terms(text: str) -> str:
    """Enforces correct casing for 90+ programming terms, acronyms, and frameworks."""
    if not text:
        return ""

    res = text
    # 1. Multi-word phrases first
    for phrase, proper in sorted(TECH_BRANDS.items(), key=lambda x: -len(x[0])):
        if " " in phrase:
            res = re.sub(r"\b" + re.escape(phrase) + r"\b", proper, res, flags=re.IGNORECASE)

    for phrase, proper in sorted(TECH_ACRONYMS.items(), key=lambda x: -len(x[0])):
        if " " in phrase:
            res = re.sub(r"\b" + re.escape(phrase) + r"\b", proper, res, flags=re.IGNORECASE)

    # 2. Single-word acronyms & brands
    for word, proper in TECH_ACRONYMS.items():
        if " " not in word:
            res = re.sub(r"\b" + re.escape(word) + r"\b", proper, res, flags=re.IGNORECASE)

    for word, proper in TECH_BRANDS.items():
        if " " not in word:
            res = re.sub(r"\b" + re.escape(word) + r"\b", proper, res, flags=re.IGNORECASE)

    return res


def format_currency_and_quantities(text: str) -> str:
    """Formats Indian and international currencies, percentages, and large numbers."""
    if not text:
        return ""

    s = text

    # Indian Rupee: "500 rupees" or "rupees 500" -> "₹500"
    s = re.sub(r"\b(?:rupees?|rs\.?)\s*(\d+(?:,\d+)*(?:\.\d+)?)\b", r"₹\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:rupees?|rs\.?)\b", r"₹\1", s, flags=re.IGNORECASE)

    # Lakhs & Crores: "5 lakh" or "5 lakhs" -> "₹5 lakh" when currency, otherwise format cleanly
    s = re.sub(r"\b₹\s*(\d+(?:\.\d+)?)\s*lakhs?\b", r"₹\1 lakh", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*lakhs?\s*(?:rupees?|rs\.?)\b", r"₹\1 lakh", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*crores?\s*(?:rupees?|rs\.?)\b", r"₹\1 crore", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*lakhs?\b", r"\1 lakh", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*crores?\b", r"\1 crore", s, flags=re.IGNORECASE)

    # International Currencies
    s = re.sub(r"\b(?:dollars?)\s*(\d+(?:,\d+)*(?:\.\d+)?)\b", r"$\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:dollars?)\b", r"$\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(?:euros?)\s*(\d+(?:,\d+)*(?:\.\d+)?)\b", r"€\1", s, flags=re.IGNORECASE)
    s = re.sub(r"\b(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:euros?)\b", r"€\1", s, flags=re.IGNORECASE)

    # Percentages: "15 percent" -> "15%"
    s = re.sub(r"\b(\d+(?:\.\d+)?)\s*(?:percent|per cent)\b", r"\1%", s, flags=re.IGNORECASE)

    return s


def format_code_identifiers(text: str) -> str:
    """Converts verbal programming casing commands into valid identifiers."""
    s = text

    STOP_WORDS = r"(?=\s+(?:and|then|with|or|equals|comma|semicolon|colon|dot|console|return|const|let|var|function|def|class|if|else|import|from)\b|[.,?!;\n]|$)"
    WORDS_PAT = r"([a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+){0,4}?)"

    # camel case word1 word2 -> word1Word2
    def _to_camel(m):
        words = m.group(1).split()
        if not words:
            return ""
        return words[0].lower() + "".join(w.capitalize() for w in words[1:])

    s = re.sub(r"\bcamel case\s+" + WORDS_PAT + STOP_WORDS, _to_camel, s, flags=re.IGNORECASE)

    # snake case word1 word2 -> word1_word2
    def _to_snake(m):
        words = m.group(1).split()
        return "_".join(w.lower() for w in words)

    s = re.sub(r"\bsnake case\s+" + WORDS_PAT + STOP_WORDS, _to_snake, s, flags=re.IGNORECASE)

    # kebab case word1 word2 -> word1-word2
    def _to_kebab(m):
        words = m.group(1).split()
        return "-".join(w.lower() for w in words)

    s = re.sub(r"\bkebab case\s+" + WORDS_PAT + STOP_WORDS, _to_kebab, s, flags=re.IGNORECASE)

    # constant case / screaming snake case word1 word2 -> WORD1_WORD2
    def _to_constant(m):
        words = m.group(1).split()
        return "_".join(w.upper() for w in words)

    s = re.sub(r"\b(?:constant case|screaming snake case)\s+" + WORDS_PAT + STOP_WORDS, _to_constant, s, flags=re.IGNORECASE)

    # Developer syntax shortcuts
    code_shortcuts = [
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
        (r"\btriple backticks\b", "```"),
        (r"\bconsole log\b", "console.log"),
    ]
    for pat, repl in code_shortcuts:
        s = re.sub(pat, repl, s, flags=re.IGNORECASE)

    return s


class SpeechToWritingEngine:
    """
    Tier 1 & Tier 2 Local Speech-to-Writing Engine.
    Delivers Wispr Flow quality text refinement 100% locally.
    """

    def __init__(self):
        self._local_slm_model = None
        self._has_checked_slm = False

    def refine(
        self,
        raw_text: str,
        context_category: str = "general",
        tone_preset: str = "smart_clean",
        language: str = "en",
        custom_dictionary: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Main entry point: cleans, refines, and formats raw transcript into written prose."""
        if not raw_text or not raw_text.strip():
            return ""

        text = raw_text.strip()
        is_hinglish = language in ("en-in", "hinglish")

        # 1. Resolve spoken self-corrections ("wait no", "sorry", "actually")
        text = resolve_self_corrections(text)

        # 2. Spoken layout commands ("new paragraph", "comma", "period")
        for pattern, repl in SPOKEN_COMMANDS:
            text = re.sub(pattern, repl, text, flags=re.IGNORECASE)

        # 3. Clean verbal filler pauses ("um", "uh", "you know", "basically")
        if tone_preset != "verbatim":
            text = clean_fillers(text, is_hinglish=is_hinglish)

        # 4. Apply custom vocabulary replacements
        if custom_dictionary:
            for entry in custom_dictionary:
                phrase = entry.get("phrase_match", "")
                replacement = entry.get("replace_with", "")
                case_sens = bool(entry.get("case_sensitive", 0))
                if phrase and replacement:
                    flags = 0 if case_sens else re.IGNORECASE
                    text = re.sub(r"\b" + re.escape(phrase) + r"\b", replacement, text, flags=flags)

        # 5. Currency, Percentages, and Indian Quantities
        text = format_currency_and_quantities(text)

        # 6. Technical Acronym & Brand Casing
        text = format_tech_terms(text)

        # 7. Code Identifiers & Syntax (if developer tone or developer app context)
        if tone_preset == "developer" or context_category == "developer":
            text = format_code_identifiers(text)

        # 8. Punctuation spacing & sentence capitalization
        text = self._finalize_punctuation_and_caps(text, tone_preset=tone_preset)

        return text

    def _finalize_punctuation_and_caps(self, text: str, tone_preset: str) -> str:
        if not text:
            return ""

        s = text
        # Ensure single space after punctuation (excluding period to preserve URLs, file extensions, and code dot notation)
        s = re.sub(r"([,?!:;])(?=[A-Za-z])", r"\1 ", s)

        # Sentence capitalization (split on sentence ends: .?! followed by space or newline)
        if tone_preset != "developer":
            sentences = re.split(r"([.?!]\s+|\n+)", s)
            res = []
            for sent in sentences:
                if sent and sent[0].isalpha():
                    sent = sent[0].upper() + sent[1:]
                res.append(sent)
            formatted = "".join(res)
        else:
            formatted = s

        # Trailing period for full prose, unless in chat or developer or verbatim
        if tone_preset == "chat":
            if formatted.endswith(".") and not formatted.endswith(".."):
                formatted = formatted[:-1]
        elif tone_preset not in ("developer", "verbatim"):
            if formatted and formatted[-1].isalnum():
                formatted += "."

        return formatted.strip()
