"""
setup.py — Package configuration and build script for OpenFlow
==============================================================
Enables standard Python packaging, editable developer installs (`pip install -e .`),
and automated Windows installer creation.
"""

import os
import re
import sys
from setuptools import setup, Command


def get_version() -> str:
    init_path = os.path.join(os.path.dirname(__file__), "__init__.py")
    if os.path.exists(init_path):
        with open(init_path, "r", encoding="utf-8") as f:
            match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', f.read())
            if match:
                return match.group(1)
    return "1.1.7"


def get_requirements() -> list:
    req_path = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if not os.path.exists(req_path):
        return []
    reqs = []
    with open(req_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                # Strip inline comments like # Parakeet CPU engine
                clean = line.split("#")[0].strip()
                if clean:
                    reqs.append(clean)
    return reqs


class BuildInstallerCommand(Command):
    """Custom setup.py command to build the Windows standalone installer."""
    description = "Build the OpenFlow Windows installer (OpenFlow-Setup.exe)"
    user_options = [
        ("skip-pyinstaller", None, "Skip PyInstaller build and only recompile Inno Setup"),
    ]

    def initialize_options(self):
        self.skip_pyinstaller = False

    def finalize_options(self):
        pass

    def run(self):
        here = os.path.dirname(os.path.abspath(__file__))
        make_installer_script = os.path.join(here, "packaging", "make_installer.py")
        if not os.path.exists(make_installer_script):
            sys.exit(f"Error: {make_installer_script} not found.")

        cmd = [sys.executable, make_installer_script]
        if self.skip_pyinstaller:
            cmd.append("--no-rebuild")

        import subprocess
        print(f"Running installer build: {' '.join(cmd)}")
        res = subprocess.call(cmd)
        if res != 0:
            sys.exit(res)


setup(
    name="openflow",
    version=get_version(),
    description="Minimal, privacy-first local voice typing capsule for Windows",
    author="Sachidananda",
    license="MIT",
    url="https://github.com/Sachin1724/OpenFlow",
    packages=[
        "openflow",
        "openflow.engine",
        "openflow.ui",
        "openflow.packaging",
    ],
    package_dir={
        "openflow": ".",
        "openflow.engine": "engine",
        "openflow.ui": "ui",
        "openflow.packaging": "packaging",
    },
    include_package_data=True,
    package_data={
        "openflow": [
            "assets/*",
            "assets/fonts/*",
            "packaging/*",
        ],
    },
    install_requires=get_requirements(),
    entry_points={
        "console_scripts": [
            "openflow = openflow.main:main",
        ],
        "gui_scripts": [
            "openflow-gui = openflow.main:main",
        ],
    },
    cmdclass={
        "build_installer": BuildInstallerCommand,
    },
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Win32 (MS Windows)",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Sound/Audio :: Speech",
    ],
)
