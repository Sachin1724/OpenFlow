"""Builds dist/OpenFlow/OpenFlow.exe. Run from anywhere: python openflow/packaging/build.py"""
import os
import sys

sys.setrecursionlimit(10000)  # PyInstaller trips the default limit on faster-whisper's import graph

import PyInstaller.__main__ as pyi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # .../openflow
PARENT = os.path.dirname(ROOT)                                        # folder containing the package

pyi.run([
    os.path.join(ROOT, "packaging", "entry.py"),
    "--noconfirm", "--clean", "--windowed",
    "--name", "OpenFlow",
    "--icon", os.path.join(ROOT, "packaging", "OpenFlow.ico"),
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
