# HUD Interfaces Logo & Animation Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Elevate all OpenFlow HUD and dialog interfaces to Apple Human Interface Guidelines and UI/UX Pro Max standards by integrating missing brand marks, eliminating emojis, and adding physics-based spring animations and micro-interactions.

**Architecture:** Implement reusable squircle logo rendering, vector iconography, animated hover/state interpolation, Dynamic Island slide-and-spring popups, and smooth VU level metering across `openflow/ui/floating_pill.py`, `openflow/main.py`, `openflow/ui/setup_dialog.py`, and `openflow/ui/main_window.py`.

**Tech Stack:** PyQt6, QPainter, QPainterPath, QPropertyAnimation, QVariantAnimation, QEasingCurve, Apple HIG Design Foundations, UI/UX Pro Max standards.

---

## Audit of Issues & Opportunities

| Interface Component | Current State | Defect / Limitation | Apple HIG & UI/UX Pro Max Fix |
|---|---|---|---|
| **Capsule HUD Header** (`FloatingPill`) | Plain text `QLabel("OpenFlow")` | Missing logo mark entirely; looks like a generic title | Add a 26x26 anti-aliased squircle brand mark with subtle hairline border; add version pill badge `v1.0` |
| **System Tray Icon** (`main.py`) | Primitive hand-drawn circle & mic rects | Crude, does not use brand identity; looks placeholder | Render official OpenFlow mark with anti-aliased circular mask and subtle translucent outer ring |
| **Application Window Icon** (`main.py`, `MainWindow`) | Default Python/Qt icon | Missing taskbar & Alt-Tab brand identity | Set `app.setWindowIcon(QIcon("assets/logo.jpg"))` and window icon on `MainWindow` |
| **Pseudo-Capsule Mic Banner** (`MicNotificationPill`) | Raw emojis (`🎙️`, `🔄`, `⚠️`) & static opacity fade | Violates UI/UX Pro Max rule against emojis; lacks spatial physics | Replace emojis with crisp vector glyphs; animate both Y-offset and opacity with `OutBack` spring physics (Dynamic Island style) |
| **Live Audio Input Meter** (`FloatingPill`) | Immediate `.setValue(int(lvl*100))` | Jarring, stuttering, hard-jumping progress bar | Implement 60 FPS physics-based spring-decay smoothing (fast attack 0.60, smooth decay 0.20) |
| **Interactive Rows** (`ValueRow`) | Instant 0/1 hover snap, static text change | No hover fade transition; text abruptly jumps on select | Add 150ms animated glass hover highlight (`QVariantAnimation`) and smooth value crossfade |
| **State Indicator** (`StateIndicator`) | Static dim dot at idle; sudden static checkmark at done | Static idle feels dead; completion has no delight | Add gentle breathing luminescence in idle mode; add animated checkmark stroke draw in done state |
| **Setup Dialog** (`SetupDialog`) | Plain text title; no logo | First impression lacks brand identity | Add 48x48 squircle logo thumbnail next to welcome title |

---

### Task 1: Capsule HUD Header Logo & Brand Squircle

**Files:**
- Modify: `openflow/ui/floating_pill.py:637-665`
- Test: `scratch/test_checkout.py`

**Step 1: Write the failing test**
Add a test in `scratch/test_checkout.py` verifying that `FloatingPill` exposes a `logo_label` in its HUD header displaying a valid non-null pixmap with squircle geometry.

```python
def test_hud_header_has_logo():
    pill = FloatingPill()
    assert hasattr(pill, "hud_logo")
    assert pill.hud_logo.pixmap() is not None
    assert not pill.hud_logo.pixmap().isNull()
    assert pill.hud_logo.pixmap().width() >= 24
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_checkout.py`
Expected: FAIL with `AttributeError: 'FloatingPill' object has no attribute 'hud_logo'`

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- Create a helper `get_squircle_pixmap(image_path: str, size: int = 26, radius: float = 6.0) -> QPixmap` that clips an image into an anti-aliased rounded rectangle with a subtle `rgba(255, 255, 255, 0.14)` border.
- In `_build_hud()`, create `self.hud_logo = QLabel(self)` with the 26x26 squircle logo pixmap and insert it into `header_layout` directly before the "OpenFlow" title.
- Add an Apple-style subtle status badge (`v1.0 · Ready`) in the header next to the title.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_checkout.py`
Expected: PASS

---

### Task 2: System Tray & Application Window Icon Brand Polish

**Files:**
- Modify: `openflow/main.py:35-53, 70-76, 203-207`
- Test: `scratch/test_checkout.py`

**Step 1: Write the failing test**
Add a test in `scratch/test_checkout.py` verifying that `create_tray_icon_pixmap()` uses the official OpenFlow brand asset rather than hand-drawn primitive circles.

```python
def test_tray_icon_uses_brand_asset():
    from openflow.main import create_tray_icon_pixmap
    pix = create_tray_icon_pixmap()
    assert not pix.isNull()
    assert pix.width() == 32
    assert pix.height() == 32
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_checkout.py`

**Step 3: Implement minimal code**
In `openflow/main.py`:
- Update `create_tray_icon_pixmap()`: Load `assets/logo.jpg` or `assets/logo_bw.jpg`, composite inside an anti-aliased circle with smooth circular clip, subtle outer highlight rim (`rgba(255, 255, 255, 0.20)`), and crisp 32x32 rendering.
- In `OpenFlowApp.__init__()`, call `self.app.setWindowIcon(QIcon(os.path.join(assets_dir, "logo.jpg")))`.
- Set window icon in `MainWindow` and `SetupDialog`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_checkout.py`
Expected: PASS

---

### Task 3: Animated Vector Icons (Strictly Zero Emojis) & Slide-and-Bounce Physics for Mic Notification Pill

**Files:**
- Modify: `openflow/ui/floating_pill.py:376-500`
- Modify: `openflow/ui/main_window.py:410-415`
- Test: `scratch/test_checkout.py`

**Step 1: Write the failing test**
Verify that `MicNotificationPill` uses animated vector icon rendering (`AnimatedVectorIcon`) with strictly zero emojis, and that `show_event` initializes an active 60 FPS animation timer and geometry animation for smooth vertical spring motion.

```python
def test_mic_pill_animated_vector_icon_no_emojis():
    pill = MicNotificationPill()
    pill.show_event("Yeti Pro", "connected")
    # Verify no emojis in labels or text
    assert "🎙" not in pill.text_label.text()
    assert hasattr(pill, "animated_icon")
    assert pill.animated_icon.mode == "connected"
    assert pill.animated_icon.timer.isActive()  # Live animation running
    assert hasattr(pill, "slide_anim")
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_checkout.py`
Expected: FAIL

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- Remove `self.icon_label = QLabel("🎙️", self)` and any font fallback for emoji sets.
- Implement `AnimatedVectorIcon(QWidget)`:
  - 24x24 vector widget running a 60 FPS `QTimer` updating `self.phase`.
  - Mode `"connected"`: Draws an Apple SF-style vector microphone with a soft pulsing audio-wave ring (`radius = 7.0 + 3.0 * sin(phase * 2.0)`, smooth alpha fade) indicating an active, live microphone.
  - Mode `"switched"`: Draws dual circular curved arrows rotating smoothly around the center (`angle = int(math.degrees(phase * 2.5)) % 360`) showing a dynamic device handoff.
  - Mode `"unplugged"`: Draws an amber/crimson vector warning triangle with an alert mark pulsing softly (`0.65 + 0.35 * sin(phase * 2.0)`).
- In `openflow/ui/main_window.py`: Replace `✓` with clean SVG / vector checkmark.
- Upgrade animation in `MicNotificationPill`:
  - Add `self.slide_anim = QVariantAnimation(self)`.
  - On `show_event()`: Start pos is `y + 16` (tucked behind main capsule), end pos is target `y`. Duration 280ms with `QEasingCurve.Type.OutBack` (amplitude 1.08) for signature Dynamic Island spring feel.
  - On `hide_animated()`: Ease `y` down 8px towards capsule while fading out with `QEasingCurve.Type.InCubic` (180ms).

**Step 4: Run test to verify it passes**
Run: `python scratch/test_checkout.py`
Expected: PASS


---

### Task 4: Liquid Audio Level Meter Smoothing in HUD

**Files:**
- Modify: `openflow/ui/floating_pill.py:685-694, 1023-1027`
- Test: `scratch/test_checkout.py`

**Step 1: Write the failing test**
Verify that `FloatingPill` employs an internal level interpolation ticker for `live_level_bar` so that audio levels glide rather than jumping.

```python
def test_live_level_smoothing():
    pill = FloatingPill()
    pill.set_amplitude(0.8)
    assert pill._target_level == 0.8
    # Should not instantly jump to 80 on the bar
    assert hasattr(pill, "_level_timer")
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_checkout.py`
Expected: FAIL

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- Add `self._target_level = 0.0` and `self._smoothed_level = 0.0`.
- Create `self._level_timer = QTimer(self)` ticking every 16ms (60 FPS) when HUD is expanded.
- In `_tick_level()`:
  - Fast attack: `self._smoothed_level += (self._target_level - self._smoothed_level) * 0.60`
  - Graceful decay: `self._smoothed_level += (self._target_level - self._smoothed_level) * 0.18`
  - Update `self.live_level_bar.setValue(int(self._smoothed_level * 100))`.
- Style `live_level_bar` with a subtle gradient chunk from Apple emerald `#34c759` to white `#ffffff`.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_checkout.py`
Expected: PASS

---

### Task 5: Interactive Glass Row Hover & Value Crossfade in ValueRow

**Files:**
- Modify: `openflow/ui/floating_pill.py:273-375`
- Modify: `openflow/ui/styles.py`
- Test: `scratch/test_checkout.py`

**Step 1: Write the failing test**
Verify that `ValueRow` contains an animated hover property (`_hover_anim`) and value transition logic.

```python
def test_value_row_animation():
    row = ValueRow("Test", "Segoe UI")
    assert hasattr(row, "_hover_anim")
    row.enterEvent(None)
    assert row._hover_anim.state() == QVariantAnimation.State.Running
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_checkout.py`
Expected: FAIL

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- In `ValueRow`: Add `self._hover_alpha = 0.0` and `self._hover_anim = QVariantAnimation(self)` (duration 140ms, `OutCubic`).
- On `enterEvent`: animate `_hover_alpha` to 1.0; on `leaveEvent`: animate to 0.0.
- In `paintEvent`: `p.fillRect(self.rect(), QColor(255, 255, 255, int(16 * self._hover_alpha)))`.
- In `setCurrentIndex`: add a 120ms fade-in transition for the value label.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_checkout.py`
Expected: PASS

---

### Task 6: Checkmark Stroke Drawing & Breathing Luminescence in StateIndicator

**Files:**
- Modify: `openflow/ui/floating_pill.py:41-94`
- Test: `scratch/test_checkout.py`

**Step 1: Write the failing test**
Verify that `StateIndicator` animates checkmark draw progress `_check_p` when entering "done" state and modulates brightness during "idle".

```python
def test_state_indicator_done_stroke():
    ind = StateIndicator()
    ind.set_state("done")
    assert hasattr(ind, "_check_p")
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_checkout.py`
Expected: FAIL

**Step 3: Implement minimal code**
In `openflow/ui/floating_pill.py`:
- In `StateIndicator`:
  - When state is set to "done", reset `_check_p = 0.0` and run a 220ms stroke progress animation.
  - In `paintEvent`, clip the checkmark path using line length proportional to `_check_p`.
  - In "idle" state, apply a gentle 3-second sinusoidal breathing alpha `85 + 30 * sin(phase * 0.4)` to the idle dot, making the resting capsule feel alive and ready.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_checkout.py`
Expected: PASS

---

### Task 7: Setup Dialog & Model Library Brand Polish

**Files:**
- Modify: `openflow/ui/setup_dialog.py:27-40`
- Modify: `openflow/ui/main_window.py:300-330`
- Test: `scratch/test_checkout.py`

**Step 1: Write the failing test**
Verify that `SetupDialog` includes the brand squircle logo thumbnail next to the title.

```python
def test_setup_dialog_has_logo():
    cfg = {}
    dlg = SetupDialog(cfg)
    assert hasattr(dlg, "logo_label")
    assert dlg.logo_label.pixmap() is not None
```

**Step 2: Run test to verify it fails**
Run: `python scratch/test_checkout.py`
Expected: FAIL

**Step 3: Implement minimal code**
- In `openflow/ui/setup_dialog.py`, load `logo.jpg` into a 48x48 squircle and place it in the header layout beside "Welcome to OpenFlow".
- In `openflow/ui/main_window.py` Model Library tab, add the OpenFlow Neural Engine badge in the top header card.

**Step 4: Run test to verify it passes**
Run: `python scratch/test_checkout.py`
Expected: PASS

---

### Task 8: Verification & Rebuild Packaging

**Files:**
- Run: `python scratch/test_checkout.py`
- Run: `python packaging/make_installer.py --rebuild`

**Steps:**
1. Run complete automated checkout suite in `scratch/test_checkout.py`.
2. Verify all UI components, logos, and animations pass without error.
3. Re-build the final setup executable (`dist/OpenFlow-Setup.exe`).
4. Validate binary size and execution integrity.

---
