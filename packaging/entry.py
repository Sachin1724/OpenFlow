import os
import sys
import traceback

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

def _handle_exception(exc_type, exc_value, exc_tb):
    """Log any fatal unhandled exception to ~/.openflow/crash.log and display a native Windows dialog."""
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    err_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        from pathlib import Path
        log_dir = Path.home() / ".openflow"
        log_dir.mkdir(parents=True, exist_ok=True)
        crash_log = log_dir / "crash.log"
        with open(crash_log, "w", encoding="utf-8") as f:
            f.write(err_str)
    except Exception:
        pass

    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"OpenFlow encountered a startup error:\n\n{exc_value}\n\nDetails saved to:\n%USERPROFILE%\\.openflow\\crash.log",
            "OpenFlow Startup Error",
            0x10  # MB_ICONERROR
        )
    except Exception:
        pass

    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _handle_exception


# Ensure openflow is importable both in frozen and source mode
if getattr(sys, "frozen", False):
    basedir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(sys.executable)))
    # If openflow was populated as an empty namespace package due to an on-disk data folder,
    # remove it so Python resolves the true package from the PyInstaller PYZ archive.
    if "openflow" in sys.modules and getattr(sys.modules["openflow"], "__file__", None) is None:
        del sys.modules["openflow"]
    if basedir not in sys.path:
        sys.path.append(basedir)
else:
    basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parent = os.path.dirname(basedir)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    if basedir not in sys.path:
        sys.path.insert(0, basedir)

try:
    from openflow.main import main
except ModuleNotFoundError:
    import importlib
    try:
        main = importlib.import_module("openflow.main").main
    except ModuleNotFoundError:
        main = importlib.import_module("main").main

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()  # a frozen exe must not re-run the whole app in helper processes
    main()

