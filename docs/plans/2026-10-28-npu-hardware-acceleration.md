# Plan: NPU Hardware Acceleration & DirectML/OpenVINO Execution

**Goal:** Enable OpenFlow to detect and utilize on-device Neural Processing Units (NPUs) on Windows 11 (Intel AI Boost, AMD Ryzen AI, Qualcomm Snapdragon X Elite Hexagon), achieving sub-2W power efficiency, zero fan noise, and uncompromised dictation latency without competing with foreground CPU/GPU workloads.

---

## Executive Summary & Feasibility

### Can we implement this?
**Yes.** OpenFlow can fully support NPU execution. 

### Why is this high-impact for OpenFlow?
- **Ultra-Low Power / Battery Saver:** Continuous voice dictation or meeting intelligence on an NVIDIA GPU draws **30W–60W** (spinning up laptop fans and draining battery). Multi-threaded CPU execution draws **15W–35W** and spikes thread queues. An NPU executes INT8/INT4 matrix math at **1.5W–3.5W**, enabling all-day dictation on battery.
- **Zero Workload Contention:** Because the NPU runs on dedicated silicon (MCDM / Level Zero), it does not compete with GPU shaders or CPU cores during heavy workloads (compiling code in VS Code, gaming, 3D rendering).
- **Targeting Copilot+ PCs:** Directly supports the modern wave of Windows 11 laptops (Intel Core Ultra, AMD Ryzen AI 300 / Strix Point, Snapdragon X Elite).

### The Core Architectural Challenge & Solution
- **The Challenge:** OpenFlow's default transcription backend is `faster-whisper`, powered by `CTranslate2`. **CTranslate2 only compiles for CPU and CUDA.** It has zero native support for DirectML, OpenVINO, QNN, or NPUs. Passing `device="npu"` directly to CTranslate2 will fail.
- **The Solution:** Implement a dual-engine ASR architecture:
  1. **NVIDIA GPUs & Legacy CPU:** Retain `faster-whisper` (CTranslate2) for float16 CUDA execution and int8 AVX2 CPU execution.
  2. **NPU Engine:** Add an ONNX Runtime / OpenVINO / Sherpa-ONNX execution backend configured for DirectML (`DmlExecutionProvider`), OpenVINO (`OpenVINOExecutionProvider`), or Qualcomm QNN (`QNNExecutionProvider`) with INT8 quantized Whisper/Parakeet models.
  3. **Auto Fallback:** If NPU device compilation fails or drivers are uninitialized, gracefully fall back to GPU or CPU without interrupting the user.

---

## Architecture Diagram

```
                 [ User Audio Input: 16 kHz mono float32 ]
                                    │
                                    ▼
                       [ engine/hardware.py ]
         Probes: Win32_PnPEntity / MCDM DirectML / OpenVINO / QNN
                                    │
         ┌──────────────────────────┼──────────────────────────┐
         ▼                          ▼                          ▼
  NVIDIA CUDA dGPU             Windows NPU                 Host CPU
  (RTX 30/40/50 series)   (Intel / AMD / Qualcomm)   (AVX2 / Vectorized)
         │                          │                          │
         ▼                          ▼                          ▼
   CTranslate2               ONNX Runtime /               CTranslate2
   (faster-whisper)            DirectML /                 (int8 / _THREADS)
   [float16 kernel]            OpenVINO
                              [INT8 ASR]
         │                          │                          │
         └──────────────────────────┼──────────────────────────┘
                                    ▼
                    [ Formatter & Tone Refiner ]
                                    │
                                    ▼
                   [ Win32 Text Injection / HUD ]
```

---

## Task Breakdown

### Task 1: NPU Hardware Detection & Driver Probing (`openflow/engine/hardware.py`)

**Objective:** Inspect the host PC at startup for supported NPU hardware, vendor identity, driver health, and estimated TOPS.

**Implementation Details:**
1. **Multi-tier Detection Pipeline:**
   - **Tier 1 (Fast Windows PnP & CIM Scan):** Query `Win32_PnPEntity` for known NPU device strings and PCI Vendor IDs:
     - Intel: `Intel(R) AI Boost` (PCI `VEN_8086&DEV_7D1D`, `DEV_AD1D`)
     - AMD: `AMD IPU Device`, `AMD NPU Device` (PCI `VEN_1022&DEV_1502`, `DEV_17F0`)
     - Qualcomm: `Snapdragon(R) X ... NPU`, `Qualcomm(R) Hexagon(TM) NPU`
   - **Tier 2 (Runtime Provider Probe):** Check if `onnxruntime` or `openvino` detects an active NPU accelerator:
     - For OpenVINO: Check `'NPU' in ov.Core().available_devices`
     - For DirectML: Check `IDMLDevice` capability or `onnxruntime-directml` adapter enumeration.
     - For QNN: Check if `QNNExecutionProvider` is in `ort.get_available_providers()`.
2. **Update `detect()` return signature:**
   ```python
   {
       "gpu_name": ...,
       "cuda_ok": ...,
       "npu_name": "Intel(R) AI Boost" | "AMD Ryzen AI NPU" | "Qualcomm Hexagon NPU" | "",
       "npu_ok": True / False,
       "npu_vendor": "intel" | "amd" | "qualcomm" | "",
       "npu_provider": "openvino" | "dml" | "qnn" | "",
       "device": "cuda" | "npu" | "cpu",
       ...
   }
   ```
3. **Smart Priority Resolution in `resolve(cfg)`:**
   - If user explicitly sets `device="npu"`, use NPU if `npu_ok`, else fallback with diagnostic note.
   - If `device="auto"`:
     - On AC power with high-end NVIDIA GPU: Prioritize CUDA for maximum raw throughput.
     - On battery or on thin-and-light laptop with NPU (and no dGPU): Prioritize NPU for battery conservation.

---

### Task 2: NPU Model Packaging & Quantization (`openflow/engine/model_manager.py`)

**Objective:** Manage lightweight INT8/INT4 quantized models specifically optimized for NPU neural compute pipelines.

**Implementation Details:**
1. **Model Format for NPU:**
   - Standard PyTorch or CTranslate2 `.bin` files cannot be dispatched to NPUs.
   - NPU accelerators require computational graphs compiled into ONNX format (`.onnx`) or OpenVINO Intermediate Representation (`.xml` / `.bin`).
   - Standardize on:
     - Whisper Base INT8 ONNX (Encoder + Decoder + Tokenizer) ~140 MB.
     - Parakeet TDT INT8 ONNX (already used by OpenFlow via `sherpa-onnx`) ~670 MB.
2. **Model Download & Storage:**
   - Dedicated cache directory: `~/.openflow/models/npu/`
   - Metadata registry: Add entries to `_MODELS` with NPU-compatible URLs (e.g. Hugging Face Optimum / Olive Whisper ONNX).
   - Validation: Strict SHA-256 integrity check and size verification before loading.
3. **Hardware Compilation Cache:**
   - NPUs compile ONNX graphs into low-level microcode on first run.
   - Configure model cache paths (`cl_cache` for Intel / QNN context binary cache) in `~/.openflow/cache/` so subsequent app launches load in <300ms.

---

### Task 3: Dual-Engine Transcriber Pipeline (`openflow/engine/transcriber.py`)

**Objective:** Implement a dedicated `NPUTranscriberEngine` that integrates into `Transcriber` seamlessly without breaking existing CUDA/CPU workflows.

**Implementation Details:**
1. **Engine Interface:**
   - Define a shared contract: `transcribe(audio_np: np.ndarray, language: str) -> Tuple[str, dict]`
2. **NPU Engine Implementations:**
   - **Path A: DirectML / ONNX Runtime (`NPUOnnxTranscriber`):**
     - Uses `onnxruntime-directml` with DirectML device index targeting the NPU compute adapter.
     - Handles mel-spectrogram feature extraction -> ONNX encoder -> greedy search / ONNX decoder.
   - **Path B: OpenVINO NPU Engine (`NPUOpenVINOTranscriber`):**
     - For Intel Core Ultra systems: uses `openvino-genai.WhisperPipeline(model_path, device="NPU")`.
     - Extremely clean, native C++ bindings, zero Python overhead.
   - **Path C: Sherpa-ONNX NPU Acceleration:**
     - OpenFlow already imports `sherpa-onnx`. Sherpa-ONNX supports `provider="openvino"` or `provider="directml"`. We can initialize `sherpa_onnx.OfflineRecognizer` pointing to the DirectML/NPU provider.
3. **Fail-Safe Fallback:**
   - If NPU initialization or memory allocation fails at runtime:
     - Log warning: `[OpenFlow] NPU execution failed, failing over to CPU int8...`
     - Automatically switch `self.device = "cpu"` and load standard CTranslate2 CPU model.
     - Notify UI via `self.on_status("NPU unavailable · Falling back to CPU")`.

---

### Task 4: Configuration & Battery Awareness (`openflow/config.py`)

**Objective:** Expose NPU settings and provide intelligent power-profile awareness.

**Implementation Details:**
1. **Config Keys in `DEFAULT_CONFIG`:**
   ```python
   DEFAULT_CONFIG = {
       "device": "auto",                    # auto, cuda, npu, cpu
       "prefer_npu_on_battery": True,      # When on battery, switch from GPU to NPU to save power
       "npu_provider": "auto",              # auto, directml, openvino, qnn
       ...
   }
   ```
2. **Battery State Polling:**
   - Using `psutil.sensors_battery()`, detect when laptop disconnects from AC power.
   - If `prefer_npu_on_battery` is enabled and NPU is present, seamlessly switch active worker to NPU.

---

### Task 5: UI & Capsule HUD Integration (`openflow/ui/`)

**Objective:** Provide intuitive device selection and feedback in the Settings dashboard and floating capsule HUD.

**Implementation Details:**
1. **Setup Dialog (`ui/setup_dialog.py`):**
   - Populate `self.device` combo box dynamically:
     - `Run on: Automatic (recommended)`
     - `Run on: NPU (Intel AI Boost / AMD Ryzen AI / Qualcomm)` *(only enabled if NPU detected)*
     - `Run on: GPU (NVIDIA CUDA)` *(only enabled if NVIDIA GPU detected)*
     - `Run on: CPU`
2. **Main Dashboard (`ui/main_window.py`):**
   - In Settings > Compute Hardware:
     - Display hardware badge with NPU vendor, driver version, and estimated TOPS.
     - Add checkbox: `Prioritize NPU on battery power (saves up to 80% battery)`.
3. **Floating Capsule HUD (`ui/floating_pill.py`):**
   - When transcribing on NPU:
     - Display subtle cyan/violet neural badge: `● NPU Active · 2W`.
     - In expanded HUD settings popover, show device selection with NPU status.

---

### Task 6: Packaging, PyInstaller & Binary Distribution (`build_exe.py`, `OpenFlow.spec`)

**Objective:** Ensure standalone Windows installer and portable `.exe` bundle required runtimes cleanly without bloated file size or missing DLL errors.

**Implementation Details:**
1. **Dynamic Runtime Resolution:**
   - Don't hard-require every vendor SDK in base bundle.
   - Use dynamic imports with graceful degradation:
     - If `onnxruntime-directml` or `openvino` is present in Python environment, enable NPU.
     - If missing, show user-friendly "One-Click Install NPU Driver" button in Settings.
2. **PyInstaller Spec (`OpenFlow.spec`):**
   - Include binaries and providers:
     - `directml.dll`
     - `onnxruntime_providers_shared.dll`, `onnxruntime_providers_dml.dll`
   - Exclude unnecessary training symbols to preserve compact download size (<120 MB installer).

---

## Verification & Testing Plan

### Automated Test Suite
- **`test_npu_detection.py`:**
  - Mock CIM / WMI output for Intel AI Boost, AMD IPU, and Qualcomm Snapdragon.
  - Verify `hardware.detect()` correctly parses vendor, model, and availability flags.
- **`test_npu_transcriber_fallback.py`:**
  - Simulate NPU driver initialization failure; verify automatic fallback to CPU without crash or lost audio.
- **`test_battery_aware_resolver.py`:**
  - Verify that `hardware.resolve()` prefers NPU when `power_plugged == False` and `prefer_npu_on_battery == True`.

### Manual Acceptance Criteria
1. On a machine with an NPU (or mocked NPU driver):
   - Selecting "NPU" in Settings successfully loads the model.
   - Holding hotkey and speaking transcribes accurately into active window.
   - Windows Task Manager > Performance tab shows compute utilization on the **NPU** graph, while CPU remains <5% and GPU remains 0%.
2. On a machine without an NPU:
   - "NPU" option is disabled or marked "Not Detected" with informative tooltip.
   - App launches smoothly without errors or missing DLL popups.
