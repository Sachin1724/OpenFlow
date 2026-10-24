import os
import sys

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NAME = "OpenFlow"


def _command() -> str:
    parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    py = sys.executable
    pyw = py[:-4] + "w.exe" if py.lower().endswith("python.exe") else py  # no console window
    code = f"import sys;sys.path.insert(0,r'{parent}');from openflow.main import main;main()"
    return f'"{pyw}" -c "{code}"'


def set_autostart(enabled: bool):
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, _NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(k, _NAME)
            except FileNotFoundError:
                pass
