import re
import time
import ctypes
from ctypes import wintypes
import pyperclip
from typing import Dict, Any

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_V = 0x56
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
SW_RESTORE = 9
SW_SHOW = 5
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# Input structures for SendInput
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", INPUT_UNION),
    ]

INPUT_KEYBOARD = 1


class WindowInjector:
    def __init__(self):
        pass

    def get_foreground_window(self) -> Dict[str, Any]:
        """Captures currently focused window handle, title, and process name."""
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"hwnd": 0, "title": "Desktop", "process": "explorer.exe"}

        title_buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, title_buf, 512)
        window_title = title_buf.value

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        process_name = "unknown.exe"
        h_process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h_process:
            proc_buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h_process, 0, proc_buf, ctypes.byref(size)):
                import os
                process_name = os.path.basename(proc_buf.value)
            kernel32.CloseHandle(h_process)

        return {
            "hwnd": hwnd,
            "title": window_title,
            "process": process_name
        }

    def force_focus(self, target_hwnd: int):
        """Forcibly restores foreground focus using Win32 AttachThreadInput."""
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return

        current_thread = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        target_thread = user32.GetWindowThreadProcessId(target_hwnd, None)

        if current_thread != target_thread:
            user32.AttachThreadInput(current_thread, target_thread, True)
        if fg_thread and fg_thread != target_thread:
            user32.AttachThreadInput(fg_thread, target_thread, True)

        user32.ShowWindow(target_hwnd, SW_SHOW)
        user32.SetForegroundWindow(target_hwnd)
        user32.BringWindowToTop(target_hwnd)

        if current_thread != target_thread:
            user32.AttachThreadInput(current_thread, target_thread, False)
        if fg_thread and fg_thread != target_thread:
            user32.AttachThreadInput(fg_thread, target_thread, False)

        time.sleep(0.04)

    def _release_all_modifiers(self):
        """Releases Shift, Ctrl, Alt, Win keys so Ctrl+V is not mixed with Shift."""
        keys = [
            VK_SHIFT, 0xA0, 0xA1,   # VK_SHIFT, VK_LSHIFT, VK_RSHIFT
            VK_CONTROL, 0xA2, 0xA3, # VK_CONTROL, VK_LCONTROL, VK_RCONTROL
            VK_MENU, 0xA4, 0xA5,    # Alt
            0x5B, 0x5C              # Windows keys
        ]
        for vk in keys:
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.02)

    def inject_text(self, text: str, target_hwnd: int = 0, method: str = "clipboard", restore_clipboard: bool = True):
        """Automatically writes the transcribed text directly into the focused control."""
        if not text:
            return

        # 1. Force foreground focus to the target application
        if target_hwnd:
            self.force_focus(target_hwnd)

        # 2. Clear any lingering modifier keys (especially Shift from Ctrl+Shift release!)
        self._release_all_modifiers()

        # 3. Perform text injection
        if method in ("type", "typein"):
            self._type_unicode(text, animate=method == "typein")
        else:
            success = self._paste_clipboard(text, restore_clipboard=restore_clipboard)
            if not success:
                print("[OpenFlow Injector] Clipboard paste failed, falling back to direct Unicode typing...")
                self._type_unicode(text)

    def _paste_clipboard(self, text: str, restore_clipboard: bool = True) -> bool:
        old_clipboard = None
        if restore_clipboard:
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                old_clipboard = None

        copied = False
        for _ in range(5):
            try:
                pyperclip.copy(text)
                copied = True
                break
            except Exception:
                time.sleep(0.02)

        if not copied:
            return False

        time.sleep(0.03)
        self._ctrl(VK_V)

        # Allow application to process before restoring clipboard (450ms for slow apps/browsers)
        if restore_clipboard and old_clipboard is not None:
            time.sleep(0.45)
            try:
                pyperclip.copy(old_clipboard)
            except Exception:
                pass

        return True

    @staticmethod
    def _ctrl(vk: int):
        """Ctrl+<key> as one SendInput call with hardware scancodes."""
        inputs = (INPUT * 4)()
        for i, (key, up) in enumerate([(VK_CONTROL, 0), (vk, 0), (vk, KEYEVENTF_KEYUP), (VK_CONTROL, KEYEVENTF_KEYUP)]):
            inputs[i].type = INPUT_KEYBOARD
            inputs[i].u.ki.wVk = key
            inputs[i].u.ki.wScan = user32.MapVirtualKeyW(key, 0)
            inputs[i].u.ki.dwFlags = up
        user32.SendInput(4, ctypes.byref(inputs), ctypes.sizeof(INPUT))

    def copy_selection(self, target_hwnd: int = 0) -> str:
        """Text selected in the target window ('' when nothing is selected); the clipboard is put back."""
        if target_hwnd:
            self.force_focus(target_hwnd)
        self._release_all_modifiers()
        try:
            old = pyperclip.paste()
            pyperclip.copy("")  # empty marker: still empty after Ctrl+C means no selection
        except Exception:
            return ""
        self._ctrl(VK_C)
        selected = ""
        for _ in range(10):  # apps answer Ctrl+C within ~50-300 ms
            time.sleep(0.04)
            try:
                selected = pyperclip.paste()
            except Exception:
                continue
            if selected:
                break
        try:
            pyperclip.copy(old)
        except Exception:
            pass
        return selected

    def _send_chunk(self, chunk: str):
        """One SendInput call for a whole word, so the app receives it atomically."""
        VK_RETURN = 0x0D
        events = []  # (wVk, wScan, flags)
        for char in chunk:
            if char == '\r':
                continue
            if char == '\n':  # standard Enter keystroke
                events += [(VK_RETURN, 0x1C, 0), (VK_RETURN, 0x1C, KEYEVENTF_KEYUP)]
                continue
            # wScan holds one UTF-16 unit: emoji and other astral chars go as a surrogate pair.
            # wVk MUST be 0 when KEYEVENTF_UNICODE is specified.
            raw = char.encode("utf-16-le")
            for i in range(0, len(raw), 2):
                unit = int.from_bytes(raw[i:i + 2], "little")
                events += [(0, unit, KEYEVENTF_UNICODE), (0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
        if not events:
            return
        inputs = (INPUT * len(events))()
        for inp, (vk, scan, flags) in zip(inputs, events):
            inp.type = INPUT_KEYBOARD
            inp.u.ki.wVk = vk
            inp.u.ki.wScan = scan
            inp.u.ki.dwFlags = flags
        user32.SendInput(len(events), ctypes.byref(inputs), ctypes.sizeof(INPUT))

    def _type_unicode(self, text: str, animate: bool = False):
        """Directly sends Unicode characters into the focused control without clipboard.
        animate=True writes word by word (ChatGPT-style type-in), capped at ~1 s for any length."""
        words = re.findall(r"\S+\s*|\s+", text)
        delay = min(0.035, 1.0 / max(1, len(words))) if animate else 0.002
        for word in words:
            self._send_chunk(word)
            time.sleep(delay)
