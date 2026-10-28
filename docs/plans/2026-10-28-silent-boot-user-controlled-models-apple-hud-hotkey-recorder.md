# Plan: Silent Boot, User-Controlled Model Downloads, Apple-Style HUD, Hotkey Recorder

**Goal:** (1) Boot shows only the capsule, never the dashboard. (2) A model is downloaded only when the user explicitly asks for it. (3) Redesign the capsule HUD to Apple (iOS/macOS) standards. (4) Replace the hotkey text field with a press-to-record key box.

---

## Task 1: Boot to capsule only

**Root cause:** the dashboard is opened twice on every launch:
- `main.py:870` `run()` calls `self.show_dashboard()` unconditionally.
- `main.py:991` `main()` calls `QTimer.singleShot(400, app.show_dashboard)` unless `--background`.

**Change:**
- Delete both calls. The dashboard opens only from the tray (click / "Open Dashboard"), the capsule's "Open Dashboard" action, or a second launch (`on_second_launch`, already wired).
- Drop the startup tray balloon in `run()` (`main.py:872-877`); the capsule's "Ready" message is enough.
- The `--background` flag becomes a no-op; keep accepting it so existing autostart shortcuts don't break.

**Check:** launch `python -m openflow`. Only the capsule appears, and the tray icon still opens the dashboard.

---

## Task 2: Download only what the user picked

**Root cause (confirmed by reading the code):**
1. `model_manager.list_downloaded_models()` (`engine/model_manager.py:219`) checks only the metadata ids (`base`, `tiny`, ...). For English (`language == "en"`), setup downloads **`base.en`**, so the list comes back empty.
2. `hardware.resolve()` (`engine/hardware.py:84-100`) gets that empty list, so with `model_size == "auto"` it falls back to the hardware recommendation (`small`, or `distil-large-v3` on a 10 GB GPU).
3. `Transcriber._load_model_locked()` (`engine/transcriber.py:111-117`) silently downloads any model that isn't cached. The same path runs when the language changes in the capsule (`base.en` becomes `base`, a new download) and when the GPU is hot-swapped.
4. Setup saves `model_size = "auto"` whenever "Quality: Automatic" is chosen (`ui/setup_dialog.py:150`). Every later boot then re-runs the auto logic above.

**Change:**
- `ui/setup_dialog.py:_finish`: save the **concrete** size that was downloaded (`tiny` / `base` / `small` / `medium` / `parakeet`), never `"auto"`.
- `engine/model_manager.py:is_model_downloaded(id)`: return True if `id` **or** `id + ".en"` is cached. This one change fixes `list_downloaded_models`, `resolve()` and the Model Library badges at the same time.
- `engine/transcriber.py:_load_model_locked`: **no implicit download.** If the target variant isn't cached, load the closest cached variant of the same size (`base` ⇄ `base.en`), then any cached model. Emit the status line `"<model> not downloaded · get it in Model Library"`. Download only when `model_manager.cached_path()` finds nothing at all, which means first run after a wiped cache.
- Explicit downloads stay as they are: Setup and Model Library both call `model_manager.download` directly, and that is the user's choice.
- Config migration: on load, if `setup_done` is true and `model_size == "auto"`, pin it to `hardware.resolve(cfg)["model_size"]` and save. This runs once.
- Meeting speaker model (`engine/meeting.py:203`): it already downloads only when the user starts meeting notes, which is an explicit action. No change.

**Check:** `test_model_resolution.py`, an assert-based script:
- When only `base.en` is cached, `hardware.resolve({"model_size": "auto", "language": "en"})["model_size"] == "base"`.
- When only `base.en` is cached, `is_model_downloaded("base")` is True.

Manual check: wipe every model except base, then boot, switch the language, and switch the GPU. Nothing should download.

---

## Task 3: Apple-style HUD redesign (`ui/floating_pill.py`, `ui/styles.py`)

The scope is the expanded capsule HUD (`_build_hud`, `ValueRow`, the `QMenu` popovers, the bottom buttons) plus the shared checkbox style in the dashboard. The rules below come from the apple-design skill, translated to Qt.

**Visual system (one token set at the top of `floating_pill.py`):**
- Material: dark translucent "HUD" material: `rgba(30,30,32,0.82)` + 0.5px top hairline `rgba(255,255,255,0.10)` + soft drop shadow. Grouped rows on one inset `FILL` card (iOS Settings "inset grouped"). No stacked translucent-on-translucent layers.
- Type: system font (Segoe UI Variable on Win11) instead of the bundled Inter/Poppins mix. Use one scale: title 15 semibold, row 13 regular, secondary 11 with +0.2px tracking. Row titles use primary white; values use 60% white.
- Spacing: an 8pt grid. Rows are 44px tall, insets 16px, card radius 12, popover radius 10. Separators are inset hairlines that start at the text, not at the card edge (already partly done).
- Color: a single accent `#0A84FF` (system blue, dark) for selection and toggles, `#30D158` for "on/active", and `#FF453A` for destructive actions. Remove the green→white gradient on the level bar; draw a plain accent fill instead.

**Controls:**
- **Single-choice lists (Mic, Language, Style, Model):** keep `ValueRow` (title, then value, then a `chevron.up.chevron.down` glyph). Restyle the popover as a macOS menu: 28px items, the checkmark **leading** in the accent color (`check.svg` recolored), the selected item in medium weight, hover as a rounded accent-tinted fill, and no indicator box. In the Model list, models that aren't downloaded show a trailing `↓ 141 MB` and are disabled in the capsule, which ties into Task 2.
- **Booleans (Hide when idle, and every dashboard `QCheckBox`):** replace the square or round checkbox with an **iOS switch**. Add a small `Switch(QAbstractButton)`: 38×22 track, white knob with a shadow, accent track when on. The knob moves with a critically damped animation (`QVariantAnimation`, 220 ms, `OutCubic`, no overshoot), the track color cross-fades, and toggling flips the state on press with no delay. This is one class reused in both the HUD and `main_window.py`.
- **Buttons:** three styles only. *Plain* (accent text, no fill) is for "Done" in the header, matching iOS. *Filled* (accent fill, white text, radius 8) is for Update and Download. *Destructive* uses red text. Every button scales to 0.97 / dims on **press** (`mousePressEvent`), not on release.
- **Header:** squircle icon 22px, "OpenFlow" title, and "Done" as a plain button on the right. Remove the `v1.0` badge; the version belongs in About.

**Motion:**
- The HUD expands from and collapses back into the capsule, along the same path with the same origin (spatial consistency). Use one critically damped curve (~300 ms) for geometry and opacity together. Start each animation from the **current** geometry, so a click mid-animation reverses smoothly instead of jumping.
- Popovers fade and scale from 0.96 anchored at their row (transform origin = trigger), over 150 ms.
- Respect Windows "Show animations" (`SystemParametersInfo SPI_GETCLIENTAREAANIMATION`): when it is off, use opacity cross-fades only.

**Check:** take screenshots of capsule idle, HUD open, each popover open, and switch on/off. Compare them against `docs/img/hud.png`, then update the docs image.

---

## Task 4: Press-to-record hotkey box (`ui/main_window.py`)

Replace `self.hotkey_input` (`main_window.py:732`) with a `HotkeyRecorder(QFrame)`.

**Behavior:**
1. **Idle:** a rounded rectangle shows the current combo as keycaps (`Ctrl` `Shift`) with a **×** close button on the right.
2. Click **×**: the combo is cleared and the box switches to *recording*. A blue focus ring appears, the placeholder reads "Press a shortcut…", and the box grabs the keyboard.
3. **Recording:** the box shows held keys live as keycaps. When **all keys are released**, the largest set held during the press is committed. This allows modifier-only combos like `ctrl+shift` as well as `alt+space` and `f8`. There is no text entry and no Enter key needed. `Esc` cancels and restores the previous combo.
4. **Commit:** save the config and call `hotkey_mgr.update_config()` right away through the existing `config_changed` signal. Remove the hotkey from the "Save settings" path.
5. While recording, **pause the global hotkey manager** (`hotkey_mgr.stop()`, then `start()` again after commit or cancel), so pressing Ctrl+Shift to record doesn't start a dictation. Add a `sig_hotkey_recording(bool)` signal to `MainWindow` and handle it in `main.py`.

**Key naming:** map Qt keys to the names `hotkey_manager` already understands. Modifiers map to `ctrl` / `shift` / `alt`, `Key_Space` to `space`, `Key_F1..F24` to `f1..f24`, and letters and digits to their lowercase character. Reject a single plain letter or digit with no modifier (it would hijack typing), and show an inline red hint.

**Follow-up in the same task:** the hard-coded "Hold Ctrl+Shift to Speak" strings (tray tooltip, capsule messages, dashboard badge in `main.py` and `main_window.py:95`) should read from `config["hotkey"]` through one `hotkey_label(cfg)` helper.

**Check:** add an assert self-check for the Qt-key-to-hotkey-string mapping. Manual check: record `ctrl+shift`, `alt+space` and `f8`, and confirm each one triggers dictation right away with no restart.

---

## Order and size
1. Task 1: about 5 lines, ship first.
2. Task 2: about 40 lines plus a test. This is the real bug.
3. Task 4: about 120 lines (new widget plus wiring).
4. Task 3: the largest (restyle plus `Switch` widget, about 250 lines changed). It is done last so screenshots reflect the final model and hotkey UI.

**Skipped:** a light-mode HUD (the app is dark-only today) and a per-model download queue. Add them when asked.
