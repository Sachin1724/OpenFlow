import os
import re
import threading
from pathlib import Path
from typing import Callable, Optional

# plain HTTP download so partial files grow on disk and progress can be measured
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TQDM_DISABLE", "1")


class _Lazy:
    """Imports huggingface_hub on first use so it stays off the startup path."""

    def __getattr__(self, name):
        import huggingface_hub as hf
        return getattr(hf, name)


huggingface_hub = _Lazy()

# same table as faster_whisper.utils._MODELS, copied so importing faster_whisper (slow) is not needed
_MODELS = {
    f"{size}{suffix}": f"Systran/faster-whisper-{size}{suffix}"
    for size in ("tiny", "base", "small", "medium")
    for suffix in ("", ".en")
}
_MODELS.update({"large-v2": "Systran/faster-whisper-large-v2", "large-v3": "Systran/faster-whisper-large-v3"})

_PATTERNS = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]


def _repo(name: str) -> str:
    if re.match(r".*/.*", name):
        return name
    repo = _MODELS.get(name)
    if repo is None:
        raise ValueError(f"Unknown model '{name}'")
    return repo


def cached_path(name: str) -> Optional[str]:
    """Local model folder if already downloaded, else None."""
    try:
        path = huggingface_hub.snapshot_download(_repo(name), local_files_only=True, allow_patterns=_PATTERNS)
    except Exception:
        return None
    # an interrupted download leaves the folder without the weights
    return path if os.path.exists(os.path.join(path, "model.bin")) else None


def _total_bytes(repo: str) -> int:
    info = huggingface_hub.HfApi().model_info(repo, files_metadata=True)
    wanted = ("config.json", "preprocessor_config.json", "model.bin", "tokenizer.json")
    return sum(f.size or 0 for f in info.siblings
               if f.rfilename in wanted or f.rfilename.startswith("vocabulary."))


def _blob_bytes(repo: str) -> int:
    """Bytes on disk for this repo, including in-flight .incomplete files."""
    blobs = Path(huggingface_hub.constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--")) / "blobs"
    try:
        return sum(f.stat().st_size for f in blobs.iterdir() if f.is_file())
    except OSError:
        return 0


def download(name: str, on_progress: Optional[Callable[[int], None]] = None) -> str:
    """Downloads a model, reporting overall percent (0-100). Progress is measured from
    the cache folder because the hub client no longer exposes per-file byte bars."""
    repo = _repo(name)
    try:
        total = _total_bytes(repo)
    except Exception:
        total = 0
    base = _blob_bytes(repo)
    done_evt = threading.Event()

    def poll():
        last = -1
        while not done_evt.wait(0.25):
            if total:
                pct = max(0, min(99, int((_blob_bytes(repo) - base) * 100 / total)))
                if pct != last and on_progress:
                    last = pct
                    on_progress(pct)

    if on_progress:
        on_progress(0)
        threading.Thread(target=poll, daemon=True).start()
    try:
        path = huggingface_hub.snapshot_download(repo, allow_patterns=_PATTERNS)
    finally:
        done_evt.set()
    if on_progress:
        on_progress(100)
    return path
