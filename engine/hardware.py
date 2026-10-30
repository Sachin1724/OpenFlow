import os
import subprocess
from pathlib import Path
from functools import lru_cache
from typing import Dict, Any, Optional

import psutil

CUDA_FIX = "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12"
# written when CUDA froze mid-call; auto mode then uses the NPU/CPU. Delete it, or pick CUDA in Settings, to retry.
CUDA_HUNG_MARK = Path.home() / ".openflow" / "cuda_hung"


def _nvidia_smi() -> Dict[str, Any]:
    """GPU name and VRAM (GB) from the driver, or {} if there is no NVIDIA driver."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=0x08000000 if os.name == "nt" else 0,  # no console flash
        )
        if out.returncode != 0 or not out.stdout.strip():
            return {}
        name, mem = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
        return {"name": name, "vram_gb": round(float(mem) / 1024, 1)}
    except Exception:
        return {}


def _cuda_usable() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def detect() -> Dict[str, Any]:
    """Inspects this PC and recommends device, compute type and model size."""
    gpu = _nvidia_smi()
    # An NVIDIA driver is enough for the startup choice: importing ctranslate2 to probe CUDA costs
    # several seconds. If CUDA is not actually usable, the model load falls back to the CPU itself.
    cuda_ok = bool(gpu) and not CUDA_HUNG_MARK.exists()  # a CUDA call froze here before: stay off it
    cores = os.cpu_count() or 4
    ram_gb = round(psutil.virtual_memory().total / 2**30, 1)

    if cuda_ok:
        vram = gpu.get("vram_gb", 4)
        model = "distil-large-v3" if vram >= 10 else "small" if vram >= 6 else "base"
        device, compute = "cuda", "float16"
        note = f"{gpu.get('name', 'NVIDIA GPU')} ({vram:g} GB) detected. Using the GPU."
    else:
        device, compute = "cpu", "int8"
        model = "base" if cores >= 8 and ram_gb >= 8 else "tiny"
        if gpu:
            note = (f"{gpu['name']} found, but CUDA is not usable. Using the CPU. "
                    f"To use the GPU run: {CUDA_FIX}")
        else:
            note = "No NVIDIA GPU found. Using the CPU with a lighter model."

    return {
        "gpu_name": gpu.get("name", ""), "vram_gb": gpu.get("vram_gb", 0), "cuda_ok": cuda_ok,
        "cpu_cores": cores, "ram_gb": ram_gb,
        "device": device, "compute_type": compute, "model_size": model, "note": note,
    }


def gpu_changed() -> bool:
    """Re-probes the NVIDIA driver (GPU switched off/on, eGPU, hybrid-graphics mode change).
    Returns True and refreshes detect() when GPU availability differs from the cached result."""
    now = bool(_nvidia_smi())
    if now == bool(detect()["gpu_name"]):  # not cuda_ok: the hang marker can turn that off while the driver stays
        return False
    detect.cache_clear()
    return True


@lru_cache(maxsize=1)
def npu_name() -> str:
    """Intel NPU (Core Ultra "AI Boost") usable through OpenVINO, else ''.
    AMD Ryzen AI and Qualcomm Hexagon need runtimes this x64 build doesn't ship, so they read as ''."""
    try:
        import openvino as ov
        core = ov.Core()
        if "NPU" in core.available_devices:
            return str(core.get_property("NPU", "FULL_DEVICE_NAME"))
        print(f"[OpenFlow] No Intel NPU visible to OpenVINO (devices: {core.available_devices}). "
              "On a Core Ultra PC, update the Intel NPU driver.")
    except Exception as e:
        print(f"[OpenFlow] NPU probe failed: {e}")
    return ""


def _npu_has_build(size: str) -> bool:
    from . import model_manager
    return size.replace(".en", "") + "-ov" in model_manager._MODELS


def _npu_model_cached(size: str) -> bool:
    from . import model_manager
    return model_manager.cached_path(size.replace(".en", "") + "-ov") is not None


def resolve(cfg: dict) -> dict:
    """Turns 'auto' settings into concrete ones. Explicit user choices are left alone."""
    hw = detect()
    device = cfg.get("device", "auto")
    if device == "npu" and not npu_name():
        print("[OpenFlow] NPU selected but no usable Intel NPU found; using automatic device.")
        device = "auto"
    if device == "auto":
        device, compute = hw["device"], hw["compute_type"]
    else:
        compute = "float16" if device == "cuda" else "int8"
    size = cfg.get("model_size", "auto")
    if size == "auto":
        try:
            from . import model_manager
            downloaded = model_manager.list_downloaded_models()
        except Exception:
            downloaded = []

        if downloaded:
            # If the recommended hardware model is already cached, use it!
            if hw["model_size"] in downloaded:
                size = hw["model_size"]
            elif "base" in downloaded:
                size = "base"
            elif "tiny" in downloaded:
                size = "tiny"
            else:
                size = downloaded[0]
        else:
            size = hw["model_size"]
    # Odia speech goes to the Odia model whenever it is downloaded, whatever model is picked for other languages
    from .transcriber import ODIA_LANGS
    if cfg.get("language") in ODIA_LANGS and size != "odia":
        from . import model_manager
        if model_manager.cached_path("odia"):
            size = "odia"
    # auto on a PC without NVIDIA: use the NPU. Its OpenVINO build is what gets downloaded on a first run;
    # once a regular model is on disk, switching needs the user to pick the NPU (no surprise downloads).
    if (cfg.get("device", "auto") == "auto" and device == "cpu" and size not in ("parakeet", "odia")
            and _npu_has_build(size) and npu_name()):
        from . import model_manager
        if _npu_model_cached(size) or not model_manager.list_downloaded_models():
            device = "npu"
        elif not getattr(resolve, "_hinted", False):
            resolve._hinted = True
            print("[OpenFlow] Intel NPU available: choose Device > NPU in Settings to use it (downloads its model build).")
    return {"device": device, "compute_type": compute, "model_size": size, "hw": hw}


def get_system_stack(cfg: Optional[dict] = None, transcriber=None) -> Dict[str, Any]:
    """
    Returns full hardware stack diagnostics detailing GPU, NPU, CPU utilization,
    and active inference backend.
    """
    hw = detect()
    npu = npu_name()
    resolved = resolve(cfg or {})

    # Active runtime device and model
    active_device = (getattr(transcriber, "_loaded_device", None) or resolved.get("device") or "cpu").upper()
    active_model = getattr(transcriber, "_current_loaded_name", None) or resolved.get("model_size") or "base.en"
    compute = resolved.get("compute_type", "float16" if active_device == "CUDA" else "int8")

    # GPU
    gpu_active = active_device == "CUDA"
    gpu_info = {
        "name": hw.get("gpu_name") or "None detected",
        "vram_gb": hw.get("vram_gb", 0),
        "cuda_available": hw.get("cuda_ok", False),
        "status": "Active Engine (Accelerated)" if gpu_active else ("Standby (Available)" if hw.get("cuda_ok") else "Unavailable"),
        "backend": "CTranslate2 (cuBLAS / cuDNN)" if hw.get("cuda_ok") else "None",
        "is_active": gpu_active
    }

    # NPU
    npu_active = active_device == "NPU"
    npu_info = {
        "name": npu or "Intel AI Boost / DirectML NPU",
        "detected": bool(npu),
        "status": "Active Engine (Direct NPU IR)" if npu_active else ("Standby (OpenVINO IR Ready)" if npu else "Not Detected / Standby"),
        "acceleration": "OpenVINO GenAI INT8" if npu else "DirectML NPU Driver",
        "power_profile": "Ultra Low Power (1.5W-4.5W TDP)" if npu else "Standard",
        "is_active": npu_active
    }

    # CPU
    cpu_active = active_device == "CPU"
    import platform
    cpu_info = {
        "processor": platform.processor() or "x86_64 Compatible",
        "cores": hw.get("cpu_cores", os.cpu_count() or 4),
        "ram_gb": hw.get("ram_gb", 0),
        "status": "Active Engine (SIMD Int8)" if cpu_active else "Host & Audio DSP",
        "is_active": cpu_active
    }

    # Pipeline summary description
    if active_model == "parakeet":
        pipeline_desc = "Sherpa-ONNX (Parakeet TDT) on CPU [INT8]"
    elif active_model == "odia":
        pipeline_desc = "ONNX Runtime (AI4Bharat IndicConformer, Odia) on CPU"
    elif active_device == "NPU":
        pipeline_desc = f"OpenVINO IR ({active_model}) on NPU [INT8]"
    elif active_device == "CUDA":
        pipeline_desc = f"faster-whisper ({active_model}) on NVIDIA CUDA [{compute}]"
    else:
        pipeline_desc = f"faster-whisper ({active_model}) on CPU [{compute}]"

    return {
        "gpu": gpu_info,
        "npu": npu_info,
        "cpu": cpu_info,
        "active_device": active_device,
        "active_model": active_model,
        "compute_precision": compute,
        "pipeline": pipeline_desc,
        "recommendation": hw.get("note", "")
    }
