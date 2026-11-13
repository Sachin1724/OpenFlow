"""
colab_train_chatterbox.py — High-Performance Google Colab / Cloud Training Script
================================================================================
Optimized for Google Colab Tesla T4 (15GB VRAM) & A100 (40GB/80GB VRAM):
- Auto-detects GPU architecture:
  * Tesla T4 (Turing, Compute 7.5): Uses FP16 Mixed Precision with GradScaler.
  * A100 / L4 (Ampere/Ada): Uses native BF16 Autocast without GradScaler.
- Uses 8-bit AdamW (bitsandbytes) to minimize optimizer memory footprint.
- Reads precomputed tensors from Google Drive (`cache_t3.pt`), zero CPU preprocessing lag.
- Checkpoints saved directly to Google Drive so no progress is ever lost.
- 100% self-contained: no external helper scripts required.
"""

import os
import sys
import glob
import ctypes
import json
import time
import logging

# Ensure CUDA 12 shared libraries (libcudart.so.12) are linked for torchaudio on Linux/Colab
cuda12_libs = sorted(glob.glob('/usr/local/lib/python*/dist-packages/nvidia/cuda_runtime/lib/libcudart.so*') +
                     glob.glob('/usr/local/cuda*/lib64/libcudart.so.12*'))
for lib in cuda12_libs:
    try:
        ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
    except Exception:
        pass
if cuda12_libs:
    os.environ['LD_LIBRARY_PATH'] = os.path.dirname(cuda12_libs[0]) + ':' + os.environ.get('LD_LIBRARY_PATH', '')
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset
from chatterbox.tts import ChatterboxTTS
from chatterbox.models.t3.t3 import T3, T3Cond

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("colab_train_chatterbox")


@dataclass
class ColabConfig:
    # Paths (relative to Google Drive or local content)
    base_dir: str = "/content/drive/MyDrive/chatterbox_odia"
    cache_path: str = "/content/drive/MyDrive/chatterbox_odia/cache_t3.pt"
    output_dir: str = "/content/drive/MyDrive/chatterbox_odia/checkpoints"
    tokenizer_path: str = "/content/drive/MyDrive/chatterbox_odia/tokenizer_odia_extended.json"

    # Training Hyperparameters
    new_vocab_size: int = 781
    batch_size: int = 2            # 2 on T4 (15GB VRAM); can be 4 or 8 on A100
    grad_accum: int = 8            # Effective batch size = batch_size * grad_accum = 16
    lr: float = 2e-5
    num_epochs: int = 1            # 1 epoch = 17,809 utterances
    save_every_steps: int = 250    # Checkpoint every 250 steps to Drive
    log_every: int = 1


def resize_and_load_t3_weights(new_model, pretrained_state_dict):
    """Loads pretrained T3 weights into a model with extended text vocabulary.
    New text-embedding/output-head rows are mean-initialized from existing tokens.
    """
    new_state = new_model.state_dict()
    emb_name = "text_emb.weight"
    head_name = "text_head.weight"

    for name, param in pretrained_state_dict.items():
        if name in (emb_name, head_name):
            continue
        if name in new_state and new_state[name].shape == param.shape:
            new_state[name].copy_(param)

    for name in (emb_name, head_name):
        old_w = pretrained_state_dict[name]
        old_n = old_w.shape[0]
        new_n = new_state[name].shape[0]
        new_state[name][:old_n, :].copy_(old_w)
        if new_n > old_n:
            mean_row = old_w.mean(dim=0)
            new_state[name][old_n:, :].copy_(mean_row.unsqueeze(0).expand(new_n - old_n, -1))
        logger.info(f"{name}: {old_n} -> {new_n} tokens ({new_n - old_n} mean-initialized for Odia)")

    new_model.load_state_dict(new_state)
    return new_model


@dataclass
class SpeechDataCollator:
    t3_config: any
    text_pad_token_id: int
    speech_pad_token_id: int

    def __call__(self, features):
        features = [f for f in features if f is not None]
        if not features:
            return {}

        batch_size = len(features)
        text_tokens_list = [f["text_tokens"] for f in features]
        speech_tokens_list = [f["speech_tokens"] for f in features]
        max_text_len = max(len(t) for t in text_tokens_list)
        max_speech_len = max(len(t) for t in speech_tokens_list)

        padded_text_tokens = torch.stack([
            F.pad(t, (0, max_text_len - len(t)), value=self.text_pad_token_id)
            for t in text_tokens_list
        ])
        padded_speech_tokens = torch.stack([
            F.pad(s, (0, max_speech_len - len(s)), value=self.speech_pad_token_id)
            for s in speech_tokens_list
        ])

        text_token_lens = torch.stack([f["text_token_lens"] for f in features])
        speech_token_lens = torch.stack([f["speech_token_lens"] for f in features])
        t3_cond_speaker_emb = torch.stack([f["t3_cond_speaker_emb"] for f in features])
        t3_cond_prompt_speech_tokens = torch.stack([f["t3_cond_prompt_speech_tokens"] for f in features])
        emotion_adv_scalars = torch.stack([f["t3_cond_emotion_adv"] for f in features])
        t3_cond_emotion_adv = emotion_adv_scalars.view(batch_size, 1, 1)

        return {
            "text_tokens": padded_text_tokens,
            "text_token_lens": text_token_lens,
            "speech_tokens": padded_speech_tokens,
            "speech_token_lens": speech_token_lens,
            "t3_cond_speaker_emb": t3_cond_speaker_emb,
            "t3_cond_prompt_speech_tokens": t3_cond_prompt_speech_tokens,
            "t3_cond_emotion_adv": t3_cond_emotion_adv,
        }


class T3ForFineTuning(torch.nn.Module):
    def __init__(self, t3_model: T3, t3_config):
        super().__init__()
        self.t3 = t3_model
        self.t3_config = t3_config

    def forward(self, text_tokens, text_token_lens, speech_tokens, speech_token_lens,
                t3_cond_speaker_emb, t3_cond_prompt_speech_tokens, t3_cond_emotion_adv):
        cond = T3Cond(
            speaker_emb=t3_cond_speaker_emb,
            cond_prompt_speech_tokens=t3_cond_prompt_speech_tokens,
            cond_prompt_speech_emb=None,
            emotion_adv=t3_cond_emotion_adv
        ).to(device=self.t3.device)

        out = self.t3.forward(
            t3_cond=cond,
            text_tokens=text_tokens,
            text_token_lens=text_token_lens,
            speech_tokens=speech_tokens,
            speech_token_lens=speech_token_lens,
            training=True,
        )

        IGNORE_ID = -100
        device = out.text_logits.device
        mask_text = torch.arange(text_tokens.size(1), device=device)[None] >= text_token_lens[:, None]
        mask_speech = torch.arange(speech_tokens.size(1), device=device)[None] >= speech_token_lens[:, None]
        masked_text = text_tokens.masked_fill(mask_text, IGNORE_ID)
        masked_speech = speech_tokens.masked_fill(mask_speech, IGNORE_ID)
        loss_text = F.cross_entropy(out.text_logits.transpose(1, 2), masked_text, ignore_index=IGNORE_ID)
        loss_speech = F.cross_entropy(out.speech_logits.transpose(1, 2), masked_speech, ignore_index=IGNORE_ID)

        return loss_text + loss_speech


def main():
    cfg = ColabConfig()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Target Compute Device: {device}")

    if device.type == "cuda":
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        logger.info(f"Detected GPU: {gpu_name} ({vram_gb:.1f} GB VRAM)")

        # Architecture detection for mixed precision
        use_bf16 = torch.cuda.is_bf16_supported()
        amp_dtype = torch.bfloat16 if use_bf16 else torch.float16
        logger.info(f"Mixed Precision Mode: {'BF16' if use_bf16 else 'FP16 (T4 Native with GradScaler)'}")
    else:
        use_bf16 = False
        amp_dtype = torch.float32

    # 1. Load Chatterbox Base Model
    logger.info("Initializing ChatterboxTTS from Hugging Face Hub (ResembleAI/chatterbox)...")
    chatterbox_model = ChatterboxTTS.from_pretrained(device="cpu")
    t3_model = chatterbox_model.t3
    t3_config = t3_model.hp

    # 2. Resize Vocab for Odia Graphemes
    if cfg.new_vocab_size != t3_config.text_tokens_dict_size:
        logger.info(f"Resizing T3 text vocab: {t3_config.text_tokens_dict_size} -> {cfg.new_vocab_size}")
        old_state = t3_model.state_dict()
        t3_config.text_tokens_dict_size = cfg.new_vocab_size
        t3_model = T3(hp=t3_config)
        t3_model = resize_and_load_t3_weights(t3_model, old_state)
        chatterbox_model.t3 = t3_model

    # Freeze non-T3 modules
    for p in chatterbox_model.ve.parameters():
        p.requires_grad = False
    for p in chatterbox_model.s3gen.parameters():
        p.requires_grad = False
    for p in t3_model.parameters():
        p.requires_grad = True

    t3_model = t3_model.to(device)
    t3_model.train()

    # 3. Load Precomputed Dataset Cache
    if not Path(cfg.cache_path).exists():
        raise FileNotFoundError(f"Missing dataset cache at {cfg.cache_path}! Please upload cache_t3.pt to Google Drive.")

    logger.info(f"Loading precomputed dataset cache from {cfg.cache_path}...")
    cached_items = torch.load(cfg.cache_path, weights_only=False)
    logger.info(f"Successfully loaded {len(cached_items)} training clips into memory.")

    collator = SpeechDataCollator(t3_config, t3_config.stop_text_token, t3_config.stop_speech_token)
    loader = DataLoader(
        cached_items,
        batch_size=cfg.batch_size,
        shuffle=True,
        collate_fn=collator,
        num_workers=2,
        pin_memory=True
    )

    wrapped = T3ForFineTuning(t3_model, t3_config).to(device)

    # 4. Optimizer & Scaler Setup
    try:
        import bitsandbytes as bnb
        optimizer = bnb.optim.AdamW8bit(t3_model.parameters(), lr=cfg.lr)
        logger.info("Using bitsandbytes AdamW8bit optimizer (memory-efficient).")
    except ImportError:
        optimizer = torch.optim.AdamW(t3_model.parameters(), lr=cfg.lr)
        logger.info("Using standard PyTorch AdamW optimizer.")

    scaler = torch.cuda.amp.GradScaler(enabled=(device.type == "cuda" and not use_bf16))

    Path(cfg.output_dir).mkdir(parents=True, exist_ok=True)
    step = 0

    # 5. Check for Existing Checkpoints to Resume Losslessly
    existing_ckpts = sorted(
        Path(cfg.output_dir).glob("t3_odia_step*.safetensors"),
        key=lambda p: int(p.stem.rsplit("step", 1)[1]) if "step" in p.stem else 0
    )
    if existing_ckpts:
        from safetensors.torch import load_file
        latest_ckpt = existing_ckpts[-1]
        t3_model.load_state_dict(load_file(str(latest_ckpt)))
        step = int(latest_ckpt.stem.rsplit("step", 1)[1])
        logger.info(f"Resumed training from checkpoint: {latest_ckpt} (Starting at Step {step})")

    t0 = time.time()
    total_steps = len(loader) * cfg.num_epochs
    logger.info(f"Beginning fine-tuning: {total_steps} total steps across {cfg.num_epochs} epoch(s).")

    for epoch in range(cfg.num_epochs):
        for batch_idx, batch in enumerate(loader):
            if not batch:
                continue

            batch = {k: v.to(device, non_blocking=True) for k, v in batch.items()}

            with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=(device.type == "cuda")):
                loss = wrapped(**batch)
                loss_scaled = loss / cfg.grad_accum

            if scaler.is_enabled():
                scaler.scale(loss_scaled).backward()
            else:
                loss_scaled.backward()

            step += 1

            if step % cfg.grad_accum == 0:
                if scaler.is_enabled():
                    scaler.unscale_(optimizer)
                    torch.nn.utils.clip_grad_norm_(t3_model.parameters(), max_norm=1.0)
                    scaler.step(optimizer)
                    scaler.update()
                else:
                    torch.nn.utils.clip_grad_norm_(t3_model.parameters(), max_norm=1.0)
                    optimizer.step()
                optimizer.zero_grad(set_to_none=True)

            if step % cfg.log_every == 0:
                elapsed = time.time() - t0
                speed = step / max(elapsed, 1e-4)
                eta_s = (total_steps - step) / max(speed, 1e-4)
                logger.info(
                    f"Epoch {epoch} | Step {step}/{total_steps} | "
                    f"Loss: {loss.item():.4f} | "
                    f"Speed: {1.0/speed:.2f}s/step | ETA: {eta_s/3600:.1f}h"
                )

            if step % cfg.save_every_steps == 0:
                from safetensors.torch import save_file
                out_path = Path(cfg.output_dir) / f"t3_odia_step{step}.safetensors"
                save_file(t3_model.state_dict(), str(out_path))
                logger.info(f"Saved checkpoint to Drive: {out_path}")

    from safetensors.torch import save_file
    final_path = Path(cfg.output_dir) / "t3_odia_final.safetensors"
    save_file(t3_model.state_dict(), str(final_path))
    logger.info(f"Training Complete! Final weights saved: {final_path}")


if __name__ == "__main__":
    main()
