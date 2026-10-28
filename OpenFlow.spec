# -*- mode: python ; coding: utf-8 -*-
"""
OpenFlow PyInstaller Specification
Created by Sachidananda
Builds standalone Windows distribution with CUDA/DirectML/CPU runtime,
PyQt6 glassmorphic UI, audio drivers, and assets.
"""
import os
import sys

# Prevent recursion depth error with large ASTs (transformers, torch, tokenizers)
sys.setrecursionlimit(50000)

from PyInstaller.utils.hooks import collect_all

block_cipher = None

datas = [
    ('openflow/assets', 'openflow/assets'),
    ('openflow/docs', 'openflow/docs'),
]
binaries = []
hiddenimports = [
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'PyQt6.QtNetwork',
    'sounddevice',
    '_sounddevice_data',
    'numpy',
    'ctranslate2',
    'faster_whisper',
    'huggingface_hub',
    'tokenizers',
    'onnxruntime',
    'openflow',
    'openflow.config',
    'openflow.database',
    'openflow.engine',
    'openflow.engine.audio_recorder',
    'openflow.engine.transcriber',
    'openflow.engine.formatter',
    'openflow.engine.injector',
    'openflow.engine.hotkey_manager',
    'openflow.engine.sound_effects',
    'openflow.engine.context_detector',
    'openflow.engine.updater',
    'openflow.engine.meeting',
    'openflow.engine.hardware',
    'openflow.engine.model_manager',
    'openflow.engine.refiner',
    'openflow.ui',
    'openflow.ui.floating_pill',
    'openflow.ui.main_window',
    'openflow.ui.setup_dialog',
    'openflow.autostart',
]

for pkg in ['ctranslate2', 'faster_whisper', 'sounddevice', 'openvino', 'openvino_genai', 'openvino_tokenizers']:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"Hook note for {pkg}: {e}")

# Deduplicate hidden imports
hiddenimports = list(set(hiddenimports))

a = Analysis(
    ['run_app.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tensorflow', 'keras', 'torchvision', 'boto3', 'botocore',
        'uvicorn', 'websockets', 'numba', 'llvmlite',
        'tkinter', 'matplotlib', 'scipy', 'pandas', 'IPython', 'pytest'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='OpenFlow',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='openflow/assets/app_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='OpenFlow',
)
