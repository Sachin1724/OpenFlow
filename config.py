import os
import json
from pathlib import Path

DEFAULT_CONFIG = {
    "model_size": "auto",                # auto, tiny, base, small, medium (".en" is added for English)
    "device": "auto",                    # auto (detect), cuda or cpu
    "compute_type": "auto",              # chosen from device: float16 for cuda, int8 for cpu
    "hotkey": "ctrl+shift",              # ctrl+shift (hold to speak, release to write)
    "trigger_mode": "push_to_talk",      # "push_to_talk" (hold while speaking, release to write), "toggle", "auto_silence"
    "auto_write_on_silence": False,      # When in push_to_talk, release writes immediately
    "silence_duration": 1.1,             # Seconds of silence (for auto_silence mode)
    "realtime_preview": True,            # Live partial text in capsule
    "tone_preset": "auto",               # auto (follows the active app), smart_clean, chat, developer, email, bullets, verbatim
    "injection_method": "clipboard",     # "clipboard" (instant Ctrl+V), "typein" (word-by-word effect) or "type" (direct Unicode typing)
    "restore_clipboard": True,           # Restore user clipboard after paste
    "sound_feedback": True,              # Play subtle audio chimes
    "show_floating_pill": True,          # Show floating minimal capsule
    "capsule_style": "compact",          # "standard" (360px full), "compact" (138px Wispr Flow), "micro" (88px minimal)
    "capsule_opacity": 1.0,              # 0.3-1.0, set from Settings
    "hide_capsule_when_idle": False,     # Hide capsule completely when idle (don't show minimized bar on desktop)
    "follow_mouse_screen": True,         # Automatically follow mouse cursor to active display with smooth ease-in/out
    "input_device_index": None,          # None = system default
    "language": "en",
    "setup_done": False,                 # first-run model download completed
    "autostart": False,                  # launch at Windows sign-in
    "voice_edits": False,                # select text + say "make this formal": local Qwen2.5-1.5B rewrites it
    "font_family": "Poppins",
}

CONFIG_DIR = Path.home() / ".openflow"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update(data)
        if merged.get("setup_done") and merged.get("model_size") == "auto":
            # pin once to what is already downloaded so "auto" never fetches a bigger model later
            from .engine import hardware
            merged["model_size"] = hardware.resolve(merged)["model_size"]
            save_config(merged)
        return merged
    except Exception as e:
        print(f"[OpenFlow] Error loading config: {e}")
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print(f"[OpenFlow] Error saving config: {e}")


def get_asset_path(*parts: str) -> str:
    """Resolve an asset file path reliably in both source and frozen PyInstaller modes."""
    import sys
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
        p = os.path.join(base, "assets", *parts)
        if os.path.exists(p):
            return p
        p_sub = os.path.join(base, "openflow", "assets", *parts)
        if os.path.exists(p_sub):
            return p_sub
        return p

    here = os.path.dirname(os.path.abspath(__file__))
    p_here = os.path.join(here, "assets", *parts)
    if os.path.exists(p_here):
        return p_here
    p_parent = os.path.join(os.path.dirname(here), "assets", *parts)
    if os.path.exists(p_parent):
        return p_parent
    return p_here

