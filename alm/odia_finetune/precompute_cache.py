"""precompute_cache.py - runs SpeechFineTuningDataset's per-item work (speaker embedding +
speech tokenizing, both CPU-bound) once for the whole manifest and saves the results to disk.

train_odia.py was re-running this preprocessing every single training step (num_workers=0,
forced by Windows: the dataset holds a live, unpicklable chatterbox model reference), which
serialized CPU preprocessing in front of every GPU step. Doing it once here lets training read
plain tensors off disk instead -- GPU-bound from then on.
"""
import json
import logging
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chatterbox.tts import ChatterboxTTS
from chatterbox.models.t3.t3 import T3
from model_resize import resize_and_load_t3_weights
from finetune_t3_odia import DataArguments, SpeechFineTuningDataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("precompute_cache")

LOCAL_MODEL_DIR = "./model_odia_init"
NEW_VOCAB_SIZE = 781
MANIFEST_PATH = "./data/manifest.json"
CACHE_PATH = "./data/cache_t3.pt"


def main():
    with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
        items = [{"audio": it["audio"], "text": it["text"]} for it in json.load(f)]
    logger.info(f"{len(items)} utterances to cache")

    chatterbox_model = ChatterboxTTS.from_local(ckpt_dir=LOCAL_MODEL_DIR, device="cpu")
    t3_config = chatterbox_model.t3.hp
    if NEW_VOCAB_SIZE != t3_config.text_tokens_dict_size:
        old_state = chatterbox_model.t3.state_dict()
        t3_config.text_tokens_dict_size = NEW_VOCAB_SIZE
        chatterbox_model.t3 = resize_and_load_t3_weights(T3(hp=t3_config), old_state)

    data_args = DataArguments(max_text_len=256, max_speech_len=800)
    dataset = SpeechFineTuningDataset(data_args, chatterbox_model, t3_config, items, is_hf_format=False)

    cached = []
    for idx in range(len(dataset)):
        item = dataset[idx]
        if item is not None:
            cached.append(item)
        if (idx + 1) % 200 == 0:
            logger.info(f"{idx + 1}/{len(dataset)} processed, {len(cached)} kept")

    torch.save(cached, CACHE_PATH)
    logger.info(f"Saved {len(cached)} cached items to {CACHE_PATH}")


if __name__ == "__main__":
    main()
