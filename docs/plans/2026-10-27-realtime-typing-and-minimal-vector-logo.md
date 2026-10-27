# Real-Time Typing Review, Direct Injection & Minimal Vector Brand Identity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the real-time typing review in the Capsule and direct text typing/injection into target applications, while replacing raster assets with a cohesive, Apple-grade minimalist vector brand identity across OpenFlow.

**Architecture:**
1. **Audio VAD & Streaming Pipeline (`engine/audio_recorder.py`, `main.py`)**: Calibrate `_speech_energy_threshold` from an unreachable 0.04 RMS down to an adaptive 0.008 RMS so normal speech reliably triggers `_has_spoken`, enabling real-time streaming chunks (`on_stream_chunk`) and pause-based auto-writing (`on_auto_silence`). Decouple real-time CTranslate2 partial inference from the PortAudio callback to a non-blocking background queue.
2. **Capsule Real-Time Typing Review (`ui/floating_pill.py`)**: Implement smooth dynamic width expansion (340px to 480px) during dictation with live text streaming, animated typing cursor, and smooth word ticker in `AnimatedText`.
3. **Rock-Solid Text Injection (`engine/injector.py`, `ui/main_window.py`)**: Fix `_type_unicode` with explicit `wVk=0`, hardware scan codes, and Enter key translation; increase clipboard restore delay from 0.18s to 0.45s so Electron/browsers don't miss the paste; expose "Writing Mode" (Instant Paste vs Direct Typewriter) in Settings.
4. **Minimal Vector Brand Identity (`assets/`, `docs/img/`, `main.py`, `packaging/`)**: Design an Apple-grade minimalist vector SVG logo representing fluid voice-to-text sound waves and infinity flow. Render crisp multi-resolution PNGs and `.ico` binaries. Update the System Tray, Capsule HUD, Setup Dialog, Main Window, and Landing Page.

**Tech Stack:** Python 3.10+, PyQt6, Win32 API (`ctypes.windll.user32`), `faster-whisper`, SVG / XML vector graphics, PIL/Pillow for multi-resolution ICO/PNG generation.

---

### Task 1: Calibrate Audio VAD & Decouple Real-Time Streaming Chunks

**Files:**
- Modify: `openflow/engine/audio_recorder.py:55-175`
- Modify: `openflow/main.py:528-545`
- Test: `scratch/test_realtime_typing.py`

**Step 1: Write the failing test**

```python
# scratch/test_realtime_typing.py
import numpy as np
import time
from openflow.engine.audio_recorder import AudioRecorder

def test_vad_and_stream_chunk():
    received_chunks = []
    recorder = AudioRecorder(
        on_stream_chunk=lambda chunk: received_chunks.append(chunk),
        auto_silence_duration=0.5
    )
    # Simulate normal speech RMS around 0.015 (below old 0.04 threshold, above new 0.008 threshold)
    t = np.linspace(0, 1, 16000, dtype=np.float32)
    speech_frame = (np.sin(2 * np.pi * 300 * t[:1024]) * 0.02).astype(np.float32)

    recorder.start_recording()
    # Feed audio frames
    for _ in range(20):
        recorder._audio_callback(speech_frame.reshape(-1, 1), 1024, None, None)
        time.sleep(0.04)

    recorder.stop_recording()
    assert recorder._has_spoken, "VAD failed to detect speech at 0.02 RMS!"
    assert len(received_chunks) > 0, "No real-time stream chunks were emitted!"
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_realtime_typing.py`
Expected: FAIL with `AssertionError: VAD failed to detect speech at 0.02 RMS!`

**Step 3: Implement minimal code**
In `openflow/engine/audio_recorder.py`:
- Lower `_speech_energy_threshold` from `0.04` to `0.008`.
- In `_audio_callback`, when `now - self._last_chunk_emit_time > 0.55`:
  - Fetch `accumulated` slice safely under `self._lock`.
  - Dispatch `self.on_stream_chunk(accumulated)` via `threading.Thread(target=..., daemon=True).start()` so PortAudio callback never blocks on inference.

In `openflow/main.py`:
- In `_on_stream_chunk(self, audio_chunk)`:
  - Check `if not self.config.get("realtime_preview", True) or not self.audio_recorder.is_recording: return`
  - Call `self.transcriber.transcribe_partial(audio_chunk)`
  - If text, emit `self.bridge.sig_realtime_text.emit(partial_text)`

**Step 4: Run test to verify it passes**
Run: `python scratch/test_realtime_typing.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/engine/audio_recorder.py openflow/main.py scratch/test_realtime_typing.py
git commit -m "fix(audio): calibrate VAD energy threshold and decouple real-time stream chunks"
```

---

### Task 2: Real-Time Typing Review & Dynamic Capsule Expansion in UI

**Files:**
- Modify: `openflow/ui/floating_pill.py:240-330`
- Modify: `openflow/ui/floating_pill.py:1240-1285`
- Test: `scratch/test_realtime_typing.py`

**Step 1: Write the failing test**

```python
# In scratch/test_realtime_typing.py
def test_capsule_realtime_text_and_expansion(qt_app):
    from openflow.ui.floating_pill import FloatingPill
    pill = FloatingPill()
    pill.show_listening("Listening")
    initial_width = pill.capsule_widget.width()

    # Emulate real-time streaming words
    pill.update_realtime_text("Hello this is a real-time live typing review")
    assert pill.text_label.text() == "Hello this is a real-time live typing review"
    # Capsule should expand dynamically during active speech review
    assert pill.capsule_widget.width() >= 460
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_realtime_typing.py`
Expected: FAIL because width stays fixed at 340px and doesn't expand for real-time review.

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- In `AnimatedText`:
  - Add optional blinking/pulsing typing cursor (e.g. `▊` or smooth vertical line `|`) when receiving streaming text in `"grow"` mode.
  - Ensure eliding and smooth scrolling correctly positions active partial words.
- In `FloatingPill`:
  - Add dynamic capsule width animation `self._cap_width_anim` targeting 480px when `update_realtime_text` receives non-empty speech text, and smoothly reverting to 340px on `show_processing()` / `show_transcription_complete()`.
  - Recenter pill horizontally on screen so the expansion is symmetric like Apple Dynamic Island.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_realtime_typing.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/ui/floating_pill.py
git commit -m "feat(ui): add dynamic capsule expansion and animated cursor for real-time typing review"
```

---

### Task 3: Robust Win32 Direct Unicode Typing & Clipboard Injection

**Files:**
- Modify: `openflow/engine/injector.py:120-230`
- Modify: `openflow/ui/main_window.py:620-655`
- Test: `scratch/test_realtime_typing.py`

**Step 1: Write the failing test**

```python
# In scratch/test_realtime_typing.py
def test_injector_methods():
    from openflow.engine.injector import WindowInjector
    injector = WindowInjector()
    # Test method signature and structure without raising ctypes errors
    assert hasattr(injector, "_type_unicode")
    assert hasattr(injector, "_paste_clipboard")
    # Verify unicode input struct correctly initializes wVk to 0 for KEYEVENTF_UNICODE
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_realtime_typing.py`
Expected: FAIL

**Step 3: Implement minimal code**
In `openflow/engine/injector.py`:
- In `_type_unicode(self, text: str)`:
  - For each char, if `char in ('\r', '\n')`:
    - Send hardware `VK_RETURN` (0x0D) with scancode `0x1C`.
  - Else:
    - Set `inputs[0].u.ki.wVk = 0`
    - Set `inputs[0].u.ki.wScan = ord(char)`
    - Set `inputs[0].u.ki.dwFlags = KEYEVENTF_UNICODE`
    - Set `inputs[1].u.ki.wVk = 0`
    - Set `inputs[1].u.ki.wScan = ord(char)`
    - Set `inputs[1].u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP`
    - Add 1.5ms pause between keystrokes to ensure target window queues handle the input reliably.
- In `_paste_clipboard`:
  - Set hardware scancodes: `user32.MapVirtualKeyW(VK_CONTROL, 0)` and `user32.MapVirtualKeyW(VK_V, 0)`.
  - Increase `time.sleep` before restoring clipboard from 0.18s to 0.45s so slow apps don't miss the paste.
- In `openflow/ui/main_window.py`:
  - Add "Text Injection Method" combobox or toggle in Settings:
    - `"clipboard"`: "Instant Paste (Clipboard - Fastest)"
    - `"type"`: "Direct Typewriter (Unicode - No Clipboard)"
  - Persist to `self.config["injection_method"]`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_realtime_typing.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/engine/injector.py openflow/ui/main_window.py
git commit -m "fix(injector): harden direct Unicode typing and add writing method setting"
```

---

### Task 4: Minimal Vector Brand Identity & Scalable SVG/PNG/ICO Assets

**Files:**
- Create: `openflow/assets/logo.svg`
- Create: `openflow/assets/logo_minimal.svg`
- Create: `openflow/packaging/generate_brand_assets.py`
- Modify: `openflow/assets/logo.png`
- Modify: `openflow/assets/logo_32.png`
- Modify: `openflow/assets/logo_64.png`
- Modify: `openflow/assets/logo.ico`
- Modify: `openflow/docs/img/logo.svg`
- Modify: `openflow/docs/img/logo.png`
- Test: `scratch/test_realtime_typing.py`

**Step 1: Write the failing test**

```python
# In scratch/test_realtime_typing.py
def test_brand_assets():
    import os
    from openflow.ui.floating_pill import get_squircle_pixmap
    svg_path = os.path.abspath("assets/logo.svg")
    ico_path = os.path.abspath("assets/logo.ico")
    assert os.path.exists(svg_path), "Vector SVG logo missing!"
    assert os.path.exists(ico_path), "Multi-resolution ICO missing!"
    pix = get_squircle_pixmap(svg_path, size=32)
    assert not pix.isNull(), "Failed to render SVG squircle!"
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_realtime_typing.py`
Expected: FAIL with `AssertionError: Vector SVG logo missing!`

**Step 3: Implement minimal code**
- Design an Apple-grade minimalist vector SVG logo:
  - Clean obsidian black squircle with subtle continuous curve (superellipse).
  - Elegant flowing voice ribbons / acoustic wave loop forming an iconic infinity wave `O` in crisp pure white and platinum gradients with electric cyan/emerald accents.
- Create `openflow/packaging/generate_brand_assets.py`:
  - Uses `PyQt6.QtSvg` or `QSvgRenderer` / `Pillow` to rasterize `logo.svg` into:
    - `assets/logo.png` (1024x1024)
    - `assets/logo_256.png` (256x256)
    - `assets/logo_64.png` (64x64)
    - `assets/logo_32.png` (32x32)
    - `assets/logo.ico` (containing 256, 128, 64, 48, 32, 16 sizes for Windows)
  - Copy SVG & PNG to `docs/img/` for web presentation.
- Update `main.py`, `ui/floating_pill.py`, `ui/setup_dialog.py`, and `ui/main_window.py` to prefer the vector SVG or high-DPI PNG over old raster JPEGs.
- Update `openflow/packaging/installer.iss` and `packaging/build.py` to use `assets/logo.ico`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_realtime_typing.py`
Expected: PASS

**Step 5: Commit**
```bash
git add openflow/assets/ openflow/packaging/ openflow/docs/
git commit -m "style(brand): generate minimal vector SVG logo and multi-resolution Windows icons"
```

---

### Task 5: End-to-End System Integration & Installer Build

**Files:**
- Modify: `openflow/docs/index.html`
- Modify: `openflow/README.md`
- Test: Full test checkout (`scratch/test_checkout.py` + `scratch/test_realtime_typing.py` + `scratch/test_exe_health.py`)
- Build: `packaging/make_installer.py --rebuild`

**Step 1: Write the failing test**
Run all validation suites to verify complete compliance with zero emojis, vector logos, real-time typing review, and clean direct typing.

**Step 2: Run test to verify it passes**
Run: `python -m pytest scratch/` or run the consolidated checkout test suite.

**Step 3: Rebuild final Windows setup executable**
Run: `python packaging/make_installer.py --rebuild`
Verify: `dist/OpenFlow-Setup.exe` builds cleanly and runs without errors.

**Step 4: Commit**
```bash
git commit -am "release: complete real-time typing review, direct injection and vector brand identity"
```
