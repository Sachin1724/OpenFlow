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
    "tone_preset": "smart_clean",        # smart_clean, developer, email, bullets, verbatim
    "injection_method": "clipboard",     # "clipboard" (instant Ctrl+V) or "type" (direct Unicode typing)
    "restore_clipboard": True,           # Restore user clipboard after paste
    "sound_feedback": True,              # Play subtle audio chimes
    "show_floating_pill": True,          # Show floating minimal capsule
    "input_device_index": None,          # None = system default
    "language": "en",
    "setup_done": False,                 # first-run model download completed
    "autostart": False,                  # launch at Windows sign-in
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
