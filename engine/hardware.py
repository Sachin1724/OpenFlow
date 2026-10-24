import os
import subprocess
from functools import lru_cache
from typing import Dict, Any

import psutil

CUDA_FIX = "pip install nvidia-cublas-cu12 nvidia-cudnn-cu12"


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
    cuda_ok = _cuda_usable()
    cores = os.cpu_count() or 4
    ram_gb = round(psutil.virtual_memory().total / 2**30, 1)

    if cuda_ok:
        vram = gpu.get("vram_gb", 4)
        model = "medium" if vram >= 10 else "small" if vram >= 6 else "base"
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


def resolve(cfg: dict) -> dict:
    """Turns 'auto' settings into concrete ones. Explicit user choices are left alone."""
    hw = detect()
    device = cfg.get("device", "auto")
    if device == "auto":
        device, compute = hw["device"], hw["compute_type"]
    else:
        compute = "float16" if device == "cuda" else "int8"
    size = cfg.get("model_size", "auto")
    if size == "auto":
        size = hw["model_size"]
    return {"device": device, "compute_type": compute, "model_size": size, "hw": hw}
