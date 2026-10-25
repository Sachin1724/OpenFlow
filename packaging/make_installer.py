"""
make_installer.py — Complete Build & Setup EXE Packaging Pipeline for OpenFlow
=============================================================================
1. Builds the PyInstaller bundle in dist/OpenFlow/
2. Compiles packaging/installer.iss with Inno Setup 6 (ISCC.exe)
3. Outputs dist/OpenFlow-Setup.exe (the final Windows installer setup file)

Run from repository root:
    python -m openflow.packaging.make_installer
or from packaging folder:
    python make_installer.py
"""

import os
import sys
import subprocess
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../openflow
DIST_DIR = os.path.join(ROOT, "dist")
APP_EXE = os.path.join(DIST_DIR, "OpenFlow", "OpenFlow.exe")
ISS_SCRIPT = os.path.join(ROOT, "packaging", "installer.iss")
FINAL_SETUP_EXE = os.path.join(DIST_DIR, "OpenFlow-Setup.exe")


def find_iscc() -> str:
    """Find the Inno Setup compiler executable."""
    candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        shutil.which("iscc"),
        shutil.which("ISCC.exe"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    raise FileNotFoundError(
        "Inno Setup 6 compiler (ISCC.exe) not found. "
        "Install via winget: 'winget install JRSoftware.InnoSetup' or download from https://jrsoftware.org/isdl.php"
    )


def is_source_newer(exe_path: str) -> bool:
    """Check if any Python source or packaging file has been modified after the exe was built."""
    if not os.path.exists(exe_path):
        return True
    exe_mtime = os.path.getmtime(exe_path)
    for root, _, files in os.walk(ROOT):
        if any(ignored in root for ignored in ("dist", "build", ".git", "__pycache__", ".vscode")):
            continue
        for f in files:
            if f.endswith((".py", ".iss", ".ico", ".svg")):
                try:
                    if os.path.getmtime(os.path.join(root, f)) > exe_mtime:
                        return True
                except OSError:
                    pass
    return False


def step1_pyinstaller(rebuild: bool = False):
    """Build PyInstaller distribution."""
    needs_rebuild = rebuild or is_source_newer(APP_EXE)
    if os.path.exists(APP_EXE) and not needs_rebuild:
        print(f"[1/2] PyInstaller build is up to date at: {APP_EXE}")
        return

    print("[1/2] Running PyInstaller build (bundling updated code, faster-whisper, PyQt6)...")
    build_script = os.path.join(ROOT, "packaging", "build.py")
    res = subprocess.run([sys.executable, build_script], cwd=ROOT)
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller build failed with exit code {res.returncode}")

    if not os.path.exists(APP_EXE):
        raise FileNotFoundError(f"Expected output not found: {APP_EXE}")
    print(f"       Built: {APP_EXE}")



def step2_inno_setup():
    """Compile the installer script into OpenFlow-Setup.exe."""
    iscc = find_iscc()
    print(f"[2/2] Compiling Windows Setup EXE with Inno Setup: {iscc}")
    print(f"       Script: {ISS_SCRIPT}")

    cmd = [iscc, f"/O{DIST_DIR}", "/FOpenFlow-Setup", ISS_SCRIPT]
    res = subprocess.run(cmd, cwd=os.path.dirname(ISS_SCRIPT))
    if res.returncode != 0:
        raise RuntimeError(f"Inno Setup compilation failed with exit code {res.returncode}")

    if not os.path.exists(FINAL_SETUP_EXE):
        raise FileNotFoundError(f"Installer was not created: {FINAL_SETUP_EXE}")

    size_mb = os.path.getsize(FINAL_SETUP_EXE) / (1024 * 1024)
    print("\n" + "=" * 64)
    print(" SUCCESS! OpenFlow Windows Setup File Created")
    print("=" * 64)
    print(f" Setup File: {FINAL_SETUP_EXE}")
    print(f" File Size : {size_mb:.2f} MB")
    print("=" * 64)


def main():
    rebuild = "--rebuild" in sys.argv or "-r" in sys.argv
    print("================================================================")
    print("            OpenFlow Windows Installer Builder                  ")
    print("================================================================")
    try:
        step1_pyinstaller(rebuild=rebuild)
        step2_inno_setup()
    except Exception as e:
        print(f"\n[ERROR] Build pipeline failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
