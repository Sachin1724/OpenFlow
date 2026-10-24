import time
import threading
import ctypes
from typing import Callable, Optional
from pynput import keyboard

user32 = ctypes.windll.user32

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_SPACE = 0x20


class GlobalHotkeyManager:
    """
    Robust Global Hotkey & Push-to-Talk Manager.
    Uses Win32 GetAsyncKeyState for modifier combinations (e.g. Ctrl+Shift)
    to ensure 100% instant press and release detection without dropped OS events.
    """
    def __init__(
        self,
        hotkey_str: str = "ctrl+shift",
        mode: str = "push_to_talk",
        on_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
    ):
        self.hotkey_str = hotkey_str.lower().strip()
        self.mode = mode  # "push_to_talk" or "toggle"
        self.on_start = on_start
        self.on_stop = on_stop

        self._listener: Optional[keyboard.Listener] = None
        self._poll_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._is_active = False
        self._current_keys = set()
        self._lock = threading.Lock()

    def update_config(self, hotkey_str: str, mode: str):
        self.stop()
        self.hotkey_str = hotkey_str.lower().strip()
        self.mode = mode
        self.start()

    def _is_modifier_combo(self) -> bool:
        parts = set(p.strip() for p in self.hotkey_str.split("+"))
        return parts.issubset({"ctrl", "shift", "alt"})

    def _check_async_keys(self) -> bool:
        """Direct Win32 hardware key-state check."""
        parts = [p.strip() for p in self.hotkey_str.split("+")]
        for p in parts:
            if p == "ctrl" and not (user32.GetAsyncKeyState(VK_CONTROL) & 0x8000):
                return False
            elif p == "shift" and not (user32.GetAsyncKeyState(VK_SHIFT) & 0x8000):
                return False
            elif p == "alt" and not (user32.GetAsyncKeyState(VK_MENU) & 0x8000):
                return False
        return True

    def _poll_loop(self):
        """Ultra low-latency polling loop for modifier hotkeys like Ctrl+Shift."""
        was_down = False
        while self._is_running:
            is_down = self._check_async_keys()

            if is_down and not was_down:
                was_down = True
                if self.mode == "push_to_talk":
                    if not self._is_active:
                        self._is_active = True
                        if self.on_start:
                            threading.Thread(target=self.on_start, daemon=True).start()
                else:  # toggle
                    self._is_active = not self._is_active
                    cb = self.on_start if self._is_active else self.on_stop
                    if cb:
                        threading.Thread(target=cb, daemon=True).start()

            elif not is_down and was_down:
                was_down = False
                if self.mode == "push_to_talk" and self._is_active:
                    self._is_active = False
                    if self.on_stop:
                        threading.Thread(target=self.on_stop, daemon=True).start()

            time.sleep(0.015)  # 15ms interval = ~66Hz, unnoticeable CPU load (<0.01%)

    def _normalize_key(self, key) -> str:
        if isinstance(key, keyboard.Key):
            return key.name.lower()
        elif hasattr(key, "char") and key.char:
            return key.char.lower()
        return str(key).lower()

    def _matches_pynput(self) -> bool:
        parts = [p.strip() for p in self.hotkey_str.split("+")]
        for p in parts:
            if p == "ctrl" and not any(k.startswith("ctrl") for k in self._current_keys):
                return False
            elif p == "alt" and not any(k.startswith("alt") for k in self._current_keys):
                return False
            elif p == "shift" and not any(k.startswith("shift") for k in self._current_keys):
                return False
            elif p not in ["ctrl", "alt", "shift"] and p not in self._current_keys:
                return False
        return True

    def _on_press(self, key):
        name = self._normalize_key(key)
        with self._lock:
            self._current_keys.add(name)
            if self._matches_pynput():
                if self.mode == "push_to_talk":
                    if not self._is_active:
                        self._is_active = True
                        if self.on_start:
                            threading.Thread(target=self.on_start, daemon=True).start()
                else:  # toggle
                    self._is_active = not self._is_active
                    cb = self.on_start if self._is_active else self.on_stop
                    if cb:
                        threading.Thread(target=cb, daemon=True).start()

    def _on_release(self, key):
        name = self._normalize_key(key)
        with self._lock:
            if self.mode == "push_to_talk" and self._is_active:
                parts = [p.strip() for p in self.hotkey_str.split("+")]
                if (
                    name in parts
                    or (name.startswith("ctrl") and "ctrl" in parts)
                    or (name.startswith("shift") and "shift" in parts)
                    or (name.startswith("alt") and "alt" in parts)
                ):
                    self._is_active = False
                    if self.on_stop:
                        threading.Thread(target=self.on_stop, daemon=True).start()
            self._current_keys.discard(name)

    def start(self):
        self._is_running = True
        self._is_active = False

        if self._is_modifier_combo():
            # For Ctrl+Shift, use high-precision polling loop
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()
        else:
            # For alphanumeric hotkeys like F8 or Ctrl+Space, use pynput hook
            self._current_keys.clear()
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            )
            self._listener.daemon = True
            self._listener.start()

    def stop(self):
        self._is_running = False
        self._is_active = False
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
        self._current_keys.clear()
        t = getattr(self, "_poll_thread", None)
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=0.5)  # restart must not leave two poll loops
