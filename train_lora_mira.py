"""
train_lora_mira.py — LoRA Fine-Tuning for MIRA Micro-Writer on NVIDIA RTX 4050
=============================================================================
Fine-tunes SmolLM2-135M on 2,500 authentic Odia dialect pairs, talk-show podcast
dialogues, and real-world speech refinement seeds.
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
DATA_PATH = "openflow/data/mira_train.jsonl"
OUTPUT_DIR = "openflow/models/mira_lora"
MERGED_DIR = "openflow/models/mira_merged"


class ChatDataset(Dataset):
    def __init__(self, jsonl_path, tokenizer, max_length=256):
        self.examples = []
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    messages = item.get("messages", [])
                    if len(messages) >= 3:
                        # Format as chat template
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
                        # Set padding tokens to -100 in labels so loss is computed only on content
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


def main():
    print("=" * 80)
    print("MIRA MICRO-WRITER LORA FINE-TUNING PIPELINE")
    print(f"Device: {torch.cuda.get_device_name(0)} (VRAM: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.1f} GB)")
    print("=" * 80)

    # 1. Load Tokenizer & Model
    print("[1/5] Loading SmolLM2-135M base model on CUDA...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL_DIR)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL_DIR,
        dtype=torch.float16,
        device_map="cuda"
    )

    # 2. Setup LoRA
    print("[2/5] Injecting LoRA adapters (r=16, alpha=32)...")
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
    )
    model = get_peft_model(model, peft_config)
    model.print_trainable_parameters()

    # 3. Load Dataset
    print(f"[3/5] Loading training dataset from {DATA_PATH}...")
    dataset = ChatDataset(DATA_PATH, tokenizer, max_length=256)
    print(f"Loaded {len(dataset)} training examples.")
    dataloader = DataLoader(dataset, batch_size=8, shuffle=True)

    # 4. Training Loop
    print("[4/5] Starting LoRA fine-tuning for 200 optimization steps...")
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.01)
    model.train()

    step = 0
    max_steps = 200
    t0 = time.time()

    while step < max_steps:
        for batch in dataloader:
            step += 1
            input_ids = batch["input_ids"].cuda()
            attention_mask = batch["attention_mask"].cuda()
            labels = batch["labels"].cuda()

            optimizer.zero_grad()
            outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
            loss = outputs.loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

            if step % 20 == 0 or step == max_steps:
                elapsed = time.time() - t0
                speed = step / elapsed
                print(f"  Step {step:3d}/{max_steps} | Loss: {loss.item():.4f} | Speed: {speed:.1f} steps/s | Elapsed: {elapsed:.1f}s")

            if step >= max_steps:
                break

    train_time = time.time() - t0
    print(f"\n[MIRA Fine-Tuning Complete] Trained in {train_time:.1f} seconds on NVIDIA RTX 4050!")

    # 5. Save LoRA Adapters
    print(f"[5/5] Saving LoRA adapter to {OUTPUT_DIR}...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    model.save_pretrained(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    # 6. Merge LoRA into Base Model for Fast Inference
    print(f"[Export] Merging LoRA weights into standalone base model -> {MERGED_DIR}...")
    merged_model = model.merge_and_unload()
    os.makedirs(MERGED_DIR, exist_ok=True)
    merged_model.save_pretrained(MERGED_DIR)
    tokenizer.save_pretrained(MERGED_DIR)
    print("=" * 80)
    print(f"SUCCESS: MIRA standalone fine-tuned model saved to {MERGED_DIR}!")
    print("=" * 80)


if __name__ == "__main__":
    main()

