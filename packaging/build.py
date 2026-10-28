"""Builds dist/OpenFlow/OpenFlow.exe. Run from anywhere: python openflow/packaging/build.py"""
import os
import sys
import shutil

sys.setrecursionlimit(10000)  # PyInstaller trips the default limit on faster-whisper's import graph

import PyInstaller.__main__ as pyi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../openflow
PARENT = os.path.dirname(ROOT)                                        # folder containing the package

# Ensure openflow is importable as lowercase openflow even when folder is capitalized (e.g. CI runner OpenFlow)
if sys.platform == "win32":
    try:
        import subprocess
        parent_openflow = os.path.join(PARENT, "openflow")
        if not os.path.exists(parent_openflow) and ROOT != parent_openflow:
            subprocess.run(["cmd", "/c", "mklink", "/J", parent_openflow, ROOT], check=False)
    except Exception:
        pass

# Ensure openflow is installed as a standard package so PyInstaller cleanly resolves it from site-packages
try:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", ".", "--no-deps"], cwd=ROOT, check=True)
except Exception as e:
    print(f"[Build] Note: package install check: {e}")

# Clean previous dist and build before compilation to prevent stale artifacts
for d in [os.path.join(ROOT, "dist"), os.path.join(ROOT, "build")]:
    if os.path.exists(d):
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

pyi.run([
    os.path.join(ROOT, "packaging", "entry.py"),
    "--noconfirm", "--clean", "--windowed",
    "--name", "OpenFlow",
    "--icon", os.path.join(ROOT, "packaging", "OpenFlow.ico"),
    "--paths", ROOT,
    "--paths", PARENT,
    "--distpath", os.path.join(ROOT, "dist"),
    "--workpath", os.path.join(ROOT, "build"),
    "--specpath", os.path.join(ROOT, "build"),
    "--add-data", os.path.join(ROOT, "assets") + os.pathsep + "assets",
    "--collect-all", "openflow",
    "--collect-all", "faster_whisper",
    "--collect-all", "ctranslate2",
    "--collect-all", "sounddevice",
    "--collect-all", "onnxruntime",
    "--collect-all", "sherpa_onnx",
    "--collect-all", "openvino",
    "--collect-all", "openvino_genai",
    "--collect-all", "openvino_tokenizers",
    "--collect-all", "pyaudiowpatch",
    "--collect-all", "pycaw",
    "--collect-all", "comtypes",

    # the dev machine has large unrelated ML packages installed; keep them out of the exe
    *[a for m in ("torch", "torchaudio", "torchvision", "tensorflow", "transformers", "sklearn", "scipy",
                  "pandas", "matplotlib", "IPython", "notebook", "jupyter", "sentence_transformers",
                  "speechbrain", "librosa", "cv2", "PIL", "tkinter", "pytest", "polars", "pyarrow", "datasets", "numba", "sympy", "llama_cpp")
      for a in ("--exclude-module", m)],
    "--hidden-import", "pynput.keyboard._win32",
    "--hidden-import", "pynput.mouse._win32",
])
