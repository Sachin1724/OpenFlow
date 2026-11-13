"""train_odia.py - fine-tunes Chatterbox's T3 on real Odia graphemes (AI4Bharat Rasa or_F/or_M,
via sulabhkatiyar/indic-tts-mini-24k), teaching it the extended tokenizer's 77 new Odia tokens.

Plain PyTorch loop, no transformers.Trainer: Trainer's import triggers torch._dynamo's
trace_rules module-scan, which segfaults once ChatterboxTTS's native stack (onnxruntime +
diffusers + torchaudio) is already loaded in-process on this Windows/Python 3.10 setup --
confirmed by bisection (chatterbox load + Trainer import crashes; either alone does not;
TF/datasets, KMP_DUPLICATE_LIB_OK, CUDA_VISIBLE_DEVICES, TORCHDYNAMO_DISABLE made no difference).
This loop needs none of Trainer's machinery for a single-process single-GPU fine-tune.

Dataset/collator/model-wrapper classes reused as-is from stlohrey/chatterbox-finetuning's
finetune_t3_odia.py (our vocab-resized fork of their finetune_t3.py).
"""
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset

sys.path.insert(0, str(Path(__file__).resolve().parent))

from chatterbox.tts import ChatterboxTTS
from chatterbox.models.t3.t3 import T3

from model_resize import resize_and_load_t3_weights
from finetune_t3_odia import DataArguments, SpeechFineTuningDataset, SpeechDataCollator, T3ForFineTuning

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("train_odia")


class CachedDataset(Dataset):
    """Wraps the list precompute_cache.py saved -- per-item work already done."""
    def __init__(self, items):
        self.items = items

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        return self.items[idx]


@dataclass
class Config:
    local_model_dir: str = "./model_odia_init"
    new_vocab_size: int = 781
    manifest_path: str = "./data/manifest.json"
    cache_path: str = "./data/cache_t3.pt"
    output_dir: str = "./checkpoints"
    batch_size: int = 1
    grad_accum: int = 16
    lr: float = 1e-5
    num_epochs: int = 1
    max_text_len: int = 256
    max_speech_len: int = 800
    log_every: int = 1
    save_every_steps: int = 500


def load_manifest(path: str):
    with open(path, "r", encoding="utf-8") as f:
        items = json.load(f)
    return [{"audio": it["audio"], "text": it["text"]} for it in items]


def main():
    cfg = Config()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Device: {device}")

    logger.info("Loading ChatterboxTTS (base weights) on CPU...")
    chatterbox_model = ChatterboxTTS.from_local(ckpt_dir=cfg.local_model_dir, device="cpu")
    t3_model = chatterbox_model.t3
    t3_config = t3_model.hp

    if cfg.new_vocab_size != t3_config.text_tokens_dict_size:
        logger.info(f"Resizing T3 text vocab: {t3_config.text_tokens_dict_size} -> {cfg.new_vocab_size}")
        old_state = t3_model.state_dict()
        t3_config.text_tokens_dict_size = cfg.new_vocab_size
        t3_model = T3(hp=t3_config)
        t3_model = resize_and_load_t3_weights(t3_model, old_state)
        chatterbox_model.t3 = t3_model

    for p in chatterbox_model.ve.parameters():
        p.requires_grad = False
    for p in chatterbox_model.s3gen.parameters():
        p.requires_grad = False
    for p in t3_model.parameters():
        p.requires_grad = True

    t3_model = t3_model.to(device)
    t3_model.train()
    # ve/s3gen stay on CPU: frozen, used only for per-utterance dataset preprocessing
    # (speaker embedding + speech tokenization), not for the training forward/backward pass.

    if Path(cfg.cache_path).exists():
        logger.info(f"Loading precomputed dataset cache: {cfg.cache_path}")
        dataset = CachedDataset(torch.load(cfg.cache_path, weights_only=False))
        logger.info(f"{len(dataset)} cached training utterances")
    else:
        logger.warning(
            f"No cache at {cfg.cache_path} -- preprocessing every item live (slow, CPU-bound "
            f"per step). Run precompute_cache.py once to remove this bottleneck."
        )
        logger.info(f"Loading manifest: {cfg.manifest_path}")
        items = load_manifest(cfg.manifest_path)
        logger.info(f"{len(items)} training utterances")
        data_args = DataArguments(max_text_len=cfg.max_text_len, max_speech_len=cfg.max_speech_len)
        dataset = SpeechFineTuningDataset(data_args, chatterbox_model, t3_config, items, is_hf_format=False)
    collator = SpeechDataCollator(t3_config, t3_config.stop_text_token, t3_config.stop_speech_token)
    # ponytail: num_workers>0 breaks here -- Windows' spawn-based multiprocessing can't pickle
    # the dataset's live chatterbox_model reference (torch.nn.utils.parametrize refuses to
    # serialize). Would need decoupling audio preprocessing from the model to fix; not worth it
    # for one run.
    loader = DataLoader(dataset, batch_size=cfg.batch_size, shuffle=True, collate_fn=collator, num_workers=0)

    wrapped = T3ForFineTuning(t3_model, t3_config).to(device)

    import bitsandbytes as bnb
    optimizer = bnb.optim.AdamW8bit(t3_model.parameters(), lr=cfg.lr)

    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    step = 0
    # ponytail: resumes weights only, not optimizer state or exact step count -- good enough
    # to not throw away GPU time already spent; add full optimizer checkpointing if a crash
    # mid-run ever needs to resume losslessly.
    existing = sorted(Path(cfg.output_dir).glob("t3_odia_step*.safetensors"),
                       key=lambda p: int(p.stem.rsplit("step", 1)[1]))
    if existing:
        from safetensors.torch import load_file
        latest = existing[-1]
        t3_model.load_state_dict(load_file(str(latest)))
        step = int(latest.stem.rsplit("step", 1)[1])
        logger.info(f"Resumed weights from {latest} (step {step})")
    t0 = time.time()
    for epoch in range(cfg.num_epochs):
        for batch in loader:
            if not batch:
                continue
            batch = {k: v.to(device) for k, v in batch.items()}
            # bf16 autocast: Ada GPU does bf16 natively, no GradScaler needed (bf16 has fp32's
            # exponent range, won't underflow like fp16 does) -- free speed + VRAM headroom.
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=device.type == "cuda"):
                total_loss, _ = wrapped(
                    text_tokens=batch["text_tokens"],
                    text_token_lens=batch["text_token_lens"],
                    speech_tokens=batch["speech_tokens"],
                    speech_token_lens=batch["speech_token_lens"],
                    t3_cond_speaker_emb=batch["t3_cond_speaker_emb"],
                    t3_cond_prompt_speech_tokens=batch["t3_cond_prompt_speech_tokens"],
                    t3_cond_emotion_adv=batch["t3_cond_emotion_adv"],
                    labels_text=batch["labels_text"],
                    labels_speech=batch["labels_speech"],
                )
            (total_loss / cfg.grad_accum).backward()
            step += 1
            if step % cfg.grad_accum == 0:
                optimizer.step()
                optimizer.zero_grad()

            if step % cfg.log_every == 0:
                elapsed = time.time() - t0
                logger.info(f"epoch={epoch} step={step} loss={total_loss.item():.4f} elapsed={elapsed:.1f}s")

            if step % cfg.save_every_steps == 0:
                from safetensors.torch import save_file
                out_path = Path(cfg.output_dir) / f"t3_odia_step{step}.safetensors"
                save_file(t3_model.state_dict(), str(out_path))
                logger.info(f"Checkpoint saved: {out_path}")

        logger.info(f"Epoch {epoch} complete.")

    from safetensors.torch import save_file
    final_path = Path(cfg.output_dir) / "t3_odia_final.safetensors"
    save_file(t3_model.state_dict(), str(final_path))
    logger.info(f"Final model saved: {final_path}")


if __name__ == "__main__":
    main()
