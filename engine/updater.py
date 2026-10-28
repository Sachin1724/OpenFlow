"""
updater.py — In-App Auto-Updater for OpenFlow
=============================================
Checks GitHub Releases for new OpenFlow versions, displays download progress
in the HUD pill and main window, and handles smooth installation & restart.
"""

import os
import sys
import json
import re
import tempfile
import threading
import subprocess
import urllib.request
import urllib.error
from typing import Optional, Callable

from PyQt6.QtCore import QObject, pyqtSignal, QTimer


DEFAULT_REPO = "Sachin1724/OpenFlow"


def parse_version(v_str: str) -> tuple:
    """Parse version string like 'v1.0.2' or '1.0' into a comparable tuple of ints."""
    v_clean = re.sub(r'^[vV]', '', str(v_str).strip())
    parts = re.split(r'[-+.]', v_clean)
    num_parts = []
    for p in parts:
        try:
            num_parts.append(int(p))
        except ValueError:
            break
    while len(num_parts) < 3:
        num_parts.append(0)
    return tuple(num_parts)


class AppUpdater(QObject):
    """
    Background auto-updater that checks GitHub Releases for new OpenFlow builds.
    Emits signals for UI progress integration with FloatingPill and MainWindow.
    """
    sig_checking = pyqtSignal()
    sig_update_available = pyqtSignal(str, str, str, str)  # version, release_url, download_url, notes
    sig_no_update = pyqtSignal(str)                       # current_version
    sig_progress = pyqtSignal(int, str)                   # percent (0-100), label
    sig_ready = pyqtSignal(str)                           # downloaded installer_path
    sig_error = pyqtSignal(str)                           # error message

    def __init__(self, current_version: str = "1.0.0", repo: str = DEFAULT_REPO, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self.repo = repo
        self._is_checking = False
        self._is_downloading = False
        self.downloaded_installer: Optional[str] = None
        self.latest_update_info: Optional[dict] = None

    def check_for_updates_async(self, notify_if_current: bool = False):
        """Check for updates in a background worker thread."""
        if self._is_checking or self._is_downloading:
            return
        self._is_checking = True
        self.sig_checking.emit()

        thread = threading.Thread(
            target=self._check_worker,
            args=(notify_if_current,),
            daemon=True,
            name="OpenFlow-UpdateChecker"
        )
        thread.start()

    def _check_worker(self, notify_if_current: bool):
        api_url = f"https://api.github.com/repos/{self.repo}/releases/latest"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": f"OpenFlow-Updater/{self.current_version} (Windows)",
                "Accept": "application/vnd.github.v3+json",
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                if resp.status != 200:
                    self._is_checking = False
                    if notify_if_current:
                        self.sig_error.emit(f"Server returned HTTP {resp.status}")
                    return
                data = json.loads(resp.read().decode("utf-8"))

            tag_name = data.get("tag_name", "")
            remote_ver = parse_version(tag_name)
            local_ver = parse_version(self.current_version)

            if remote_ver > local_ver:
                # Find the setup/installer .exe asset
                download_url = None
                for asset in data.get("assets", []):
                    name = asset.get("name", "").lower()
                    if name.endswith(".exe"):
                        download_url = asset.get("browser_download_url")
                        # Prefer explicit setup file
                        if "setup" in name or "installer" in name:
                            break

                # If no exe asset found, fallback to the html release url
                html_url = data.get("html_url", f"https://github.com/{self.repo}/releases")
                notes = data.get("body", "").strip()
                clean_ver = tag_name.lstrip("vV")

                self.latest_update_info = {
                    "version": clean_ver,
                    "release_url": html_url,
                    "download_url": download_url or html_url,
                    "notes": notes,
                }
                self.sig_update_available.emit(clean_ver, html_url, download_url or "", notes)
            else:
                if notify_if_current:
                    self.sig_no_update.emit(self.current_version)

        except urllib.error.HTTPError as e:
            if e.code == 404:
                # No release published yet
                if notify_if_current:
                    self.sig_no_update.emit(self.current_version)
            else:
                if notify_if_current:
                    self.sig_error.emit(f"Check failed: HTTP {e.code}")
        except Exception as e:
            if notify_if_current:
                self.sig_error.emit(f"Check failed: {str(e)[:50]}")
        finally:
            self._is_checking = False

    def start_download_async(self, download_url: Optional[str] = None, version: Optional[str] = None):
        """Download the installer with progress updates."""
        if self._is_downloading:
            return

        target_url = download_url or (self.latest_update_info.get("download_url") if self.latest_update_info else None)
        target_ver = version or (self.latest_update_info.get("version") if self.latest_update_info else "latest")

        if not target_url or not target_url.endswith(".exe"):
            # Open browser page if direct exe is not present
            if self.latest_update_info and self.latest_update_info.get("release_url"):
                import webbrowser
                webbrowser.open(self.latest_update_info["release_url"])
            return

        self._is_downloading = True
        thread = threading.Thread(
            target=self._download_worker,
            args=(target_url, target_ver),
            daemon=True,
            name="OpenFlow-UpdateDownloader"
        )
        thread.start()

    def _download_worker(self, url: str, version: str):
        dest_path = os.path.join(tempfile.gettempdir(), f"OpenFlow-Setup-v{version}.exe")
        label = f"OpenFlow v{version}"

        try:
            self.sig_progress.emit(0, label)
            req = urllib.request.Request(
                url,
                headers={"User-Agent": f"OpenFlow-Updater/{self.current_version} (Windows)"}
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 64 * 1024

                with open(dest_path, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total_size > 0:
                            percent = min(99, int(downloaded * 100 / total_size))
                            self.sig_progress.emit(percent, label)

            # Finished 100%
            self.sig_progress.emit(100, label)
            self.downloaded_installer = dest_path
            self.sig_ready.emit(dest_path)

        except Exception as e:
            print(f"[OpenFlow Updater] Download error: {e}")
            self.sig_error.emit(f"Download failed: {str(e)[:40]}")
        finally:
            self._is_downloading = False

    def install_and_restart(self, installer_path: Optional[str] = None, silent: bool = True):
        """
        Executes the installer and cleanly quits the current instance.
        Inno Setup supports /SILENT for silent background installation.
        """
        path = installer_path or self.downloaded_installer
        if not path or not os.path.exists(path):
            self.sig_error.emit("Installer file not found")
            return

        try:
            args = [path]
            # Ensure Inno Setup automatically closes running instances of OpenFlow
            args.extend(["/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS"])
            if silent:
                # Inno Setup flags for smooth silent update
                args.extend(["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])

            print(f"[OpenFlow Updater] Launching installer: {' '.join(args)}")
            subprocess.Popen(args, close_fds=True, shell=False)

            # Exit the running application immediately so executable file lock is released
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                app.quit()
            # Force immediate exit so Windows kernel releases the OpenFlow.exe lock
            os._exit(0)
        except Exception as e:
            print(f"[OpenFlow Updater] Install error: {e}")
            self.sig_error.emit(f"Install error: {str(e)[:40]}")
