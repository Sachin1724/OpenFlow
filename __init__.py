"""
OpenFlow — Unlimited Local AI Voice Dictation for Windows
"""
import os as _os

# The installed exe has no console (sys.stderr is None), which makes tqdm progress bars crash
# model downloads. OpenFlow reports download progress itself, so switch the bars off up front,
# before huggingface_hub is imported anywhere.
_os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
_os.environ.setdefault("TQDM_DISABLE", "1")
_os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

__version__ = "1.1.5"
