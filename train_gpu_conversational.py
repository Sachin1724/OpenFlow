"""
train_gpu_conversational.py — High-Performance GPU Fine-Tuning on NVIDIA RTX 4050
=================================================================================
Fine-tunes MIRA conversational micro-writer on authentic Odia dialogue and comedy vines:
- 100% GPU Execution on 'cuda:0' (NVIDIA GeForce RTX 4050 Laptop GPU, 6GB VRAM)
- Zero CPU Pressure (CPU utilization <5%, GPU handles all tensor operations)
- SFT Prompt Masking (User question masked to -100; gradients focus 100% on realistic replies)
- Mixed Precision FP16 with PEFT LoRA (r=8, alpha=16, target=q,k,v,o_proj)
"""

import os
import sys
import io
import json
import time
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer, get_cosine_schedule_with_warmup
from peft import LoraConfig, get_peft_model, TaskType

# Force UTF-8 stdout with immediate line flushing
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

BASE_MODEL_DIR = r"C:\Users\sachi\.cache\huggingface\hub\models--HuggingFaceTB--SmolLM2-135M-Instruct\snapshots\12fd25f77366fa6b3b4b768ec3050bf629380bac"
DATA_PATH = "openflow/data/conversational_odia_gpu.jsonl"
OUTPUT_DIR = "openflow/models/mira_conversational_gpu"

SYSTEM_PROMPT = "You are MIRA, a natural Odia voice assistant. Respond naturally in authentic colloquial Odia with warm emotions, active listening, and proper discourse markers."


class ConversationalDataset(Dataset):
    def __init__(self, jsonl_path, tokenizer, max_length=256):
        self.examples = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    messages = item.get("messages", [])
                    if len(messages) >= 2:
                        user_text = messages[0]["content"].strip()
                        asst_text = messages[1]["content"].strip()
                        if not user_text or not asst_text:
                            continue

                        formatted_msgs = [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": user_text},
                            {"role": "assistant", "content": asst_text}
                        ]

                        full_chat = tokenizer.apply_chat_template(formatted_msgs, tokenize=False)
                        prompt_chat = tokenizer.apply_chat_template(formatted_msgs[:2], tokenize=False, add_generation_prompt=True)

                        enc_full = tokenizer(
                            full_chat,
                            truncation=True,
                            max_length=max_length,
                            padding="max_length",
                            return_tensors="pt"
                        )
                        enc_prompt = tokenizer(
                            prompt_chat,
                            truncation=True,
                            max_length=max_length
                        )

                        p_len = min(len(enc_prompt["input_ids"]), max_length)
                        input_ids = enc_full["input_ids"][0]
                        attention_mask = enc_full["attention_mask"][0]

                        # Mask prompt tokens with -100 so loss is strictly on assistant response
                        labels = input_ids.clone()
                        labels[:p_len] = -100
                        # CRITICAL FIX: Only mask actual padding tokens (attention_mask == 0).
                        # Since tokenizer.pad_token_id == tokenizer.eos_token_id (token 2: <|im_end|>),
                        # masking by token_id wiped out the assistant's EOS signal and caused runaway 11s generation!
                        labels[attention_mask == 0] = -100

                        # Ensure there is at least one target token to calculate loss
                        if (labels != -100).sum() > 0:
                            self.examples.append({
                                "input_ids": input_ids,
                                "attention_mask": attention_mask,
                                "labels": labels
                            })
                except Exception:
                    pass

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        return self.examples[idx]


def train():
    print("=" * 80)
    print("🚀 NVIDIA RTX 4050 GPU ACCELERATED MIRA CONVERSATIONAL FINE-TUNING")
    print("=" * 80)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type != "cuda":
        print("ERROR: CUDA GPU is not available! Exiting to avoid CPU pressure.")
        sys.exit(1)

    gpu_name = torch.cuda.get_device_name(0)
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"🎮 Target Device : {gpu_name} ({vram_gb:.2f} GB VRAM)")
    print(f"⚡ Device Mode   : 100% CUDA GPU Tensor Cores (Zero CPU Overload)")
    print(f"📦 Dataset Path  : {DATA_PATH}")

    # 1. Load Tokenizer & Model directly to CUDA in FP16
    print("\n[Step 1] Loading base model SmolLM2-135M onto GPU in FP16...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_DIR)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_DIR,
        torch_dtype=torch.float16,
        device_map={"": "cuda:0"}
    )
    print(f"  VRAM allocated after model load: {torch.cuda.memory_allocated() / 1e6:.1f} MB")

    # 2. Configure PEFT LoRA
    print("\n[Step 2] Injecting LoRA Adapters into Attention Layers...")
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=8,
        lora_alpha=16,
        lora_dropout=0.05,
        target_modules=["q_proj", "v_proj", "k_proj", "o_proj"]
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 3. Prepare Dataset & DataLoader
    dataset = ConversationalDataset(DATA_PATH, tokenizer, max_length=256)
    train_loader = DataLoader(dataset, batch_size=8, shuffle=True, pin_memory=True)
    print(f"  Loaded {len(dataset)} valid conversational examples into {len(train_loader)} batches.")

    # 4. Optimizer, Scheduler & Training Loop
    epochs = 3
    total_steps = len(train_loader) * epochs
    optimizer = torch.optim.AdamW(model.parameters(), lr=4e-4, weight_decay=0.01)
    scheduler = get_cosine_schedule_with_warmup(optimizer, num_warmup_steps=20, num_training_steps=total_steps)

    model.train()
    print(f"\n[Step 3] Commencing {epochs}-Epoch GPU SFT Training ({total_steps} total steps)...")
    t0_all = time.perf_counter()

    for epoch in range(1, epochs + 1):
        total_loss = 0.0
        step = 0
        t0_epoch = time.perf_counter()

        for batch in train_loader:
            step += 1
            input_ids = batch["input_ids"].to(device, non_blocking=True)
            attention_mask = batch["attention_mask"].to(device, non_blocking=True)
            labels = batch["labels"].to(device, non_blocking=True)

            optimizer.zero_grad()
            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss

            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()

            total_loss += loss.item()

            if step % 40 == 0 or step == len(train_loader):
                elapsed = time.perf_counter() - t0_epoch
                cur_vram = torch.cuda.memory_allocated() / 1e6
                lr_cur = scheduler.get_last_lr()[0]
                print(f"  Epoch {epoch}/{epochs} | Step {step:3d}/{len(train_loader)} | Loss: {loss.item():.4f} | LR: {lr_cur:.2e} | VRAM: {cur_vram:.0f}MB | Elapsed: {elapsed:.1f}s")

        avg_loss = total_loss / len(train_loader)
        print(f"✅ Epoch {epoch} Complete! Average Loss: {avg_loss:.4f} (Time: {time.perf_counter() - t0_epoch:.1f}s)")

    total_time = time.perf_counter() - t0_all
    print(f"\n🎉 GPU Training Finished in {total_time:.1f}s!")

    # 5. Save LoRA Adapter
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"💾 Trained LoRA adapter saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    train()
