# MIRA Blobatar Eye Movement & Head Tracking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement a lifelike organic Blobatar indicator for Odia & Sambalpuri dictation in OpenFlow, featuring real-time eye gaze tracking and 3D head tilt following the Windows mouse cursor with Gaussian blend aura ("gaslan").

**Architecture:** 
A lightweight vector tracker computes the Euclidean directional vector from the capsule's screen position to the system cursor (`QCursor.pos()`). Spring-damped damping smoothly offsets the pupils and tilts the capsule head towards the cursor at 60 FPS without GPU overhead. When our acoustic and dialect engine detects Odia or Sambalpuri speech, the capsule seamlessly activates the MIRA Blobatar in place of the static recording dot.

**Tech Stack:** 
PyQt6 (`QPainter`, `QSvgRenderer`, `QCursor`, `QRadialGradient`), JavaScript/React 18 (`@blobatar/react`, `blobatar/motion.css`), `esbuild`.

---

### Task 1: Mathematical Mouse Pointer & Gaze Physics in `BlobatarWidget`

**Files:**
- Modify: `openflow/ui/blobatar_widget.py`
- Test: `openflow/scratch/test_blob_tracking.py`

**Step 1: Write the unit test for vector cursor gaze tracking**

```python
# openflow/scratch/test_blob_tracking.py
import pytest
from PyQt6.QtCore import QPointF
from openflow.ui.blobatar_widget import calculate_gaze_vector

def test_gaze_tracking_math():
    center = QPointF(100, 100)
    cursor = QPointF(200, 100) # cursor directly to the right
    gaze_x, gaze_y, tilt = calculate_gaze_vector(center, cursor, max_eye_offset=4.0)
    assert gaze_x > 0.0
    assert abs(gaze_y) < 1e-4
    assert tilt > 0.0 # tilts towards cursor
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest openflow/scratch/test_blob_tracking.py -v`  
Expected: FAIL (`ImportError` or `calculate_gaze_vector` not defined)

**Step 3: Implement vector cursor tracking in `blobatar_widget.py`**

- Add standalone mathematical function `calculate_gaze_vector(center: QPointF, cursor_pos: QPointF, max_eye_offset: float = 3.5) -> tuple[float, float, float]`.
- Update `BlobatarWidget._tick()` to sample `QCursor.pos()`, compute screen-relative vector, and lerp (`current += (target - current) * 0.18`) for buttery smooth spring animation.
- In `BlobatarWidget.paintEvent()`, apply `p.rotate(tilt)` to the head, and translate the eye circles/path by `(gaze_x, gaze_y)`.

**Step 4: Run test to verify it passes**

Run: `python -m pytest openflow/scratch/test_blob_tracking.py -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add openflow/ui/blobatar_widget.py openflow/scratch/test_blob_tracking.py
git commit -m "feat(ui): add real-time mouse pointer gaze and head tilt tracking to BlobatarWidget"
```

---

### Task 2: Odia & Sambalpuri Smart Activation in `FloatingPill`

**Files:**
- Modify: `openflow/ui/floating_pill.py`

**Step 1: Check dialect activation hook**

Verify where `FloatingPill.show_listening()` and `set_language()` are invoked and how language state (`or-mix`, `or-en`, `odia`) is stored.

**Step 2: Implement smart indicator switching**

- In `FloatingPill.__init__()`, instantiate `self.blobatar = BlobatarWidget(size=26, parent=self.capsule_widget)`.
- In `FloatingPill._update_indicator_visibility()`:
  - If language is Odia/Sambalpuri (`self.current_language in ("odia", "or-mix", "or-en")` or dialect detected):
    - Hide mechanical `StateIndicator`.
    - Show `BlobatarWidget` with smooth Gaussian glow.
  - Else (standard English):
    - Show standard minimal monochrome indicator.
- Connect audio amplitude: `self.blobatar.set_level(level)`.

**Step 3: Test visually on desktop**

Run: `python -c "from openflow.ui.floating_pill import FloatingPill; from PyQt6.QtWidgets import QApplication; app=QApplication([]); p=FloatingPill(current_language='or-mix'); p.show_listening('Listening'); print('Pill dialect blob ok')"`  
Expected: Prints `Pill dialect blob ok` without error.

**Step 4: Commit**

```bash
git add openflow/ui/floating_pill.py
git commit -m "feat(ui): integrate MIRA Blobatar into FloatingPill for Odia and Sambalpuri"
```

---

### Task 3: Odia & Sambalpuri Smart Activation in `IslandPill`

**Files:**
- Modify: `openflow/ui/island.py`

**Step 1: Inspect `IslandPill._draw_face()` for `listen` state**

Currently:
```python
elif face == "listen":
    pulse = 0.65 + 0.35 * abs(math.sin(time.monotonic() * 2.4))
    p.setBrush(REC)
    p.drawEllipse(...)
```

**Step 2: Implement smart Blobatar rendering in `IslandPill`**

- Add helper method `_draw_blobatar(self, p, center, size, level)` to `IslandPill`.
- If `self.current_language` is Odia / Sambalpuri (`or-mix`, `or-en`, `odia`):
  - In `face == "listen"`, replace the red dot with the living Blobatar capsule with cursor gaze tracking and Gaussian aura.
- Else:
  - Keep standard minimal indicator.

**Step 3: Test visually on desktop**

Run: `python -c "from openflow.ui.island import IslandPill; from PyQt6.QtWidgets import QApplication; app=QApplication([]); p=IslandPill(current_language='or-mix'); p.show_listening(); print('Island dialect blob ok')"`  
Expected: Prints `Island dialect blob ok`.

**Step 4: Commit**

```bash
git add openflow/ui/island.py
git commit -m "feat(ui): integrate MIRA Blobatar into IslandPill with cursor tracking for Odia and Sambalpuri"
```

---

### Task 4: Interactive Web Sample Cursor Tracking in React

**Files:**
- Modify: `openflow/samples/app.jsx`
- Re-bundle: `openflow/samples/bundle.js`

**Step 1: Add window `mousemove` listener in `app.jsx`**

Calculate normalized gaze coordinates `(-1.5 to 1.5)` from the avatar center to the mouse position.
Dynamically inject `--mo-look-x`, `--mo-look-y`, and `--mo-tilt` into the avatar wrapper style.

**Step 2: Re-bundle using `esbuild`**

Run: `npx esbuild openflow/samples/app.jsx --bundle --outfile=openflow/samples/bundle.js --loader:.css=css`  
Expected: `openflow/samples/bundle.js` updated cleanly.

**Step 3: Commit**

```bash
git add openflow/samples/app.jsx openflow/samples/bundle.js
git commit -m "feat(ui): add live mouse cursor tracking to React Blobatar sample"
```

---

### Task 5: End-to-End Visual Verification

**Files:**
- Modify: `openflow/scratch/preview_mira_sample.py`

**Step 1: Re-render snapshot showing mouse cursor tracking**

Run: `python openflow/scratch/preview_mira_sample.py`  
Expected: Saves updated snapshot with cursor gaze tracking.

**Step 2: Launch desktop preview for user inspection**

Run: `open_blob_sample.bat` and `python openflow/preview_mira_blob.py`.

**Step 3: Commit & Push**

```bash
git push origin main
```
