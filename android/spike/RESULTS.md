# Android feasibility spike (31 Oct 2026)

Device: Realme RMX3031, MediaTek Dimensity 1200 (MT6893), 8 GB RAM, Android 13. CPU only, 4 threads, 10-12 s test clips
from Google FLEURS (public). Tools: Android NDK 26.1, whisper.cpp (q5_1 models), onnxruntime-android 1.19.2.

| Engine | Audio | Total time | Notes |
|---|---|---|---|
| Whisper tiny q5_1, English | 7.9 s | 3.2 s | |
| Whisper base q5_1, English | 7.9 s | 3.6 s | text exact; encoder is a fixed ~2.6 s (30 s window), `-ac 768` cuts it to 1.6 s |
| Whisper small q5_1, English | 7.9 s | 11.9 s | too slow for dictation |
| Whisper base q5_1, Hindi | 12.2 s | 10.7 s | fast enough, but 89% word errors on FLEURS Hindi (desktop run) |
| Whisper small q5_1, Hindi | 12.2 s | 26-32 s | accurate-ish, far too slow |
| **OpenFlow Odia (IndicConformer int8, ONNX)** | 10 s | **0.7 s** | RTF 0.07, 390 MB RSS, load 1.3 s; CTC beam + word list still to port |

Takeaways
- Indian languages: use the IndicConformer ONNX family (fast, accurate). Whisper is unusable for Hindi/Odia on this phone.
- English: Whisper base is fine; a small streaming English model (sherpa-onnx) may be faster.
- Not tested yet: Odia -> English translation (IndicTrans2), Hindi IndicConformer export.

Reproduce: `ort_test.cpp` is built with the NDK clang for arm64 and run as `LD_LIBRARY_PATH=. ./ort_test odia.onnx 4 10`.
