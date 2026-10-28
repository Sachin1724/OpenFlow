"""Builds dist/OpenFlow/OpenFlow.exe. Run from anywhere: python openflow/packaging/build.py"""
import os
import sys
import shutil

sys.setrecursionlimit(10000)  # PyInstaller trips the default limit on faster-whisper's import graph

import PyInstaller.__main__ as pyi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../openflow
PARENT = os.path.dirname(ROOT)                                        # folder containing the package

# Ensure openflow junction exists so openflow package is always resolvable on Windows
junction = os.path.join(ROOT, "openflow")
if not os.path.exists(junction) and sys.platform == "win32":
    try:
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", "openflow", "."], cwd=ROOT, check=False)
    except Exception:
        pass

# Clean previous dist and build before compilation to prevent recursive collection
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
