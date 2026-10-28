import fnmatch
import os
import re
import shutil
import stat
import threading
from pathlib import Path
from typing import Callable, Optional, List, Dict, Any

# plain HTTP download so partial files grow on disk and progress can be measured
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")


class _Lazy:
    """Imports huggingface_hub on first use so it stays off the startup path."""

    def __getattr__(self, name):
        if name == "constants":
            import huggingface_hub.constants as hfc
            return hfc
        import huggingface_hub as hf
        return getattr(hf, name)


huggingface_hub = _Lazy()


# Standard faster-whisper models table
_MODELS = {
    f"{size}{suffix}": f"Systran/faster-whisper-{size}{suffix}"
    for size in ("tiny", "base", "small", "medium")
    for suffix in ("", ".en")
}
_MODELS.update({
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
    "parakeet": "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
    # AI4Bharat IndicConformer (CC-BY-4.0), sulabhkatiyar's ONNX export with MatMuls quantized to int8
    "odia": "sachinmallick/openflow-odia-asr-int8",
    # AI4Bharat IndicTrans2 Indic->En distilled 200M, CTranslate2 build (MIT); not a speech model
    "odia-en": "adalat-ai/ct2-rotary-indictrans2-indic-en-dist-200M",
    # Qwen2.5-1.5B-Instruct (Apache-2.0), int8 CTranslate2 build: voice edits and meeting notes
    "writer": "jncraton/Qwen2.5-1.5B-Instruct-ct2-int8",
})

# OpenVINO IR builds for the Intel NPU engine ("base-ov" -> OpenVINO/whisper-base-int8-ov)
_MODELS.update({f"{size}-ov": f"OpenVINO/whisper-{size}-int8-ov" for size in ("tiny", "base", "small", "medium")})
_MODELS["distil-large-v3-ov"] = "OpenVINO/distil-whisper-large-v3-int8-ov"

_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
_OV_PATTERNS = ["*.xml", "*.bin", "*.json"]
_PARAKEET_PATTERNS = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt"]
_ODIA_PATTERNS = ["or/model.onnx", "or/vocab.json"]
TRANSLATOR_DIR = "indic-en-200m-ct2/ctranslate2_model"
_TRANSLATOR_PATTERNS = [TRANSLATOR_DIR + "/*", TRANSLATOR_DIR + "/vocab/*"]


def _patterns(name: str) -> List[str]:
    if name.endswith("-ov"):
        return _OV_PATTERNS
    if name == "odia":
        return _ODIA_PATTERNS
    if name == "odia-en":
        return _TRANSLATOR_PATTERNS
    if name == "writer":
        return ["config.json", "generation_config.json", "model.bin", "tokenizer.json", "tokenizer_config.json", "vocabulary.json"]
    return _PARAKEET_PATTERNS if name == "parakeet" else _PATTERNS


def _weights_file(name: str) -> str:
    """The big file whose presence and size proves a download finished."""
    if name.endswith("-ov"):
        return "openvino_encoder_model.bin"
    if name == "odia":
        return "or/model.onnx"
    if name == "odia-en":
        return TRANSLATOR_DIR + "/model.bin"
    return "encoder.int8.onnx" if name == "parakeet" else "model.bin"

# Accurate offline known sizes for fallback progress calculation (in bytes)
_KNOWN_SIZES: Dict[str, int] = {
    "tiny": 78_203_619,
    "tiny.en": 78_090_594,
    "base": 147_882_941,
    "base.en": 147_769_510,
    "small": 486_212_372,
    "small.en": 486_098_798,
    "medium": 1_530_571_735,
    "medium.en": 1_530_457_748,
    "distil-large-v3": 1_510_000_000,
    "large-v2": 3_090_000_000,
    "large-v3": 3_090_000_000,
    "parakeet": 670_478_772,
    "odia": 197_090_303,
    "odia-en": 856_259_538,
    "writer": 1_558_000_000,
}

MODEL_METADATA = [
    {
        "id": "base",
        "name": "Base (Multilingual)",
        "description": "Recommended: fast & accurate for English, Hinglish & Indian English (~141 MB)",
        "speed": "Fast (1.2x)",
        "accuracy": "High",
        "recommended": True,
    },
    {
        "id": "tiny",
        "name": "Tiny (Multilingual)",
        "description": "Ultra-lightweight, minimal memory footprint (~75 MB)",
        "speed": "Ultra-Fast (3.5x)",
        "accuracy": "Good",
        "recommended": False,
    },
    {
        "id": "small",
        "name": "Small (Multilingual)",
        "description": "Enhanced vocabulary recognition for heavy accents & mixed code (~464 MB)",
        "speed": "Moderate (0.8x)",
        "accuracy": "Very High",
        "recommended": False,
    },
    {
        "id": "medium",
        "name": "Medium (Multilingual)",
        "description": "Maximum transcription fidelity across technical & medical jargon (~1.46 GB)",
        "speed": "Heavy (0.4x)",
        "accuracy": "State-of-the-art",
        "recommended": False,
    },
    {
        "id": "parakeet",
        "name": "Parakeet V3 (CPU)",
        "description": "Fast on computers without a GPU. English + 24 European languages; others use Whisper (~640 MB)",
        "speed": "Fast on CPU",
        "accuracy": "Very High",
        "recommended": False,
    },
    {
        "id": "odia",
        "name": "Odia (AI4Bharat IndicConformer)",
        "description": "Native Odia speech-to-text in Odia script. Used when the language is Odia; others use Whisper (~190 MB)",
        "speed": "Fast",
        "accuracy": "High (Odia)",
        "recommended": False,
    },
]


def _repo(name: str) -> str:
    if re.match(r".*/.*", name):
        return name
    repo = _MODELS.get(name)
    if repo is None:
        raise ValueError(f"Unknown model '{name}'")
    return repo


def sanitize_cache_symlinks(model_dir: Path):
    """
    On Windows, symlinks in HF cache can trigger:
    [WinError 448] The path cannot be traversed because it contains an untrusted mount point.
    Replacing symlinks with standard files prevents Windows NTFS untrusted mount point traversal blocks.
    """
    if os.name != "nt":
        return
    try:
        snapshots = model_dir / "snapshots"
        if not snapshots.is_dir():
            return
        for snap in snapshots.iterdir():
            if snap.is_dir():
                for item in snap.iterdir():
                    try:
                        if item.is_symlink():
                            target = os.readlink(str(item))
                            abs_target = os.path.normpath(os.path.join(str(snap), target))
                            if os.path.isfile(abs_target):
                                os.remove(str(item))
                                shutil.copyfile(abs_target, str(item))
                    except OSError:
                        pass
    except Exception:
        pass


def sanitize_all_cached_models():
    """Sanitizes all cached model snapshots on Windows to eliminate untrusted mount points."""
    if os.name != "nt":
        return
    try:
        hub_cache = Path(huggingface_hub.constants.HF_HUB_CACHE)
        if not hub_cache.is_dir():
            return
        for folder in hub_cache.iterdir():
            if folder.is_dir() and folder.name.startswith("models--"):
                sanitize_cache_symlinks(folder)
    except Exception:
        pass


def get_model_cache_dir(name: str) -> Path:
    """Return the Path to the Hugging Face hub model cache folder."""
    repo = _repo(name)
    hub_cache = Path(huggingface_hub.constants.HF_HUB_CACHE)
    return hub_cache / ("models--" + repo.replace("/", "--"))


def cached_path(name: str) -> Optional[str]:
    """Local model folder if already completely downloaded, else None."""
    model_dir = get_model_cache_dir(name)
    sanitize_cache_symlinks(model_dir)

    try:
        # First check fast snapshot_download in local-only mode
        path = huggingface_hub.snapshot_download(_repo(name), local_files_only=True, allow_patterns=_patterns(name))
        model_bin = os.path.join(path, _weights_file(name))
        try:
            if os.path.isfile(model_bin) and os.path.getsize(model_bin) > 5_000_000:
                return path
        except OSError:
            pass
    except Exception:
        pass

    # Direct filesystem fallback: inspect snapshots folder
    try:
        snapshots_dir = model_dir / "snapshots"
        if snapshots_dir.is_dir():
            for snap in snapshots_dir.iterdir():
                try:
                    if snap.is_dir():
                        model_bin = snap / _weights_file(name)
                        try:
                            if os.path.isfile(str(model_bin)) and os.path.getsize(str(model_bin)) > 5_000_000:
                                return str(snap)
                        except OSError:
                            pass
                except OSError:
                    pass
    except Exception:
        pass
    return None


def variants(name: str) -> List[str]:
    """A library id and its English-only twin ('base' -> ['base', 'base.en']); both count as that model."""
    clean = name.replace(".en", "")
    twin = f"{clean}.en"
    return [clean, twin] if twin in _MODELS else [clean]


def any_cached_path(name: str) -> Optional[str]:
    """Like cached_path, but accepts the other variant of the same size (base <-> base.en)."""
    for v in sorted(variants(name), key=lambda v: v != name):
        p = cached_path(v)
        if p:
            return p
    return None


def is_model_downloaded(name: str) -> bool:
    """True if model weights (either variant) exist on disk and are non-empty."""
    try:
        return any_cached_path(name) is not None
    except Exception:
        return False


active_device = "cpu"  # set by Transcriber on load; the NPU engine uses its own "-ov" model builds


def is_ready(name: str) -> bool:
    """Downloaded for the engine that is running now (Model Library and capsule badges)."""
    if active_device == "npu" and name not in ("parakeet", "odia"):
        return cached_path(name.replace(".en", "") + "-ov") is not None
    return is_model_downloaded(name)


def list_downloaded_models() -> List[str]:
    """Returns list of model IDs currently ready in local disk cache."""
    downloaded: List[str] = []
    for m in MODEL_METADATA:
        mid = str(m["id"])
        if is_model_downloaded(mid):
            downloaded.append(mid)
    return downloaded



def get_model_disk_size(name: str) -> int:
    """Calculate total bytes occupied on disk by this model (both variants)."""
    return sum(_dir_size(get_model_cache_dir(v)) for v in variants(name))


def _dir_size(model_dir: Path) -> int:
    if not model_dir.exists():
        return 0
    total = 0
    try:
        for root, _, files in os.walk(model_dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    except Exception:
        pass
    return total


def format_size_mb(size_bytes: int) -> str:
    """Format bytes into friendly MB string."""
    if size_bytes <= 0:
        return "0 MB"
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def clean_incomplete_downloads(name: Optional[str] = None):
    """Clean up stale .incomplete or lock files to prevent stuck download loops."""
    targets = [name] if name else list(_MODELS.keys())
    for target in targets:
        try:
            model_dir = get_model_cache_dir(target)
            if not model_dir.exists():
                continue
            blobs_dir = model_dir / "blobs"
            if blobs_dir.exists():
                for f in blobs_dir.iterdir():
                    if f.name.endswith(".incomplete") or f.name.endswith(".lock"):
                        try:
                            f.unlink(missing_ok=True)
                        except OSError:
                            pass
        except Exception:
            pass


def _remove_readonly(func, path, excinfo):
    """Windows error handler for shutil.rmtree on read-only files."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def delete_model(name: str) -> bool:
    """Safely delete model cache (both variants) from disk. Returns True if deleted or did not exist."""
    ok = True
    ov = f"{name.replace('.en', '')}-ov"
    for v in variants(name) + ([ov] if ov in _MODELS else []):  # the NPU build goes with it
        try:
            model_dir = get_model_cache_dir(v)
            if model_dir.exists():
                shutil.rmtree(str(model_dir), onerror=_remove_readonly)
                ok = ok and not model_dir.exists()
        except Exception as e:
            print(f"[OpenFlow] Failed to delete model {v}: {e}")
            ok = False
    return ok


def list_available_models(active_model: str = "base") -> List[Dict[str, Any]]:
    """Return model library listing with status, size on disk, and active state."""
    active_clean = active_model.replace(".en", "").lower()
    res = []
    for meta in MODEL_METADATA:
        m_id = str(meta["id"])
        is_dl = is_ready(m_id)
        disk_bytes = get_model_disk_size(m_id) if is_dl else 0
        expected_bytes = _KNOWN_SIZES.get(m_id, 0)

        is_active = (active_clean == m_id or active_clean.startswith(m_id))

        res.append({
            "id": m_id,
            "name": meta["name"],
            "description": meta["description"],
            "speed": meta["speed"],
            "accuracy": meta["accuracy"],
            "recommended": meta["recommended"],
            "is_downloaded": is_dl,
            "is_active": is_active,
            "disk_bytes": disk_bytes,
            "disk_size_str": format_size_mb(disk_bytes if is_dl else expected_bytes),
            "expected_size_str": format_size_mb(expected_bytes),
        })
    return res


def _total_bytes(repo: str, model_name: str = "") -> int:
    """Determine expected total bytes, with reliable offline fallback."""
    clean_name = model_name.replace(".en", "")
    known = _KNOWN_SIZES.get(model_name) or _KNOWN_SIZES.get(clean_name)
    try:
        info = huggingface_hub.HfApi().model_info(repo, files_metadata=True)
        api_total = sum(
            f.size or 0 for f in info.siblings
            if any(fnmatch.fnmatch(f.rfilename, p) for p in _patterns(model_name))
        )
        if api_total > 5_000_000:
            return api_total
    except Exception:
        pass
    return known or 147_882_941


def _blob_bytes(repo: str) -> int:
    """Bytes on disk for this repo, including in-flight .incomplete files."""
    blobs = Path(huggingface_hub.constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--")) / "blobs"
    try:
        return sum(f.stat().st_size for f in blobs.iterdir() if f.is_file())
    except OSError:
        return 0


def download(name: str, on_progress: Optional[Callable[[int], None]] = None, force: bool = False) -> str:
    """
    Downloads a model, reporting overall percent (0-100).
    Automatically cleans corrupted partial files if forced or interrupted.
    """
    repo = _repo(name)
    total = _total_bytes(repo, model_name=name)

    if force:
        clean_incomplete_downloads(name)
        delete_model(name)

    base = 0 if force else _blob_bytes(repo)
    done_evt = threading.Event()

    def poll():
        last = -1
        while not done_evt.wait(0.20):
            if total > 0:
                current = _blob_bytes(repo)
                # Ensure monotonic progress
                pct = max(0, min(99, int((current - base) * 100 / total)))
                if pct != last and on_progress:
                    last = pct
                    try:
                        on_progress(pct)
                    except Exception:
                        pass

    if on_progress:
        try:
            on_progress(0)
        except Exception:
            pass
        threading.Thread(target=poll, daemon=True).start()

    try:
        path = huggingface_hub.snapshot_download(
            repo,
            allow_patterns=_patterns(name),
            force_download=force,
            resume_download=True,
        )
    finally:
        done_evt.set()

    # Validate that model.bin exists and has valid size
    verified_path = cached_path(name)
    if not verified_path:
        clean_incomplete_downloads(name)
        raise RuntimeError(f"Model download for {name} finished but weights were not verified.")

    if on_progress:
        try:
            on_progress(100)
        except Exception:
            pass

    return verified_path
