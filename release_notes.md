# OpenFlow v1.1.7 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Fixes in v1.1.7
- **Dictation pastes again**: Ctrl+V sent as one batched input was silently dropped on some Windows builds, leaving the text only in the clipboard. Keys are now sent one by one.
- **No more endless spinner**: a live-preview call on the GPU could freeze and block every dictation after it. OpenFlow now gives up on a stuck call after 10 s and finishes on the CPU; the capsule always returns to idle and the hotkey keeps working.
- **Mis-pressed hotkey**: a tap under 0.35 s (or a Ctrl shortcut) is discarded instead of starting a recording that never ended. Hands-free dictation is the Toggle mode in Settings.
- **Dashboard no longer opens at boot**: the installer stops adding a Startup shortcut (it doubled the app's own autostart) and removes the old one; a second launch only shows the capsule.
- **Capsule opacity**: new Settings slider, 30–100%, applied live.

---

# OpenFlow v1.1.6 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.1.6
- **Apple-Grade Velvety OLED Capsule Aesthetic**:
  - Re-engineered capsule rendering with continuous subpixel pill geometry (`QPainterPath` with exact $r = \text{height} / 2.0$) and top-to-bottom specular hairline gradient lighting (`QLinearGradient`).
  - Eliminates all jagged or harsh pixel boundaries on Windows high-DPI displays (125% / 150% / 200%).
- **Living Siri / Dynamic Island Audio Visualizer**:
  - Replaced static dots with dual-harmonic traveling sine waveforms across 7 formant-weighted bars.
  - Continuous ambient traveling wave keeps the waveform fluidly undulating between 4.2 px and 9.7 px during listening.
  - Non-linear vocal dynamic expansion (lvl^0.35) dynamically lifts middle bars up to 20 px during voice speech.
- **Dynamic Language Badge & Option A Layout Fixes**:
  - Dynamically sized language badge (`_update_badge_text`) with proportional padding; fixes letter-clipping on `"EN-IN"`.
  - Cleanly decoupled text labels from compact and micro layouts to ensure zero phantom widget spacing or overlap.
- **Jitter-Free Centered Capsule Morphing**:
  - Geometry interpolation anchored directly to bottom-center during snooze expansion and contraction; eliminates multi-pixel jumps.
  - Isolated multi-screen mouse tracking animation (`screen_fade_anim`) preventing fade animation collisions across monitors.
- **Native Odia Voice Dictation & Offline Translation**:
  - Built-in support for Odia speech dictation and offline Odia-to-English translation.
- **Local Model Meeting Notes & In-Place Voice Edits**:
  - Select text and command rewrites locally with built-in Qwen2.5-1.5B-Instruct running on CTranslate2.

---

# OpenFlow v1.1.5 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.1.5
- **Resolved Startup Crash (`attempted relative import` & `No module named 'main'`)**:
  - Re-architected all module imports across `main.py`, `ui/floating_pill.py`, `ui/main_window.py`, `ui/setup_dialog.py`, and `ui/styles.py` with dual-mode packaging fallbacks.
  - Removed faulty runtime dummy module registration in `packaging/entry.py` that conflicted with PyInstaller's `PyiFrozenImporter`.
  - Added multi-tiered fallback importing with detailed diagnostic logging into `%USERPROFILE%\.openflow\crash.log`.
- **Bulletproof CI/CD Windows Packaging**:
  - Resolved GitHub Actions runner folder capitalization discrepancy (`OpenFlow` vs `openflow`) with non-recursive parent directory junction and standard non-editable wheel installation (`pip install . --no-deps`).
  - Guaranteed 100% static collection of all 32+ OpenFlow submodules into `PYZ.pyz`.
- **Low-End Hardware Inference Acceleration**:
  - Fully tested fast greedy CPU transcription (`beam_size=1`, `temperature=0.0`) cutting processing latency by >65% on AMD Ryzen 5 & Intel laptops.
  - SMT/hyperthreading core-pinning preventing CPU cache thrashing.
- **Installer Auto-Relaunch on Background Update**:
  - Silent updater runs post-install relaunch (`WizardSilent` check) so OpenFlow comes back online immediately after silent update.

---

# OpenFlow v1.1.4 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.1.4
- **Low-End & CPU Laptop Optimization (AMD Ryzen & Intel Core)**:
  - Optimized CPU inference for devices like Acer Aspire Lite (AMD Ryzen 5, integrated Radeon graphics) with 65%+ latency reduction.
  - Implemented dynamic beam sizing (`beam_size=1` greedy search on CPU with `temperature=0.0`) to avoid costly autoregressive decoding passes and thermal throttling.
  - Physical-core aware threading (`_physical_cores`) to prevent OpenMP hyperthread cache thrashing.
- **Fixed `ModuleNotFoundError: No module named 'openflow'` Startup Crash**:
  - Replaced problematic filesystem junction recursion with official Python `setup.py` editable packaging (`pip install -e . --no-deps`).
  - Added robust multi-tiered fallback imports in `packaging/entry.py` ensuring `openflow.main` is always resolved in frozen executables.
- **Installer Auto-Relaunch on Update**:
  - Added `Check: WizardSilent` in Inno Setup script so OpenFlow automatically relaunches immediately after silent background updates complete.

---

# OpenFlow v1.1.3 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.1.3
- **Robust Package Resolution for Standalone Windows Build**:
  - Implemented automated package junction resolution (`mklink /J openflow .`) ensuring all root modules and subpackages (`openflow.main`, `openflow.config`, `openflow.engine.*`, `openflow.ui.*`) are statically bundled into the frozen executable without namespace conflicts.
  - Eliminated `ModuleNotFoundError: No module named 'openflow'` on boot.
  - Hardened packaging pipeline with recursive artifact cleanup before compilation.

---

# OpenFlow v1.1.2 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.1.2
- **Fix Frozen Executable Package Resolution**:
  - Fixed PyInstaller module search path conflict that caused `ModuleNotFoundError: No module named 'openflow'` on startup in v1.1.1.
  - Ensured `openflow` package structure is properly packaged in standalone frozen builds.
  - Clean installer lifecycle and auto-update flow.

---

# OpenFlow v1.1.1 — Maintenance & In-App Auto-Update Fix

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.1.1
- **Seamless In-App Auto-Update & Process Lifecycle**:
  - Resolved update re-prompt loop by ensuring setup packages always bundle clean, freshly compiled binaries.
  - Implemented immediate process release (`os._exit(0)`) and Inno Setup `/FORCECLOSEAPPLICATIONS` flags to eliminate Windows executable file sharing locks during auto-updates.
- **Expanded Autonomous Meeting Intelligence**:
  - Full background detection for WhatsApp Desktop calls and meetings.
  - Expanded browser meeting hooks across Chrome, Edge, Brave, Opera, Vivaldi, and Firefox with self-exclusion to avoid audio feedback.
- **Improved Multilingual Dictation**:
  - Refined context prompting for Indian English, Hinglish, and Odia script accuracy.

---

# OpenFlow v1.1.0 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.1.0
- **On-Device NPU Acceleration (Intel AI Boost / OpenVINO)**:
  - Native support for on-device Neural Processing Units (NPUs) on Windows 11 Copilot+ hardware.
  - Sub-2W ultra-low power execution for all-day voice dictation and background meeting transcription without fan spin or battery drain.
  - Automatic hardware detection and fail-safe fallback to NVIDIA CUDA or AVX2 CPU.
- **Apple-Grade Capsule HUD Redesign**:
  - Re-architected translucent dark HUD material with inset grouped cards, 8pt spacing grid, and system typography.
  - iOS-style fluid toggle switches (`QVariantAnimation`, 220ms critically damped easing).
  - macOS-style popover menus with leading accent checkmarks and responsive model size indicators.
- **Silent Boot (Capsule-First Launch)**:
  - Boots straight into the subtle desktop capsule HUD without opening the heavy dashboard window.
  - Full dashboard opens smoothly on-demand from tray or capsule actions.
- **Interactive Press-to-Record Hotkey Box**:
  - Replaced manual text hotkey entry with a dedicated press-to-record input box in Settings.
  - Safely pauses global hooks during key recording to prevent hotkey capture collisions.
- **Deterministic User-Controlled Model Management**:
  - OpenFlow now strictly downloads only what the user explicitly selects.
  - Resolves cached variant aliases (`base` ⇄ `base.en`) without triggering unwanted background downloads.
  - Status feedback guides users directly to the Model Library when a variant isn't cached.

---

# OpenFlow v1.0.0 — Standalone Windows Release

### Zero-Limit · 100% Offline · Local AI Voice Dictation & Meeting Intelligence for Windows
**Architected and Created by Sachidananda**

---

### Highlights in v1.0.0
- **Standalone Windows Installer (`OpenFlow-Setup.exe`)**:
  - Single-file 94.7 MB installer with automatic Start Menu and Desktop shortcuts.
  - Installs cleanly to `{localappdata}\OpenFlow` without requiring Administrator/UAC elevation.
- **Hardware-Accelerated Realtime Inference**:
  - Sub-150ms transcription latency powered by CTranslate2 `float16` kernels on NVIDIA GeForce RTX GPUs.
  - Dynamic GPU hardware detection for all NVIDIA RTX/GTX GPUs with automatic DirectML and AVX2 CPU fallback.
- **Dynamic Island Floating Capsule HUD**:
  - Translucent glassmorphic overlay that never steals focus from active windows.
  - Smooth 360ms OutCubic easing morphing between compact capsule, desktop stealth line, and Apple Control Center HUD.
  - Real-time reactive audio waveform meters and volume monitoring.
- **Autonomous Meeting Mode**:
  - Background window detection for Google Meet (Chrome/Edge), Zoom, Microsoft Teams, and Cisco Webex.
  - Automatic transcript segmentation and structured executive notes formatting (Agenda, Discussion Points, Decisions & Action Items, Next Steps).
  - Persistent SQLite meeting storage with one-click clipboard copy and HTML preview.
- **Win32 Hardware Microphone Hotplug**:
  - Direct Windows `winmm` kernel polling for instantaneous USB/Bluetooth mic connect and disconnect events.
  - Companion animated notification pill and automatic primary audio switching.
  - Filters out inactive Bluetooth artifacts and duplicate audio driver aliases.
- **Multi-Tone Intelligent Text Refiner**:
  - **Smart Clean**: Strips hesitations and filler words (*"um"*, *"uh"*, *"like"*), fixes punctuation.
  - **Developer / Code**: Voice-coding syntax (*"camel case get user id"* ➔ `getUserId`, arrows, brackets).
  - **Email & Formal**: Adds professional structure, greetings, and sign-offs.
  - **Bullet Points**: Converts thought streams into structured Markdown bullets.
  - **Verbatim**: Literal raw speech without modification.
- **Linguistic Precision for Indic Languages**:
  - Context prompt injection for Hindi and Odia ensuring natural Devanagari and Odia script rendering instead of phonetic drift.
  - Support for 99+ languages with automatic language identification.

---

### Installation & Verification
1. Download **`OpenFlow-Setup.exe`** below.
2. Run the installer and click **Install**.
3. Hold **`Ctrl + Shift`** in any application to dictate and release to insert.

#### Windows SmartScreen / Edge Download Notice
Because OpenFlow is a newly compiled open-source tool without an enterprise $500/year code-signing certificate, Microsoft Edge or Windows Defender SmartScreen may display:
> *"OpenFlow-Setup.exe isn't commonly downloaded. Make sure you trust OpenFlow-Setup.exe before you open it."*

- **In Microsoft Edge / Chrome**: Click `...` next to the download > Click **Keep** > Click **Show more** > Click **Keep anyway**.
- **In Windows SmartScreen**: Click **More info** > Click **Run anyway**.
- **Verify File Integrity (SHA-256)**:
  ```powershell
  Get-FileHash OpenFlow-Setup.exe -Algorithm SHA256
  ```
  Expected SHA-256: `D3B7514CCA021E5A4FFB9737B5D69C261A06B1D7C41530FE5A77314EB5C418DB`

---
**Full Documentation & Collaboration Guide**: [https://github.com/Sachin1724/OpenFlow](https://github.com/Sachin1724/OpenFlow)

