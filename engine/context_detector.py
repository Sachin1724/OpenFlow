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
    (("code", "code.exe", "cursor", "windsurf", "devenv", "idea64", "pycharm", "clion",
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
    CAT_CHAT:      "smart_clean",
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
            PROCESS_QI = 0x0400  # PROCESS_QUERY_INFORMATION
            h = kernel32.OpenProcess(PROCESS_QI, False, pid.value)
            if h:
                buf2 = ctypes.create_unicode_buffer(260)
                psapi = ctypes.windll.psapi
                psapi.GetModuleBaseNameW(h, None, buf2, 260)
                kernel32.CloseHandle(h)
                proc = buf2.value.strip() or "unknown"

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

# Tech terms always useful regardless of context
_BASE_VOCAB = (
    "OpenFlow", "GitHub", "PyTorch", "CUDA", "API", "SQL", "JSON",
    "TypeScript", "JavaScript", "Python", "Rust", "React", "Node.js",
    "VS Code", "git", "npm", "pip", "Docker", "Kubernetes",
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
    context: AppContext,
    custom_vocab: list[str] | None = None,
    language: str = "en",
) -> str | None:
    """
    Build the Whisper initial_prompt string from context + user vocab.
    Returns None for non-English languages unless we have a specific hint.
    """
    # For Odia / pure Hindi, don't inject an English prompt — it biases script.
    if language in ("or", "hi", "bn", "ta", "te", "ml", "kn", "gu", "mr", "pa"):
        return None

    parts: list[str] = []

    # 1. Instruction prefix based on context
    if context["category"] == CAT_DEVELOPER:
        parts.append(
            "Technical programming dictation with proper punctuation. "
            "Use camelCase, snake_case, and exact symbol names as spoken."
        )
    elif context["category"] == CAT_EMAIL:
        parts.append(
            "Professional email dictation. Use formal punctuation, "
            "paragraph breaks, and proper salutations."
        )
    elif language in ("hinglish", "auto") and context["category"] == CAT_CHAT:
        parts.append(
            "Casual Hinglish conversation in natural Latin/Roman script. "
            "Mix Hindi and English naturally with proper punctuation."
        )
    else:
        parts.append("Use standard punctuation, commas, periods, and capitalization.")

    # 2. Vocabulary bias — custom user terms first (highest priority)
    vocab: list[str] = []
    if custom_vocab:
        # Deduplicate preserving order, max 40 user terms
        seen: set[str] = set()
        for v in custom_vocab:
            if v not in seen:
                vocab.append(v)
                seen.add(v)
            if len(vocab) >= 40:
                break

    # Then add base + category vocab (only what fits in 200 chars)
    vocab += [v for v in _BASE_VOCAB if v not in vocab]
    vocab += [v for v in _CATEGORY_VOCAB.get(context["category"], ()) if v not in vocab]

    # Join, truncate to ~220 chars to keep prompt token budget small
    vocab_str = ", ".join(vocab)
    if len(vocab_str) > 220:
        vocab_str = vocab_str[:220].rsplit(",", 1)[0]

    if vocab_str:
        parts.append(f"Glossary: {vocab_str}.")

    return " ".join(parts)
