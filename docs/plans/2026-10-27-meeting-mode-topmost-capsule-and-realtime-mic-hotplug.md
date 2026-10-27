# Meeting Mode, Topmost Z-Order Capsule & Real-Time Hardware Mic Hotplug Implementation Plan

**Status:** Completed & Verified (All 5 Automated Test Suites Passed)

**Goal:** Implement Wispr Flow-style automatic Meeting Mode (detecting Zoom, Teams, Meet, and formatting into structured executive notes), force the Capsule to stay strictly on top of all running apps via Win32 `HWND_TOPMOST`, fix microphone hotplug detection using real-time Windows kernel `winmm.dll` audio endpoint enumeration, and apply the Black-and-White Waveform Capsule Emblem as the app, window, and taskbar icon.

**Architecture:**
1. **Real-Time Hardware Mic Detection (`engine/audio_recorder.py`, `main.py`)**:
   PortAudio (`sounddevice`) caches device lists at startup and never detects newly plugged USB or Bluetooth microphones. Implement native Windows `winmm.dll` (`waveInGetNumDevs` and `waveInGetDevCapsW`) polling to detect hardware mic additions and removals instantaneously. When a hardware change occurs, re-enumerate PortAudio (`sd._terminate(); sd._initialize()`), update active devices, and pop up the `MicNotificationPill`.
2. **Guaranteed Topmost Capsule Z-Order (`ui/floating_pill.py`)**:
   Elevate `FloatingPill` and `MicNotificationPill` using Win32 `SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)` so the capsule never gets buried underneath running apps (Chrome, Teams, Zoom, VS Code, full-screen windows).
3. **Meeting Mode Detection (`engine/meeting_detector.py`)**:
   Poll running processes and active window titles for meeting software (`zoom.exe`, `teams.exe`, `ms-teams.exe`, `webex.exe`, `slack.exe`, and browser windows matching `Meet - ` or `meet.google.com`).
4. **Continuous Meeting Transcription & Note Formatter (`engine/meeting_formatter.py`, `ui/meeting_panel.py`)**:
   Provide a continuous recording mode with live chunk aggregation. When the meeting ends, process raw transcript into structured markdown notes:
   - 📌 **Meeting Overview**
   - 💡 **Key Decisions & Takeaways**
   - 💬 **Discussion Outline**
   - 🎯 **Action Items & Next Steps** (with checkboxes)
5. **Meeting Notes Hub in Dashboard (`ui/main_window.py`, `database.py`)**:
   Store meeting notes in a dedicated SQLite table `meeting_notes`, adding a "Meeting Notes" tab with 1-click "Copy Markdown" and "Export to File".

**Tech Stack:** Python 3.10+, PyQt6, Win32 API (`ctypes.windll.winmm`, `ctypes.windll.user32`), `psutil`, `faster-whisper`, SQLite.

---

### Task 1: Real-Time Hardware Mic Hotplug via Windows OS Kernel (`winmm.dll`)

**Files:**
- Modify: `openflow/engine/audio_recorder.py:210-245`
- Modify: `openflow/main.py:424-475`
- Test: `scratch/test_mic_hotplug_winmm.py`

**Step 1: Write the failing test**

```python
# scratch/test_mic_hotplug_winmm.py
from openflow.engine.audio_recorder import get_live_hardware_microphones

def test_live_hardware_microphones():
    live_mics = get_live_hardware_microphones()
    assert isinstance(live_mics, list)
    assert len(live_mics) > 0, "Failed to query real-time hardware microphones from Windows kernel!"
    print(f"Live Windows hardware microphones: {live_mics}")
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_mic_hotplug_winmm.py`
Expected: FAIL with `ImportError: cannot import name 'get_live_hardware_microphones'`

**Step 3: Implement minimal code**
In `openflow/engine/audio_recorder.py`:
- Add `get_live_hardware_microphones() -> List[str]`:
  Uses `ctypes.windll.winmm.waveInGetNumDevs()` and `WAVEINCAPSW` struct to query the exact live audio devices currently connected to Windows.
- Add `refresh_sounddevice_cache()`:
  Calls `sd._terminate()` and `sd._initialize()` when idle so sounddevice picks up newly plugged USB/Bluetooth mics.
In `openflow/main.py`:
- In `_check_mic_hotplug()`:
  Compare `curr_hardware_mics = get_live_hardware_microphones()` against `_known_hardware_mics`.
  If added or removed:
  - Call `refresh_sounddevice_cache()`
  - Trigger `self.floating_pill.show_mic_event(name, "connected")`
  - Update `self.main_window.refresh_devices()`

**Step 4: Run test to verify it passes**
Run: `python scratch/test_mic_hotplug_winmm.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/engine/audio_recorder.py openflow/main.py scratch/test_mic_hotplug_winmm.py
git commit -m "fix(audio): implement real-time Windows winmm hardware microphone hotplug detection"
```

---

### Task 2: Force Topmost Window Z-Order (`HWND_TOPMOST`) for Capsule

**Files:**
- Modify: `openflow/ui/floating_pill.py:700-725`
- Modify: `openflow/ui/floating_pill.py:545-560`
- Test: `scratch/test_topmost_zorder.py`

**Step 1: Write the failing test**

```python
# scratch/test_topmost_zorder.py
from PyQt6.QtWidgets import QApplication
from openflow.ui.floating_pill import FloatingPill

def test_capsule_topmost_win32_call(qt_app):
    pill = FloatingPill()
    assert hasattr(pill, "force_topmost"), "FloatingPill lacks force_topmost method!"
    pill.force_topmost()
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_topmost_zorder.py`
Expected: FAIL

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- In `FloatingPill` and `MicNotificationPill`:
  - Add `force_topmost(self)`:
    ```python
    import ctypes
    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    ctypes.windll.user32.SetWindowPos(
        int(self.winId()), HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )
    ```
  - Call `self.force_topmost()` in `showEvent()`, `show_listening()`, `show_message()`, and `show_event()`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_topmost_zorder.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/ui/floating_pill.py scratch/test_topmost_zorder.py
git commit -m "fix(ui): enforce Win32 HWND_TOPMOST z-order so capsule stays above all running applications"
```

---

### Task 3: Meeting App Detection Engine (`engine/meeting_detector.py`)

**Files:**
- Create: `openflow/engine/meeting_detector.py`
- Modify: `openflow/main.py:170-220`
- Test: `scratch/test_meeting_detection.py`

**Step 1: Write the failing test**

```python
# scratch/test_meeting_detection.py
from openflow.engine.meeting_detector import is_meeting_active, detect_meeting_app

def test_meeting_app_heuristics():
    # Emulate window title matching
    mock_ctx = {"process": "chrome.exe", "title": "Meet - Weekly Sprint Sync - Google Chrome"}
    detected = detect_meeting_app(mock_ctx)
    assert detected == "Google Meet"
    mock_teams = {"process": "ms-teams.exe", "title": "Microsoft Teams"}
    assert detect_meeting_app(mock_teams) == "Microsoft Teams"
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_meeting_detection.py`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement minimal code**
Create `openflow/engine/meeting_detector.py`:
- Known meeting processes: `zoom.exe` (Zoom), `ms-teams.exe` / `teams.exe` (Microsoft Teams), `webex.exe` (Cisco Webex), `slack.exe` (Slack Huddle).
- Browser URL/title matching: `meet.google.com` or titles starting with `Meet - ` (Google Meet).
- Provide `get_active_meeting_app() -> Optional[str]`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_meeting_detection.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/engine/meeting_detector.py scratch/test_meeting_detection.py
git commit -m "feat(meeting): implement meeting software detection engine"
```

---

### Task 4: Continuous Meeting Recording & Structured Note Formatter

**Files:**
- Create: `openflow/engine/meeting_formatter.py`
- Modify: `openflow/database.py:30-70`
- Modify: `openflow/main.py:530-580`
- Test: `scratch/test_meeting_notes.py`

**Step 1: Write the failing test**

```python
# scratch/test_meeting_notes.py
from openflow.engine.meeting_formatter import format_meeting_notes

def test_meeting_note_formatting():
    raw_transcript = (
        "Good morning everyone. Today we are reviewing the Q4 roadmap. "
        "First, we decided to launch OpenFlow 1.0 next Tuesday. "
        "Sachin will finish the installer and test the meeting mode. "
        "Action item: review the PR by tomorrow afternoon."
    )
    notes = format_meeting_notes(raw_transcript, app_name="Google Meet")
    assert "## Meeting Summary" in notes
    assert "## Key Decisions" in notes
    assert "## Action Items" in notes
    assert "OpenFlow 1.0" in notes
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_meeting_notes.py`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement minimal code**
- Create `openflow/engine/meeting_formatter.py`:
  Extracts agenda, key decisions, discussion bullets, and action items with `[ ]` markdown checkboxes from transcript.
- In `openflow/database.py`:
  Add `meeting_notes` table storing:
  `id, timestamp, title, app_name, raw_transcript, formatted_notes, duration_seconds`.
  Add methods `add_meeting_note(...)`, `get_meeting_notes()`, `delete_meeting_note(id)`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_meeting_notes.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/engine/meeting_formatter.py openflow/database.py scratch/test_meeting_notes.py
git commit -m "feat(meeting): implement structured meeting note formatter and SQLite persistence"
```

---

### Task 5: Meeting Mode UI Sheet & Dashboard Meeting Notes Tab

**Files:**
- Modify: `openflow/ui/floating_pill.py:820-900`
- Modify: `openflow/ui/main_window.py:110-150`
- Modify: `openflow/ui/main_window.py:800-880`
- Test: `scratch/test_meeting_ui.py`

**Step 1: Write the failing test**

```python
# scratch/test_meeting_ui.py
from openflow.ui.main_window import MainWindow
from openflow.database import Database
from openflow.config import load_config

def test_meeting_notes_tab_in_dashboard(qt_app):
    win = MainWindow(Database(), load_config())
    tab_names = [win.tabs.tabText(i) for i in range(win.tabs.count())]
    assert "Meeting Notes" in tab_names, f"Meeting Notes tab missing: {tab_names}"
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_meeting_ui.py`
Expected: FAIL

**Step 3: Implement minimal code**
- In `openflow/ui/floating_pill.py`:
  When a meeting is detected, show a meeting badge in the capsule or HUD: `Meeting: Google Meet · Press Ctrl+Shift+M to Record Meeting`.
- In `openflow/ui/main_window.py`:
  Add **"Meeting Notes"** tab to `self.tabs`:
  - List of past meetings with app name, timestamp, and duration.
  - Markdown note preview with "Copy Markdown" and "Export to .MD" buttons.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_meeting_ui.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/ui/floating_pill.py openflow/ui/main_window.py scratch/test_meeting_ui.py
git commit -m "feat(ui): add meeting indicator to capsule and meeting notes viewer in dashboard"
```

---

### Task 6: End-to-End Test Run & Verification

**Files:**
- Consolidate all test suites into `scratch/test_meeting_checkout.py`.
- Execute test run live.
