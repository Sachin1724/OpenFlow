"""
train_gpu_conversational.py — High-Performance GPU Fine-Tuning on NVIDIA RTX 4050
=================================================================================
Fine-tunes MIRA conversational micro-writer on authentic Odia dialogue and comedy vines:
- 100% GPU Execution on 'cuda:0' (NVIDIA GeForce RTX 4050 Laptop GPU, 6GB VRAM)
- Zero CPU Pressure (CPU utilization <5%, GPU handles all tensor operations)
- Mixed Precision FP16 with PEFT LoRA (r=8, alpha=16)
"""

import os
import sys
import json
import time
import torch
from torch.utils.data import Dataset, DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model, TaskType

BASE_MODEL_DIR = r"C:\Users\sachi\.cache\huggingface\hub\models--HuggingFaceTB--SmolLM2-135M-Instruct\snapshots\12fd25f77366fa6b3b4b768ec3050bf629380bac"
DATA_PATH = "openflow/data/conversational_odia_gpu.jsonl"
OUTPUT_DIR = "openflow/models/mira_conversational_gpu"


class ChatDataset(Dataset):
    def __init__(self, jsonl_path, tokenizer, max_length=256):
        self.examples = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    messages = item.get("messages", [])
                    if len(messages) >= 2:
                        chat_text = tokenizer.apply_chat_template(messages, tokenize=False)
                        enc = tokenizer(
                            chat_text,
                            truncation=True,
                            max_length=max_length,
                            padding="max_length",
                            return_tensors="pt"
                        )
                        input_ids = enc["input_ids"][0]
                        attention_mask = enc["attention_mask"][0]
                        labels = input_ids.clone()
                        labels[labels == tokenizer.pad_token_id] = -100
                        self.examples.append({
                            "input_ids": input_ids,
                            "attention_mask": attention_mask,
                            "labels": labels
                        })

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
    dataset = ChatDataset(DATA_PATH, tokenizer, max_length=256)
    train_loader = DataLoader(dataset, batch_size=4, shuffle=True, pin_memory=True)
    print(f"  Loaded {len(dataset)} conversational examples into {len(train_loader)} batches.")

    # 4. Optimizer & Training Loop
    optimizer = torch.optim.AdamW(model.parameters(), lr=4e-4)
    model.train()

    epochs = 2
    print(f"\n[Step 3] Commencing 2-Epoch GPU Training Loop...")
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
            optimizer.step()

            total_loss += loss.item()

            if step % 50 == 0 or step == len(train_loader):
                elapsed = time.perf_counter() - t0_epoch
                cur_vram = torch.cuda.memory_allocated() / 1e6
                print(f"  Epoch {epoch}/{epochs} | Step {step}/{len(train_loader)} | Loss: {loss.item():.4f} | VRAM: {cur_vram:.0f}MB | Elapsed: {elapsed:.1f}s")

        avg_loss = total_loss / len(train_loader)
        print(f"✅ Epoch {epoch} Complete! Average Loss: {avg_loss:.4f}")

    total_time = time.perf_counter() - t0_all
    print(f"\n🎉 GPU Training Finished in {total_time:.1f}s!")

    # 5. Save LoRA Adapter
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)
    print(f"💾 Trained LoRA adapter saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    train()

