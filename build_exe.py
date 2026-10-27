"""
OpenFlow Build & Distribution Script
Created by Sachidananda
Builds the standalone OpenFlow Windows executable and creates a distributable ZIP package.
"""
import os
import sys
import shutil
import subprocess
import zipfile

def build():
    root = os.path.abspath(os.path.dirname(__file__))
    os.chdir(root)
    print("=" * 60)
    print("OpenFlow Windows Standalone Build Pipeline")
    print("Creator: Sachidananda")
    print("=" * 60)

    # 1. Run PyInstaller
    spec_path = os.path.join(root, "OpenFlow.spec")
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", spec_path]
    print(f"\n[1/3] Running PyInstaller: {' '.join(cmd)}\n")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print("\n[ERROR] PyInstaller build failed!")
        sys.exit(res.returncode)

    dist_dir = os.path.join(root, "dist", "OpenFlow")
    exe_path = os.path.join(dist_dir, "OpenFlow.exe")
    if not os.path.exists(exe_path):
        print(f"\n[ERROR] Output binary {exe_path} not found!")
        sys.exit(1)

    print(f"\n[2/3] Built executable verified: {exe_path}")

    # Copy convenient launcher batch into dist/OpenFlow
    bat_content = "@echo off\r\nstart \"\" \"%~dp0OpenFlow.exe\"\r\n"
    with open(os.path.join(dist_dir, "Launch-OpenFlow.bat"), "w", encoding="utf-8") as f:
        f.write(bat_content)

    # 2. Package into portable ZIP
    zip_name = "OpenFlow-v1.0-Windows-x64.zip"
    zip_dest = os.path.join(root, "dist", zip_name)
    print(f"\n[3/3] Creating distribution ZIP: {zip_dest} ...")

    with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for foldername, subfolders, filenames in os.walk(dist_dir):
            for filename in filenames:
                filepath = os.path.join(foldername, filename)
                arcname = os.path.relpath(filepath, os.path.join(root, "dist"))
                zf.write(filepath, arcname)

    size_mb = os.path.getsize(zip_dest) / (1024 * 1024)
    print(f"\n[SUCCESS] Build complete!")
    print(f"Standalone Folder: {dist_dir}")
    print(f"Distribution ZIP:  {zip_dest} ({size_mb:.1f} MB)")
    print("=" * 60)

if __name__ == "__main__":
    build()
