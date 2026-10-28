import time
import threading
import ctypes
from typing import Callable, Optional
from pynput import keyboard

user32 = ctypes.windll.user32
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_SPACE = 0x20

VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5


class GlobalHotkeyManager:
    """
    Robust Global Hotkey & Push-to-Talk Manager.
    Combines Win32 GetAsyncKeyState hardware polling (with Left/Right modifier support)
    together with pynput low-level OS hooks for zero missed events across all apps.
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

    @staticmethod
    def _is_vk_down(*vks: int) -> bool:
        for vk in vks:
            val = user32.GetAsyncKeyState(vk)
            if (val & 0x8000) or val < 0:
                return True
        return False

    def _check_async_keys(self) -> bool:
        """Direct Win32 hardware key-state check supporting Left and Right variants."""
        parts = [p.strip() for p in self.hotkey_str.split("+")]
        for p in parts:
            if p == "ctrl" and not self._is_vk_down(VK_CONTROL, VK_LCONTROL, VK_RCONTROL):
                return False
            elif p == "shift" and not self._is_vk_down(VK_SHIFT, VK_LSHIFT, VK_RSHIFT):
                return False
            elif p == "alt" and not self._is_vk_down(VK_MENU, VK_LMENU, VK_RMENU):
                return False
            elif p == "space" and not self._is_vk_down(VK_SPACE):
                return False
        return True

    def _trigger_start(self):
        with self._lock:
            if not self._is_active:
                self._is_active = True
                print(f"[OpenFlow Hotkey] Activated '{self.hotkey_str}' (mode={self.mode})")
                if self.on_start:
                    threading.Thread(target=self.on_start, daemon=True).start()

    def _trigger_stop(self):
        with self._lock:
            if self._is_active:
                self._is_active = False
                print(f"[OpenFlow Hotkey] Deactivated '{self.hotkey_str}'")
                if self.on_stop:
                    threading.Thread(target=self.on_stop, daemon=True).start()

    def _trigger_toggle(self):
        with self._lock:
            self._is_active = not self._is_active
            active = self._is_active
        print(f"[OpenFlow Hotkey] Toggled '{self.hotkey_str}': active={active}")
        cb = self.on_start if active else self.on_stop
        if cb:
            threading.Thread(target=cb, daemon=True).start()

    def _poll_loop(self):
        """Ultra low-latency polling loop for modifier hotkeys like Ctrl+Shift."""
        was_down = False
        while self._is_running:
            is_down = self._check_async_keys()

            if is_down and not was_down:
                was_down = True
                if self.mode == "push_to_talk":
                    self._trigger_start()
                else:
                    self._trigger_toggle()

            elif not is_down and was_down:
                was_down = False
                if self.mode == "push_to_talk":
                    self._trigger_stop()

            time.sleep(0.015)  # 15ms interval = ~66Hz, unnoticeable CPU load (<0.01%)

    def _normalize_key(self, key) -> str:
        if isinstance(key, keyboard.Key):
            return key.name.lower()
        vk = getattr(key, "vk", None)
        if vk and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):  # Ctrl+A arrives as char '\x01'
            return chr(vk).lower()
        if hasattr(key, "char") and key.char:
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
            matches = self._matches_pynput()
        if matches:
            if self.mode == "push_to_talk":
                self._trigger_start()
            else:
                self._trigger_toggle()

    def _on_release(self, key):
        name = self._normalize_key(key)
        with self._lock:
            self._current_keys.discard(name)
            active = self._is_active
        if active and self.mode == "push_to_talk":
            parts = [p.strip() for p in self.hotkey_str.split("+")]
            if (
                name in parts
                or (name.startswith("ctrl") and "ctrl" in parts)
                or (name.startswith("shift") and "shift" in parts)
                or (name.startswith("alt") and "alt" in parts)
            ):
                self._trigger_stop()

    def start(self):
        self._is_running = True
        self._is_active = False
        print(f"[OpenFlow Hotkey] Manager started for '{self.hotkey_str}' (mode={self.mode})")

        # Start pynput hook
        self._current_keys.clear()
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release
            )
            self._listener.daemon = True
            self._listener.start()
        except Exception as e:
            print(f"[OpenFlow Hotkey] Note: pynput hook unavailable ({e}); using Win32 polling")
            self._listener = None

        # Start Win32 polling loop for modifier hotkeys
        if self._is_modifier_combo():
            self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self._poll_thread.start()

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
            t.join(timeout=0.5)
