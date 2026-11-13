# Voice Enrollment & Zero-Shot Odia Voice Cloning Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the female voice acoustic degradation and fumbles, and build an end-to-end, native Voice Enrollment & Zero-Shot Voice Cloning System under the OpenFlow hood allowing users to enroll their voice, input paragraphs, and tune synthesis parameters (temperature, speed, style guidance) in crisp 24kHz studio quality.

**Architecture:** 
1. **Acoustic Recovery & Phonetic Alignment:** Eliminate intra-word `<blank>` ballooning by implementing context-aware token duration clamping and restoring clean booth speaker embeddings.
2. **Native Enrollment Engine (`openflow/engine/enrollment.py`):** Ingests 5–15s reference audio via microphone or file, validates SNR/RMS, extracts 192-dim deep speaker embeddings via ERes2Net ONNX, and computes a 64-dim continuous acoustic conditioning vector.
3. **Continuous Cloned Voice Synthesis (`openflow/engine/cloned_voice.py`):** Injects enrolled speaker vectors directly into the MultiCondMatcha text encoder and CFM flow-matching decoder, exposing Euler ODE stochasticity (`temperature`), duration scale (`speed`), and style guidance.
4. **Interactive Audition Console (`openflow/enroll_voice.py` + `ENROLL_VOICE.bat`):** A zero-dependency CLI/TUI studio for recording, enrolling, tuning, and generating audio.
5. **Production Readiness:** ONNX Runtime / TensorRT optimization, CPU fallback, and multi-platform deployment roadmap.

**Tech Stack:** PyTorch, TorchAudio, ONNX Runtime, NumPy, SoundFile, SoundDevice, Safetensors, Vocos 24kHz.

---

### Task 1: Fix Female Voice Regression & Inter-Character Blank Ballooning

**Root Cause Confirmed by Empirical Diagnostics:**
1. In `indic-tiny-tts`, blank tokens (ID 0) are placed between every character.
2. The fine-tuning on noisy podcast clips caused predicted durations for intra-word `<blank>` tokens to balloon from 1–2 frames up to 8.9 frames (~95ms dead air between letters of the same word).
3. The starting `<blank>` token exploded to 56.1 frames (600ms dead silence) vs 2.3 frames (24ms) in the male model.
4. When multiplied by `human_1x_scale = 1.47`, these dead frames created stuttering ("fumbles") and consonant slurring in Odia ligatures (*ସ୍ୱାଗତ*, *ରେଷ୍ଟୁରାଣ୍ଟ*).
5. The speaker embedding `spk_emb.weight` was shifted away from the pure booth timbre by multi-speaker podcast contamination.

**Files:**
- Modify: `openflow/engine/studio_voice.py:122-161, 195-207`
- Create: `openflow/tests/test_female_clarity.py`

**Step 1: Write the failing test**
Create `openflow/tests/test_female_clarity.py` to assert that:
- Intra-word blank token durations are clamped to $\le 2.0$ frames.
- Sentence initial and terminal blanks are clamped to $1.0$ frame.
- Female benchmark synthesis completes with crisp, continuous articulation (duration between 4.0s and 4.6s for standard sentence, max amplitude $\ge 0.85$, zero intra-word pauses $> 40\text{ms}$).

```python
import pytest
import numpy as np
import soundfile as sf
from engine.studio_voice import StudioVoiceEngine

def test_female_voice_clarity_and_duration():
    sv = StudioVoiceEngine("female")
    text = "ନମସ୍କାର ! ମୁଁ ମୀରା । ଆପଣ କେମିତି ଅଛନ୍ତି ? ଆଜି ଆପଣଙ୍କ ଦିନ କିପରି କଟିଲା ?"
    wav = sv.synthesize(text, voice="female", speed=1.0)
    dur = len(wav) / 24000.0
    
    # 67 characters at ~15 chars/s should be between 3.8s and 4.6s
    assert 3.8 <= dur <= 4.8, f"Duration {dur:.2f}s is abnormal (expected 3.8s - 4.8s)"
    assert np.max(np.abs(wav)) >= 0.85, "Audio failed peak normalization (-1.0 dBFS)"
    
    # Check that there are no long internal dropouts (>60ms) inside speech
    win = int(0.04 * 24000)
    hop = int(0.02 * 24000)
    energies = [np.sum(wav[i:i+win]**2) for i in range(win, len(wav) - win, hop)]
    zero_runs = sum(1 for e in energies if e < 1e-5)
    assert zero_runs == 0, f"Found {zero_runs} dead silence dropouts inside continuous speech"
```

**Step 2: Run test to verify failure**
Run: `pytest openflow/tests/test_female_clarity.py -v`
Expected: FAIL due to duration bloat (>5.5s) or internal dropout warnings.

**Step 3: Implement context-aware duration clamping & timbre recovery in `studio_voice.py`**
- Replace the coarse `human_1x_scale = 1.47` with context-aware duration control:
  - Initial/trailing `<blank>`: clamped to $1.0$ frame.
  - Inter-character `<blank>` (between phonemes in a word): strictly clamped to $\le 2.0$ frames (~21ms).
  - Word boundary `<blank>` (adjacent to space): clamped to $\le 3.0$ frames (~32ms).
  - Space tokens: clamped to $\le 5.0$ frames (~53ms).
  - Punctuation tokens (`।`, `?`, `!`): clamped to $\le 8.0$ frames (~85ms).
- Add `temperature: float = 0.667` argument to `synthesize()`.
- Use the restored pristine speaker embedding for `or_F`.

**Step 4: Run test to verify it passes**
Run: `pytest openflow/tests/test_female_clarity.py -v`
Expected: PASS with 4.18s duration and crisp speech.

**Step 5: Regenerate Benchmark Audio Files**
Run: `python -c "from engine.studio_voice import StudioVoiceEngine; sv = StudioVoiceEngine('female'); wav = sv.synthesize('ନମସ୍କାର ! ମୁଁ ମୀରା । ଆପଣ କେମିତି ଅଛନ୍ତି ? ଆଜି ଆପଣଙ୍କ ଦିନ କିପରି କଟିଲା ?', voice='female'); sv.save_wav(wav, 'openflow/scratch/benchmark_results/normal_female.wav')"`

---

### Task 2: Build the Native Voice Enrollment Engine (`openflow/engine/enrollment.py`)

**Goal:** Create a standalone voice enrollment subsystem that validates audio, extracts 192-dim speaker embeddings via ERes2Net, computes fundamental acoustic characteristics, and persists structured speaker profiles.

**Files:**
- Create: `openflow/engine/enrollment.py`
- Create: `openflow/data/enrolled_speakers/`
- Test: `openflow/tests/test_enrollment.py`

**Key Components of `VoiceEnrollmentManager`:**
1. `validate_audio(wav: np.ndarray, sr: int) -> Tuple[bool, str, Dict]`:
   - Enforces: duration between 3.0s and 30.0s.
   - Enforces: RMS energy $\ge 0.015$ (rejects empty or ultra-quiet microphones).
   - Enforces: SNR $\ge 12.0\text{ dB}$.
   - Detects clipping ($|x| \ge 0.99$).
2. `preprocess_audio(wav: np.ndarray, sr: int) -> np.ndarray`:
   - Resamples to 24,000 Hz mono.
   - Trims leading/trailing silence using energy-based VAD.
   - Applies peak normalization to -1.0 dBFS.
3. `extract_speaker_embedding(wav_24k: np.ndarray) -> np.ndarray`:
   - Uses `C:\Users\sachi\.openflow\models\speaker-eres2net.onnx` via ONNX Runtime.
   - Generates L2-normalized 192-dimensional speaker identity vector.
4. `compute_latent_adapter_vector(embedding_192: np.ndarray, gender: str) -> np.ndarray`:
   - Projects 192-dim ERes2Net vector into 64-dim `spk_emb` latent space aligned with MultiCondMatcha.
   - Seeds from calibrated centroid of base booth speaker (`or_F` or `or_M`) shifted along the principal acoustic components of the user's vocal timbre.
5. `enroll_speaker(name: str, audio_path_or_array, gender: str = "auto") -> Dict`:
   - Creates `openflow/data/enrolled_speakers/<speaker_id>.json`.
   - Saves clean reference WAV to `openflow/data/enrolled_speakers/<speaker_id>_ref.wav`.

**Testing Steps:**
- Test enrollment from existing reference WAV (`openflow/models/female_voice_reference.wav`).
- Verify profile JSON schema, embedding dimensionality (192-dim and 64-dim), and cosine similarity metrics.

---

### Task 3: Build the Parameterized Zero-Shot Cloned Voice Synthesis Engine (`openflow/engine/cloned_voice.py`)

**Goal:** Build the engine that takes an enrolled speaker ID (or reference audio) and generates speech for arbitrary paragraphs with full parameter control (temperature, speed, guidance).

**Files:**
- Create: `openflow/engine/cloned_voice.py`
- Test: `openflow/tests/test_cloned_voice.py`

**Key Features:**
1. **Dynamic Vector Conditioning:**
   Instead of indexing a frozen lookup table row, `ClonedVoiceEngine` builds a continuous conditioning tensor:
   $$\mathbf{c} = [\mathbf{e}_{\text{lang}}(32) \,\|\, \mathbf{e}_{\text{cloned}}(64) \,\|\, \mathbf{e}_{\text{style}}(16)] \in \mathbb{R}^{1 \times 112}$$
   Injected into:
   - RoPE Text Encoder (`encoder(x, x_lengths, spks=c)`)
   - Duration Predictor (`encoder.proj_w`)
   - Flow-Matching U-Net Decoder (`decoder(mu_y, y_mask, n_timesteps, temperature, spks=c)`)
2. **Euler ODE Stochasticity (`temperature`):**
   - $T \in [0.1, 1.2]$:
     - $T = 0.1 - 0.3$: High precision, deterministic, steady pacing.
     - $T = 0.667$ (default): Natural human prosodic variance.
     - $T = 0.9 - 1.1$: Highly expressive, animated intonation.
3. **Pacing Control (`speed`):**
   - Range $0.75\text{x}$ to $1.5\text{x}$ with smooth alignment preserving relative phoneme durations.
4. **Paragraph Synthesis & Continuous Blending:**
   - Splits long paragraphs (>300 chars) at syntactic clause boundaries.
   - Blends adjacent sentences using 50ms equal-power crossfades.
   - Overlays micro-acoustic room floor (-52 dBFS).

**Testing Steps:**
- Synthesize test paragraph with `speaker_id="elina_samantray"` at $T=0.3$, $T=0.667$, and $T=1.0$.
- Verify that pitch and duration vary smoothly with temperature without audio clipping or phase artifacts.

---

### Task 4: Interactive Enrollment & Audition Console (`openflow/enroll_voice.py` + `ENROLL_VOICE.bat`)

**Goal:** Provide an intuitive local tool for users to record their microphone, enroll audio, type Odia/English paragraphs, adjust temperature and speed, and listen to the cloned output.

**Files:**
- Create: `openflow/enroll_voice.py`
- Create: `openflow/ENROLL_VOICE.bat`

**Console Workflow:**
```
================================================================================
          🎙️ MIRA STUDIO: ZERO-SHOT ODIA VOICE ENROLLMENT & CLONING CONSOLE
================================================================================
Enrolled Voices:
  [1] MIRA Female Anchor (Smita Mohanty) - Default Studio Female
  [2] MIRA Male Anchor (Kishore Kumar) - Default Studio Male
  [3] Elina Samantray (Harvested Studio Podcast Voice)
  [4] User Cloned Voices (from data/enrolled_speakers/)

Actions:
  [E] Enroll New Voice via Microphone (10-second live prompt)
  [F] Enroll New Voice from Audio File (.wav / .mp3)
  [S] Synthesize Paragraph with Cloned Voice
      - Select Voice
      - Enter Paragraph
      - Set Temperature (0.1 - 1.2, default 0.67)
      - Set Speed (0.8 - 1.3, default 1.0)
  [P] Play & Audition Existing Cloned Samples
  [Q] Quit
```

---

### Task 5: Production Readiness & Model Optimization Strategy

**Goal:** Establish technical benchmarks and deployment requirements for taking MIRA models to production.

**Deliverables:**
1. **Inference Latency Profile (RTX 4050 vs CPU vs NPU):**
   - Measure Real-Time Factor (RTF) across sentence lengths:
     - First-chunk latency (Time-to-First-Audio, TTFA) $\le 120\text{ms}$.
     - Overall RTF on RTX 4050: $\le 0.08$ (generates 10s audio in $< 0.8\text{s}$).
2. **Memory Footprint:**
   - MultiCondMatcha: 8.9M parameters (~35 MB FP32 / 18 MB FP16).
   - Vocos 24kHz Vocoder: 13.5M parameters (~54 MB FP32 / 27 MB FP16).
   - ERes2Net Speaker Model: ~39 MB ONNX.
   - Total VRAM: $< 250\text{ MB}$ (ultra-lightweight, easily runs on edge hardware).
3. **Packaging & Offline Edge Deployment:**
   - Standalone ONNX runtime export for Matcha acoustic model + Vocos vocoder.
   - Complete local offline execution without internet connection.
   - Update `PROGRESS_REPORT.md` with benchmark numbers and verified audio specs.

---

### Execution Protocol
1. User reviews and approves this plan.
2. Step-by-step implementation:
   - Fix female fumbles in `studio_voice.py` and verify audio.
   - Build `enrollment.py` and write unit tests.
   - Build `cloned_voice.py` and test paragraph synthesis with temperature tuning.
   - Build `enroll_voice.py` and `ENROLL_VOICE.bat`.
   - Update `PROGRESS_REPORT.md`.
3. Discuss final production readiness with user.

