import os
import sys
import traceback
import types

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
    if basedir not in sys.path:
        sys.path.insert(0, basedir)
    pkg_dir = os.path.join(basedir, "openflow")
    if os.path.isdir(pkg_dir):
        if pkg_dir not in sys.path:
            sys.path.insert(0, pkg_dir)
        if "openflow" not in sys.modules or getattr(sys.modules["openflow"], "__file__", None) is None:
            mod = types.ModuleType("openflow")
            mod.__file__ = os.path.join(pkg_dir, "__init__.py")
            mod.__path__ = [pkg_dir]
            mod.__package__ = "openflow"
            sys.modules["openflow"] = mod
else:
    basedir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parent = os.path.dirname(basedir)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    if basedir not in sys.path:
        sys.path.insert(0, basedir)

import multiprocessing
multiprocessing.freeze_support()  # the engine child process ends here, before the heavy UI imports below

main = None
try:
    from openflow.main import main
except Exception as e_pkg:
    try:
        from main import main
    except Exception as e_top:
        import importlib
        try:
            main = importlib.import_module("openflow.main").main
        except Exception as e_dyn_pkg:
            try:
                main = importlib.import_module("main").main
            except Exception as e_dyn_top:
                raise RuntimeError(
                    f"Failed to start OpenFlow: main module could not be loaded.\n"
                    f"Attempts:\n"
                    f"  1. 'from openflow.main import main' -> {e_pkg}\n"
                    f"  2. 'from main import main' -> {e_top}\n"
                    f"  3. 'importlib.import_module(openflow.main)' -> {e_dyn_pkg}\n"
                    f"  4. 'importlib.import_module(main)' -> {e_dyn_top}\n"
                    f"sys.frozen: {getattr(sys, 'frozen', False)}\n"
                    f"sys.path: {sys.path}"
                )

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
