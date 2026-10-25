"""
refiner.py — Local Speech-to-Writing Refiner
=============================================
Uses a small quantized GGUF model (via llama-cpp-python) to:
  - Remove filler words intelligently (um, uh, you know, sort of)
  - Resolve self-corrections  ("Monday, wait no, Tuesday" → "Tuesday")
  - Fix punctuation and capitalization
  - Preserve meaning, names, numbers exactly

Hardware-aware model selection (fully automatic):
  ┌─────────────────┬───────────────────┬──────────┬─────────┐
  │ Tier            │ Model             │ Size     │ Latency │
  ├─────────────────┼───────────────────┼──────────┼─────────┤
  │ CUDA GPU        │ Qwen2.5-0.5B      │ 380 MB   │ ~30 ms  │
  │ CPU ≥8c/≥8GB   │ SmolLM2-360M      │ 220 MB   │ ~140 ms │
  │ CPU low-end     │ SmolLM2-135M      │  90 MB   │ ~55 ms  │
  │ Very low-end    │ None (regex only) │   0 MB   │   0 ms  │
  └─────────────────┴───────────────────┴──────────┴─────────┘

Graceful degradation:
  - llama-cpp-python not installed → skip silently
  - Model download fails          → skip silently
  - Inference > 500 ms            → fall back to raw text
  - Any exception                 → fall back to raw text

The refiner is OPTIONAL. OpenFlow works fine without it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

# ─── Model catalogue ─────────────────────────────────────────────────────────
# Each entry: (hf_repo, filename, min_ram_gb, prefers_cuda)
_MODELS: dict[str, tuple[str, str, float, bool]] = {
    "qwen0.5b-q4":   (
        "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "qwen2.5-0.5b-instruct-q4_k_m.gguf",
        0.6,   # VRAM / RAM needed
        True,  # prefers GPU
    ),
    "smollm360-q4": (
        "HuggingFaceTB/smollm2-360M-instruct-GGUF",
        "smollm2-360m-instruct-q4_k_m.gguf",
        0.35,
        False,
    ),
    "smollm135-q4": (
        "HuggingFaceTB/smollm2-135M-instruct-GGUF",
        "smollm2-135m-instruct-q4_k_m.gguf",
        0.15,
        False,
    ),
}

REFINER_CACHE = Path.home() / ".openflow" / "refiner_models"
TIMEOUT_MS    = 500   # fall back to regex if LLM takes longer than this

# System prompt — tight and task-specific.  temperature=0 (greedy).
_SYSTEM = (
    "You are a speech-to-writing refiner. Your ONLY job is to clean spoken text into natural written text.\n"
    "Rules:\n"
    "1. Remove filler words: um, uh, like, you know, sort of, I mean, basically.\n"
    "2. Resolve self-corrections: keep ONLY the final intent. "
    "   Example: 'Send to Bob — wait no — Alice' → 'Send to Alice'\n"
    "3. Fix capitalisation and add minimal punctuation.\n"
    "4. NEVER change names, numbers, technical terms, or meaning.\n"
    "5. If input is clean already, return it unchanged.\n"
    "Output ONLY the cleaned sentence — no explanation, no prefix."
)


def _pick_tier(cuda_ok: bool, cpu_cores: int, ram_gb: float, vram_gb: float) -> str | None:
    """Return model key for this hardware, or None if system is too limited."""
    if cuda_ok and vram_gb >= 0.6:
        return "qwen0.5b-q4"
    if cpu_cores >= 8 and ram_gb >= 6.0:
        return "smollm360-q4"
    if cpu_cores >= 4 and ram_gb >= 3.0:
        return "smollm135-q4"
    return None   # very low-end: regex only


def _llama_available() -> bool:
    """Check llama-cpp-python is importable (wheel may not be installed)."""
    try:
        import importlib
        importlib.import_module("llama_cpp")
        return True
    except ImportError:
        return False


class LocalRefiner:
    """
    Singleton-friendly refiner.  Instantiate once in main.py, keep alive.
    All heavy work (download + load) happens in a background thread.
    """

    def __init__(
        self,
        cuda_ok: bool = False,
        cpu_cores: int = 4,
        ram_gb: float = 8.0,
        vram_gb: float = 0.0,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ):
        self._llm = None          # llama_cpp.Llama instance
        self._ready = False
        self._enabled = False     # True only when model loaded successfully
        self._lock = threading.Lock()

        self.on_status   = on_status    # callback(str) → shown in HUD status bar
        self.on_progress = on_progress  # callback(percent:int, label:str) → HUD fill

        self._tier = _pick_tier(cuda_ok, cpu_cores, ram_gb, vram_gb)
        self._cuda = cuda_ok

        if self._tier is None:
            self._log("Refiner: system below minimum — regex formatter only")
            return

        if not _llama_available():
            self._log("Refiner: llama-cpp-python not installed — regex formatter only")
            self._log("         Install with:  pip install llama-cpp-python")
            return

        # Start background download + load immediately
        threading.Thread(target=self._bootstrap, daemon=True).start()

    # ─── Internal ────────────────────────────────────────────────────────────

    def _log(self, msg: str):
        print(f"[OpenFlow] {msg}")
        if self.on_status:
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _report_progress(self, pct: int, label: str):
        if self.on_progress:
            try:
                self.on_progress(pct, label)
            except Exception:
                pass

    def _bootstrap(self):
        """Download model if needed, then load it — runs in a daemon thread."""
        try:
            model_path = self._ensure_downloaded()
            if model_path is None:
                return
            self._load(model_path)
        except Exception as e:
            self._log(f"Refiner bootstrap failed: {e}")

    def _ensure_downloaded(self) -> str | None:
        repo, filename, _, _ = _MODELS[self._tier]
        dest = REFINER_CACHE / filename

        if dest.exists():
            self._log(f"Refiner model ready: {filename}")
            return str(dest)

        # Download from HuggingFace Hub (single-file GGUF)
        try:
            import huggingface_hub
        except ImportError:
            self._log("Refiner: huggingface_hub not found — cannot download model")
            return None

        REFINER_CACHE.mkdir(parents=True, exist_ok=True)
        label = self._tier

        self._log(f"Refiner: downloading {filename} ({repo}) …")
        self._report_progress(0, label)

        done_evt  = threading.Event()
        tmp_path  = REFINER_CACHE / (filename + ".part")

        def poll_progress():
            last = -1
            while not done_evt.wait(0.5):
                if tmp_path.exists():
                    written = tmp_path.stat().st_size
                    # Estimate total from known sizes
                    _sizes = {"qwen0.5b-q4": 398_000_000, "smollm360-q4": 230_000_000, "smollm135-q4": 90_000_000}
                    total = _sizes.get(self._tier, 0)
                    if total:
                        pct = min(99, int(written * 100 / total))
                        if pct != last:
                            last = pct
                            self._report_progress(pct, label)

        threading.Thread(target=poll_progress, daemon=True).start()
        try:
            local_path = huggingface_hub.hf_hub_download(
                repo_id=repo,
                filename=filename,
                local_dir=str(REFINER_CACHE),
                local_dir_use_symlinks=False,
            )
        except Exception as e:
            done_evt.set()
            self._log(f"Refiner: download failed — {e}")
            return None
        finally:
            done_evt.set()

        self._report_progress(100, label)
        self._log(f"Refiner: {filename} downloaded ({Path(local_path).stat().st_size // 1_000_000} MB)")
        return local_path

    def _load(self, model_path: str):
        """Load GGUF into llama_cpp — takes 1-3 s on first call."""
        from llama_cpp import Llama

        n_gpu = -1 if self._cuda else 0   # -1 = all layers on GPU
        self._log(f"Refiner: loading {Path(model_path).name}  (gpu_layers={n_gpu}) …")

        t0 = time.perf_counter()
        with self._lock:
            self._llm = Llama(
                model_path=model_path,
                n_gpu_layers=n_gpu,
                n_ctx=512,          # our inputs are tiny; no need for 4K ctx
                n_threads=min(4, os.cpu_count() or 4),
                verbose=False,
            )
        elapsed = time.perf_counter() - t0
        self._enabled = True
        self._log(f"Refiner: ready in {elapsed:.1f}s on {'GPU' if self._cuda else 'CPU'}")

    # ─── Public API ───────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._enabled

    def refine(self, raw_text: str) -> str:
        """
        Refine raw_text.  Returns cleaned text, or raw_text on any failure.
        Enforces TIMEOUT_MS hard deadline — never blocks the paste pipeline.
        """
        if not self._enabled or not raw_text.strip():
            return raw_text

        # Skip very short utterances — nothing to clean
        if len(raw_text.split()) < 4:
            return raw_text

        result_box: list[str] = []
        exc_box:    list[Exception] = []

        def _call():
            try:
                from llama_cpp import Llama
                with self._lock:
                    llm: Llama = self._llm  # type: ignore[assignment]
                out = llm.create_chat_completion(
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user",   "content": raw_text},
                    ],
                    temperature=0.0,   # greedy — deterministic, fastest
                    max_tokens=len(raw_text.split()) + 30,  # never inflate output
                    stream=False,
                )
                refined = out["choices"][0]["message"]["content"].strip()
                result_box.append(refined)
            except Exception as e:
                exc_box.append(e)

        t = threading.Thread(target=_call, daemon=True)
        t.start()
        t.join(timeout=TIMEOUT_MS / 1000.0)

        if exc_box:
            print(f"[OpenFlow] Refiner error: {exc_box[0]}")
            return raw_text

        if not result_box:
            # Timed out
            print(f"[OpenFlow] Refiner timeout (>{TIMEOUT_MS}ms) — using raw transcript")
            return raw_text

        refined = result_box[0]

        # Safety check: if model returns empty or wildly different length, use raw
        if not refined or len(refined) < len(raw_text) * 0.3:
            return raw_text

        return refined
