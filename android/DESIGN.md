# OpenFlow for Android: design decisions

Style: the same Apple-like, dark, minimal look as the web and the Windows app. Pill is the one motif.
(From the ui-ux-pro-max pass: "AI-native" voice UI, minimal chrome, Inter, red recording dot + blue waveform.)

## Interaction (decided)
- A small **round button** appears beside a focused text field (accessibility service). Tap it to start.
- It opens a **capsule** just above the keyboard (or above the field if there is no keyboard): red dot, live
  waveform, language badge, a stop button. Words type into the field as they are recognised; release or tap to finish.
- No top-notch island on Android: camera cut-outs and status-bar rules differ per phone and overlays cannot draw
  there reliably. An island can come later as an option for centred punch-hole phones.
- Everything is draggable; the position is remembered per app.

## Tokens (Compose `colorScheme` + `Shapes`)
| Token | Dark | Light |
|---|---|---|
| background | #000000 | #FFFFFF |
| surface (capsule, sheets) | #1C1C1E | #F2F2F7 |
| surfaceVariant | #2C2C2E | #E5E5EA |
| onSurface | #FFFFFF | #000000 |
| onSurfaceVariant | 60% white | 60% black |
| accent (actions, waveform) | #0A84FF | #007AFF |
| recording | #FF453A | #FF3B30 |
| success | #30D158 | #34C759 |
Shapes: pill = 50% corners (buttons, chips, capsule); every card/sheet one radius, 24 dp.
Type: Inter (bundled), body 16 sp, labels 13 sp minimum. Spacing 4/8/16/24/32 dp.
Motion: 150-300 ms; spring open for the capsule; animate transform and alpha only; honour "remove animations".

## Accessibility and polish (checklist)
- Touch targets 48 dp or more; the floating button 56 dp.
- Every icon button has a `contentDescription`; the capsule announces "Listening" and "Done" (live region).
- Contrast 4.5:1 or better in both themes; never colour alone (recording = dot + the word "Listening").
- Animation lives in the UI layer, not the ViewModel.
- Respect Android's "Remove animations", font scale up to 200%, and TalkBack.

## Logo
Options in `brand/logo-options.html`: A Split O, B Flow O, C Pill O (recommended). White on black, one blue accent.
