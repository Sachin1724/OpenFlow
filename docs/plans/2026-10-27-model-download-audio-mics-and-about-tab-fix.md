# Comprehensive Fix Plan: Model Auto-Download Prevention, Active Microphone Inspection, About & Privacy Hub, and Capsule Typing Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve background model re-downloading by prioritizing existing local models, fix microphone deduplication and active device display, restore the hotplug pop-up pill, create a dedicated About & Privacy Policy hub with developer contact (Mr. Chindhada / GitHub / Website / Mail), and refine capsule typing animations and fast-exit on empty speech.

**Architecture:**
1. **Model Cache Prioritization (`engine/hardware.py`, `config.py`, `engine/model_manager.py`)**:
   Modify `hardware.resolve(cfg)` to check `model_manager.list_downloaded_models()`. When `model_size == "auto"`, always select the best *already-downloaded* model on local disk (e.g. `base`, `tiny`) instead of recommending an undownloaded `small` (464 MB) or `medium` (1.43 GB). Persist the chosen model into `config.json` upon selection.
2. **Audio Device Deduplication & Active Mic Visibility (`engine/audio_recorder.py`, `ui/main_window.py`)**:
   Filter redundant virtual endpoints (MME/DirectSound duplicate mappings and Sound Mappers) in `list_microphones()`. Query the active system input and annotate the Settings dropdown and status card with `(Currently Active)`.
3. **Mic Hotplug Companion Pill Delegate (`ui/floating_pill.py`, `main.py`)**:
   Implement `FloatingPill.show_mic_event(name, status)` delegating directly to `self.mic_pill.show_event(name, status, self.geometry())` with an active 1.5s hotplug detection poll.
4. **About & Privacy Policy Dashboard Tab (`ui/main_window.py`)**:
   Add an **About** tab to the dashboard containing the high-DPI squircle brand emblem, developer bio ("Developed by Sachidananda"), clickable vector-icon buttons for GitHub (`https://github.com/Sachin1724/OpenFlow`), project website (`https://sachin1724.github.io/OpenFlow/`), direct issue reporting email (`mailto:fakesachin.19@gmail.com`), and an ironclad local privacy statement.
5. **Capsule Typing Effect & Fast-Exit on Silence (`ui/floating_pill.py`, `main.py`)**:
   Polish `AnimatedText` in the capsule to display live words with an active glowing cursor in expanded listening mode; when speech is empty or under 0.25s, display "No speech detected" for only 800ms and immediately collapse without lingering.

**Tech Stack:** Python 3.10+, PyQt6, Sounddevice, CTranslate2 / Faster-Whisper, QDesktopServices for OS-native browser/mail launching.

---

### Task 1: Prevent Auto-Downloading When Cached Models Exist

**Files:**
- Modify: `openflow/engine/hardware.py:76-88`
- Modify: `openflow/engine/model_manager.py`
- Modify: `openflow/main.py:140-155`
- Test: `scratch/test_model_resolution.py`

**Step 1: Write the failing test**

```python
# scratch/test_model_resolution.py
from openflow.engine import hardware, model_manager

def test_auto_model_prefers_downloaded_cache():
    # If base is downloaded and config is auto, resolution MUST pick base, NOT small
    cfg = {"model_size": "auto", "device": "auto"}
    rt = hardware.resolve(cfg)
    downloaded = model_manager.list_downloaded_models()
    if downloaded:
        assert rt["model_size"] in downloaded, (
            f"Resolved model '{rt['model_size']}' is not in downloaded cache: {downloaded}!"
        )
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_model_resolution.py`
Expected: FAIL if GPU has >=6GB VRAM and resolves to `small` despite `base` being downloaded.

**Step 3: Implement minimal code**
In `openflow/engine/hardware.py`:
- Import `model_manager` lazily or directly.
- In `resolve(cfg)`:
  ```python
  size = cfg.get("model_size", "auto")
  if size == "auto":
      try:
          from . import model_manager
          downloaded = model_manager.list_downloaded_models()
      except Exception:
          downloaded = []
      if downloaded:
          # Prefer matching hardware recommendation if already downloaded
          if hw["model_size"] in downloaded:
              size = hw["model_size"]
          elif "base" in downloaded:
              size = "base"
          elif "tiny" in downloaded:
              size = "tiny"
          else:
              size = downloaded[0]
      else:
          size = "base"
  ```
- In `openflow/main.py`:
  When `self.transcriber` is initialized, write the resolved `size` to `self.config["model_size"]` and `save_config(self.config)` if it was `"auto"`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_model_resolution.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/engine/hardware.py openflow/main.py scratch/test_model_resolution.py
git commit -m "fix(model): prioritize already-downloaded models to prevent unexpected background downloads"
```

---

### Task 2: Deduplicate Microphones & Display Currently Active Device

**Files:**
- Modify: `openflow/engine/audio_recorder.py:210-236`
- Modify: `openflow/ui/main_window.py:567-582`
- Test: `scratch/test_mic_inspection.py`

**Step 1: Write the failing test**

```python
# scratch/test_mic_inspection.py
from openflow.engine.audio_recorder import list_microphones, AudioRecorder

def test_mic_deduplication_and_active_label():
    devices = list_microphones()
    names = [d["name"] for d in devices]
    # Verify no exact duplicates
    assert len(names) == len(set(names)), f"Duplicate devices found: {names}"
    # Verify generic Microsoft Sound Mapper / Primary Sound Capture Driver are filtered
    for n in names:
        assert "Sound Mapper" not in n, f"Virtual mapper not filtered: {n}"
        assert "Primary Sound Capture" not in n, f"Virtual capture driver not filtered: {n}"

    recorder = AudioRecorder()
    active_name = recorder.get_current_device_name()
    assert active_name, "Failed to resolve active microphone name!"
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_mic_inspection.py`
Expected: FAIL due to duplicates or sound mapper present.

**Step 3: Implement minimal code**
In `openflow/engine/audio_recorder.py`:
- In `list_microphones()`:
  - Filter out `"Microsoft Sound Mapper"` and `"Primary Sound Capture Driver"`.
  - Filter devices where `max_input_channels > 0`.
  - Maintain a set `seen_clean_names` and skip duplicates across different host APIs (preferring WASAPI or highest sample rate).
- In `openflow/ui/main_window.py`:
  - Query `active_name = self.audio_recorder.get_current_device_name()`.
  - In `self.mic_combo`:
    - First item: `f"Default System Microphone · Active: {active_name}"`.
    - For each item in `self.mic_devices`:
      - If `dev["name"] == active_name`:
        `label = f"● {dev['name']} (Currently Active)"`
      - Else:
        `label = f"{dev['name']}"`
  - Add an active microphone status badge in the Settings card:
    `"Active Input: " + active_name`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_mic_inspection.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/engine/audio_recorder.py openflow/ui/main_window.py scratch/test_mic_inspection.py
git commit -m "fix(audio): deduplicate input devices and highlight currently active microphone"
```

---

### Task 3: Fix Microphone Connect/Disconnect Pop-up Notification Pill

**Files:**
- Modify: `openflow/ui/floating_pill.py:1300-1360`
- Modify: `openflow/main.py:424-472`
- Test: `scratch/test_mic_popup.py`

**Step 1: Write the failing test**

```python
# scratch/test_mic_popup.py
from PyQt6.QtWidgets import QApplication
from openflow.ui.floating_pill import FloatingPill

def test_floating_pill_show_mic_event(qt_app):
    pill = FloatingPill()
    assert hasattr(pill, "show_mic_event"), "FloatingPill lacks show_mic_event delegate!"
    pill.show_mic_event("HyperX SoloCast", "connected")
    assert pill.mic_pill.isVisible(), "MicNotificationPill should be visible on event!"
    assert "HyperX SoloCast" in pill.mic_pill.text_label.text()
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_mic_popup.py`
Expected: FAIL with `AssertionError: FloatingPill lacks show_mic_event delegate!`

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- Add `show_mic_event(self, mic_name: str, status: str = "connected")`:
  ```python
  def show_mic_event(self, mic_name: str, status: str = "connected"):
      if hasattr(self, "mic_pill"):
          self.mic_pill.show_event(mic_name, status, self.geometry())
  ```
In `openflow/main.py`:
- Create a dedicated `QTimer` (`self._mic_poll_timer`) running every 1800ms calling `self._check_mic_hotplug()`.
- Log any hotplug events cleanly and trigger `self.floating_pill.show_mic_event(name, "connected" | "switched" | "disconnected")`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_mic_popup.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/ui/floating_pill.py openflow/main.py scratch/test_mic_popup.py
git commit -m "fix(ui): delegate show_mic_event to mic notification pill and increase hotplug responsiveness"
```

---

### Task 4: Create Dedicated About & Privacy Hub with Developer Links

**Files:**
- Modify: `openflow/ui/main_window.py:60-150`
- Modify: `openflow/ui/main_window.py:750-815`
- Test: `scratch/test_about_tab.py`

**Step 1: Write the failing test**

```python
# scratch/test_about_tab.py
from openflow.ui.main_window import MainWindow
from openflow.database import Database
from openflow.config import load_config

def test_about_tab_present(qt_app):
    win = MainWindow(Database(), load_config())
    tab_names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert "About" in tab_names, f"'About' tab missing from tabs: {tab_names}"
    about_idx = tab_names.index("About")
    about_widget = win.tabs.widget(about_idx)
    # Check developer attribution & links
    labels = [w.text() for w in about_widget.findChildren(QLabel)]
    assert any("Sachidananda" in t for t in labels), "Developer Sachidananda missing from About tab!"
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_about_tab.py`
Expected: FAIL with `AssertionError: 'About' tab missing from tabs`

**Step 3: Implement minimal code**
In `openflow/ui/main_window.py`:
- Add `"About"` tab to `self.tabs`.
- Implement `_create_about_tab(self) -> QWidget`:
  - **Header Card**:
    - High-DPI squircle brand emblem (48x48) + "OpenFlow v1.0.0".
    - Subtitle: "Private, unlimited voice dictation & speech-to-writing system. 100% on-device AI."
  - **Creator & Open Source Card**:
    - "Developed with ❤️ by **Sachidananda**"
    - Three vector-icon action buttons:
      1. `GitHub Repository`: Launches `https://github.com/Sachin1724/OpenFlow` via `QDesktopServices.openUrl()`.
      2. `Official Website`: Launches `https://sachin1724.github.io/OpenFlow/`.
      3. `Contact Developer / Report Issue`: Launches `mailto:fakesachin.19@gmail.com?subject=OpenFlow%20Inquiry%20%2F%20Issue`.
  - **Privacy Policy & Local Security Commitment Card**:
    - Zero data transmitted over the internet.
    - Zero telemetry, zero speech logging to external servers.
    - Local SQLite database & offline model weights stored in user profile.
    - Full user sovereignty: Instant model deletion & history wipe.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_about_tab.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/ui/main_window.py scratch/test_about_tab.py
git commit -m "feat(ui): add dedicated About & Privacy hub with developer links and contact buttons"
```

---

### Task 5: Capsule Typing Effect Polish & Fast-Exit on Silence/Empty Audio

**Files:**
- Modify: `openflow/ui/floating_pill.py:240-330`
- Modify: `openflow/main.py:550-580`
- Test: `scratch/test_typing_and_silence.py`

**Step 1: Write the failing test**

```python
# scratch/test_typing_and_silence.py
from openflow.ui.floating_pill import FloatingPill

def test_fast_exit_on_empty_speech(qt_app):
    pill = FloatingPill()
    pill.show_listening()
    # Emulate empty speech event
    pill.show_message("No Speech Detected", duration_ms=800)
    assert pill.hide_timer.interval() == 800, f"Expected 800ms timer, got {pill.hide_timer.interval()}"
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_typing_and_silence.py`
Expected: FAIL if interval was 2500ms.

**Step 3: Implement minimal code**
In `openflow/main.py`:
- In `_process_worker(audio_data)`:
  - If `len(audio_data) < 2400`:
    `self.floating_pill.show_message("Tap · Hold to Dictate", duration_ms=700)`
    `return`
  - If `not raw_text.strip()`:
    `self.floating_pill.show_message("No Speech Detected", duration_ms=850)`
    `return`
In `openflow/ui/floating_pill.py`:
- In `AnimatedText`:
  - When in live preview `"grow"` mode, render active partial text with a subtle, sleek vertical glowing cursor `|` (alpha 200) that pulses softly.
  - Expand capsule smoothly when live preview text arrives, and restore immediately on finish.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_typing_and_silence.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/ui/floating_pill.py openflow/main.py scratch/test_typing_and_silence.py
git commit -m "fix(ui): polish capsule typing effect and implement fast-exit on empty audio"
```

---

### Task 6: Recompile Windows Installer & Full End-to-End Verification

**Files:**
- Run: consolidated test suite
- Rebuild: `python packaging/make_installer.py --rebuild`
- Verify: `dist/OpenFlow-Setup.exe`
