"""
train_alm.py — Train & Fine-Tune MIRA DualAR Audio Language Model
================================================================
Trains MIRA-ALM on native Odia & Hindi podcast tokens with prosody markers.
Optimized for NVIDIA RTX 4050 GPU using CUDA and mixed precision (FP16).
"""

import os
import sys
import time
import torch
import torch.nn as nn
from pathlib import Path
from torch.utils.data import DataLoader

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from alm.model import MiraALMModel, MiraALMConfig
from alm.dataset import MiraALMDataset, collate_fn

CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

def train_alm(
    epochs: int = 30,
    batch_size: int = 4,
    lr: float = 3e-4,
    device: str = "cuda" if torch.cuda.is_available() else "cpu"
):
    print("=" * 80)
    print("🚀 TRAINING MIRA AUDIO LANGUAGE MODEL (ALM) ON NATIVE ODIA PODCASTS")
    print(f"Device: {device} | Target: NVIDIA RTX 4050 GPU (DualAR)")
    print("=" * 80)
    
    dataset = MiraALMDataset()
    if len(dataset) == 0:
        print("❌ Dataset is empty. Harvest tokens first.")
        return
        
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, collate_fn=collate_fn)
    
    config = MiraALMConfig()
    model = MiraALMModel(config).to(device)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"Model parameters: {total_params / 1e6:.2f}M | Training slices: {len(dataset)}")
    
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-2)
    scaler = torch.amp.GradScaler('cuda', enabled=(device == 'cuda'))
    
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
        optimizer, T_max=epochs * len(loader), eta_min=1e-5
    )
    
    best_loss = float('inf')
    start_time = time.time()
    
    for epoch in range(1, epochs + 1):
        model.train()
        total_loss = 0.0
        cb0_loss_total = 0.0
        fine_loss_total = 0.0
        steps = 0
        
        for batch in loader:
            text_ids = batch["text_ids"].to(device)
            target_codes = batch["target_codes"].to(device)
            
            optimizer.zero_grad()
            
            with torch.amp.autocast('cuda', enabled=(device == 'cuda')):
                outputs = model(text_ids, target_codes)
                loss = outputs["loss"]
                
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            
            total_loss += loss.item()
            cb0_loss_total += outputs["loss_cb0"].item()
            fine_loss_total += outputs["loss_fine"].item()
            steps += 1
            
        avg_loss = total_loss / steps
        avg_cb0 = cb0_loss_total / steps
        avg_fine = fine_loss_total / steps
        
        if epoch % 5 == 0 or epoch == 1 or epoch == epochs:
            elapsed = time.time() - start_time
            print(f"Epoch [{epoch:02d}/{epochs:02d}] | Loss: {avg_loss:.4f} (CB0: {avg_cb0:.4f}, Fine: {avg_fine:.4f}) | Elapsed: {elapsed:.1f}s")
            
        if avg_loss < best_loss:
            best_loss = avg_loss
            checkpoint_path = CHECKPOINT_DIR / "mira_alm_best.pt"
            torch.save({
                "epoch": epoch,
                "config": config,
                "model_state_dict": model.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "loss": best_loss
            }, checkpoint_path)
            
    # Save final model
    final_path = CHECKPOINT_DIR / "mira_alm_v1.pt"
    torch.save({
        "epoch": epochs,
        "config": config,
        "model_state_dict": model.state_dict(),
        "loss": avg_loss
    }, final_path)
    
    total_time = time.time() - start_time
    print("=" * 80)
    print(f"✅ MIRA-ALM Training Completed in {total_time:.1f}s!")
    print(f"Best Loss: {best_loss:.4f} | Saved to: {final_path}")
    print("=" * 80)
    return final_path

if __name__ == '__main__':
    train_alm(epochs=25, batch_size=4)

