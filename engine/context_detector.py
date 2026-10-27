"""
context_detector.py — Active Window Context Sniffer
====================================================
Detects which app the user is typing into (VS Code, Slack, Word, etc.)
and returns a structured context dict used to:
  1. Build a smarter Whisper initial_prompt (vocabulary biasing)
  2. Auto-select the best tone_preset for the active app
  3. Tag history entries with rich target_app metadata

All lookups are pure Win32 calls — zero network, < 1 ms latency.
Falls back gracefully on non-Windows platforms.
"""

from __future__ import annotations
import os
import sys
from typing import TypedDict

# ─── App category constants ───────────────────────────────────────────────────
CAT_DEVELOPER  = "developer"   # IDEs, terminals, code editors
CAT_CHAT       = "chat"        # Slack, Teams, WhatsApp, Discord, Telegram
CAT_DOCUMENT   = "document"    # Word, Notion, Obsidian, Typora, Notepad
CAT_BROWSER    = "browser"     # Chrome, Firefox, Edge
CAT_EMAIL      = "email"       # Outlook, Thunderbird, Gmail (browser special case)
CAT_GENERAL    = "general"     # Everything else

# Map of process-name substrings → category
_PROCESS_MAP: list[tuple[tuple[str, ...], str]] = [
    # Developer tools
    (("code", "code.exe", "cursor", "windsurf", "antigravity", "devenv", "idea64", "pycharm", "clion",
      "webstorm", "intellij", "sublime_text", "atom", "notepad++", "neovide", "nvim",
      "vim", "windowsterminal", "wt", "powershell", "pwsh", "cmd", "conhost", "alacritty",
      "hyper", "wezterm", "gitbash", "git-bash", "bash", "zsh"), CAT_DEVELOPER),

    # Chat / messaging
    (("slack", "teams", "msteams", "discord", "telegram", "whatsapp", "signal",
      "zoom", "skype", "element", "zulip", "rocketchat"), CAT_CHAT),

    # Email clients
    (("outlook", "thunderbird", "mailspring", "postbox", "evolution"), CAT_EMAIL),

    # Browsers (title heuristic used later for Gmail / Outlook web)
    (("chrome", "firefox", "msedge", "edge", "brave", "opera", "vivaldi", "safari",
      "chromium", "arc"), CAT_BROWSER),

    # Document editors / note-taking
    (("winword", "libreoffice", "soffice", "notion", "obsidian", "typora", "logseq",
      "roam", "craft", "bear", "notepad", "write", "wordpad", "focuswriter",
      "onenote"), CAT_DOCUMENT),
]

# Window title substrings that upgrade a BROWSER window to a better category
_TITLE_EMAIL_HINTS   = ("gmail", "outlook.com", "mail.google", "yahoo mail", "protonmail")
_TITLE_CHAT_HINTS    = ("slack", "discord", "whatsapp web", "telegram web", "teams")
_TITLE_CODE_HINTS    = ("github", "gitlab", "stackoverflow", "docs.python", "mdn web docs",
                        "devdocs", "readthedocs", "huggingface")


class AppContext(TypedDict):
    """Everything the transcription pipeline needs from the current window."""
    process: str        # bare .exe name, lowercased
    title: str          # window title
    category: str       # one of CAT_* constants
    tone_suggestion: str  # suggested tone_preset for this context


def _classify_process(proc: str) -> str:
    proc_l = proc.lower()
    for names, cat in _PROCESS_MAP:
        if any(n in proc_l for n in names):
            return cat
    return CAT_GENERAL


def _refine_browser(title: str) -> str:
    """Use window title to upgrade a generic BROWSER classification."""
    tl = title.lower()
    if any(h in tl for h in _TITLE_EMAIL_HINTS):
        return CAT_EMAIL
    if any(h in tl for h in _TITLE_CHAT_HINTS):
        return CAT_CHAT
    if any(h in tl for h in _TITLE_CODE_HINTS):
        return CAT_DEVELOPER
    return CAT_BROWSER


_TONE_MAP: dict[str, str] = {
    CAT_DEVELOPER: "developer",
    CAT_CHAT:      "chat",
    CAT_EMAIL:     "email",
    CAT_DOCUMENT:  "smart_clean",
    CAT_BROWSER:   "smart_clean",
    CAT_GENERAL:   "smart_clean",
}


def get_active_app_context() -> AppContext:
    """
    Return structured information about the currently focused window.
    Guaranteed never to raise — returns a safe default on any error.
    """
    proc  = "unknown"
    title = ""
    try:
        if sys.platform == "win32":
            import ctypes
            import ctypes.wintypes as wt

            user32 = ctypes.windll.user32
            hwnd   = user32.GetForegroundWindow()

            # Window title
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            title = buf.value.strip()

            # PID → process name
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

            kernel32   = ctypes.windll.kernel32
            # Same call as injector.get_foreground_window: GetModuleBaseNameW also needs
            # PROCESS_VM_READ and silently failed, so every app was "unknown".
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            if h:
                buf2 = ctypes.create_unicode_buffer(1024)
                size = wt.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf2, ctypes.byref(size)):
                    proc = os.path.basename(buf2.value) or "unknown"
                kernel32.CloseHandle(h)

    except Exception:
        pass

    proc_clean = proc.lower().removesuffix(".exe")
    category   = _classify_process(proc_clean)
    if category == CAT_BROWSER:
        category = _refine_browser(title)

    return AppContext(
        process=proc_clean,
        title=title,
        category=category,
        tone_suggestion=_TONE_MAP.get(category, "smart_clean"),
    )


# ─── Prompt builder ──────────────────────────────────────────────────────────

# Tech and developer terms
_BASE_VOCAB = (
    "OpenFlow", "GitHub", "PyTorch", "CUDA", "API", "SQL", "JSON",
    "TypeScript", "JavaScript", "Python", "Rust", "React", "Node.js",
    "VS Code", "git", "npm", "pip", "Docker", "Kubernetes",
)

# Rich automatic Indian English, Odia, Hindi, financial, naming, and conversational lexicon
_INDIAN_AUTO_VOCAB = (
    # Finance, Banking, IDs & Govt
    "lakh", "crore", "rupees", "INR", "paisa", "Aadhaar", "UPI", "PAN", "GST",
    "GPay", "PhonePe", "Paytm", "FASTag", "NEFT", "RTGS",
    # Cities & Tech Hubs
    "Bengaluru", "Bangalore", "Mumbai", "Delhi", "Hyderabad", "Chennai", "Kolkata",
    "Pune", "Ahmedabad", "Noida", "Gurgaon", "Gurugram", "Jaipur", "Bhubaneswar", "Cuttack", "Odisha",
    # Popular Names & Surnames
    "Sachidananda", "Sachin", "Rahul", "Rohit", "Virat", "Priya", "Neha", "Ananya", "Amit",
    "Sharma", "Verma", "Patel", "Singh", "Kumar", "Gupta", "Reddy", "Iyer", "Mehta", "Mishra", "Patnaik", "Mohanty",
    # Common conversational Hinglish & Hindi terms
    "namaste", "jugaad", "yaar", "bhai", "chalo", "accha", "theek", "matlab",
    "karo", "karna", "zaroor", "shukriya", "chai", "samosa",
    "kya", "kyu", "kaise", "kuch", "nahi", "haan", "batao", "suno", "pata", "jalega", "bol", "dekho",
    # Common Odia conversational terms
    "kete", "kan", "kemiti", "kouthi", "kichi", "sabu", "ghare", "aama", "bhala",
    "dhanyabad", "aji", "kalia", "khabar", "bujhila", "katha", "pani", "jiba", "asiba",
)

_CATEGORY_VOCAB: dict[str, tuple[str, ...]] = {
    CAT_DEVELOPER: (
        "function", "variable", "async", "await", "return", "class", "import",
        "export", "const", "let", "try", "catch", "null", "undefined",
        "True", "False", "None", "lambda", "yield", "pytest", "unittest",
        "camelCase", "snake_case", "PascalCase", "README", "TODO", "FIXME",
    ),
    CAT_EMAIL: (
        "Best regards", "Kind regards", "Please find attached", "FYI",
        "RSVP", "CC", "BCC", "follow-up", "action items",
    ),
    CAT_CHAT: (),
    CAT_DOCUMENT: (),
    CAT_BROWSER: (),
    CAT_GENERAL: (),
}


def build_initial_prompt(
    context: AppContext | None = None,
    custom_vocab: list[str] | None = None,
    language: str = "en",
) -> str | None:
    """
    Build the Whisper initial_prompt string from context + user vocab.
    Returns None for non-English languages unless we have a specific hint.
    """
    if language in ("or", "odia"):
        return (
            "Odia and Indian English dictation. Accurately transcribe Odia and English in clean "
            "Latin/Roman script: kete, kan, kemiti, kouthi, kichi, sabu, ghare, aama, bhala, namaskar, "
            "dhanyabad, aji, kalia, bujhila, katha. Never output Urdu or Arabic script."
        )

    if language == "hi":
        return (
            "हिंदी भाषा और हिंग्लिश डिक्टेशन। शुद्ध देवनागरी लिपि या रोमन में लिखें। "
            "सामान्य शब्द: क्या, कैसे, क्यों, कुछ, नहीं, हाँ, ठीक, अच्छा, भाई, यार, मतलब, बताओ, सुनो। "
            "उर्दू या अरबी लिपि का प्रयोग न करें।"
        )

    # For other non-Hindi regional Indic scripts with their own token, let Whisper priors work
    if language in ("bn", "ta", "te", "ml", "kn", "gu", "mr", "pa"):
        return None

    ctx: AppContext = context if isinstance(context, dict) else {
        "process": "",
        "title": "",
        "category": CAT_GENERAL,
        "tone_suggestion": "smart_clean",
    }

    parts: list[str] = []

    # 1. Instruction prefix based on context and language
    if language in ("en-in", "hinglish", "auto"):
        parts.append(
            "Indian English, Hinglish, Hindi, and Odia dictation in natural Latin/Roman script. "
            "Accurately preserve Indian words (kya, kuch, kyu, kaise, nahi, theek, accha, bhai, yaar, kete, kan, kemiti). "
            "Never output Urdu or Arabic script."
        )
    elif ctx["category"] == CAT_DEVELOPER:
        parts.append(
            "Technical programming dictation with proper punctuation. "
            "Use camelCase, snake_case, and exact symbol names as spoken."
        )
    elif ctx["category"] == CAT_EMAIL:
        parts.append(
            "Professional email dictation. Use formal punctuation, "
            "paragraph breaks, and proper salutations."
        )
    elif language in ("hinglish", "auto") and ctx["category"] == CAT_CHAT:
        parts.append(
            "Casual Hinglish conversation in natural Latin/Roman script. "
            "Mix Hindi and English naturally with proper punctuation."
        )
    else:
        parts.append("Use standard punctuation, commas, periods, and capitalization.")

    # 2. Vocabulary bias
    vocab: list[str] = []

    # Custom user terms first (highest priority)
    if custom_vocab:
        seen: set[str] = set()
        for v in custom_vocab:
            if v not in seen:
                vocab.append(v)
                seen.add(v)
            if len(vocab) >= 60:
                break

    # Automatic Indian lexicon when in Indian English or Hinglish mode
    if language in ("en-in", "hinglish", "auto"):
        vocab += [v for v in _INDIAN_AUTO_VOCAB if v not in vocab]

    # Base tech + category vocab
    vocab += [v for v in _BASE_VOCAB if v not in vocab]
    vocab += [v for v in _CATEGORY_VOCAB.get(ctx["category"], ()) if v not in vocab]

    # Join, truncate to ~700 chars (Whisper supports up to 224 prompt tokens)
    vocab_str = ", ".join(vocab)
    if len(vocab_str) > 700:
        vocab_str = vocab_str[:700].rsplit(",", 1)[0]

    if vocab_str:
        parts.append(f"Glossary: {vocab_str}.")

    return " ".join(parts)
