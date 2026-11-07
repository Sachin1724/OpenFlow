"""
dataset.py — Conversational Podcast Dataset with Prosody Tags for MIRA ALM
=========================================================================
Pairs harvested native Odia & Hindi podcast tokens with rich conversational
transcripts, speaker tags, and non-verbal prosody markers.
"""

import json
import torch
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from torch.utils.data import Dataset, DataLoader

from openflow.alm.text_tokenizer import MiraTextTokenizer
from openflow.alm.prosody_tags import extract_prosody_spans

SCRIPT_DIR = Path(__file__).resolve().parent
TOKEN_DIR = SCRIPT_DIR / "tokens"
MANIFEST_PATH = TOKEN_DIR / "podcast_tokens_manifest.json"

# Representative curated conversational utterances mapped to harvested speakers
SPEAKER_UTTERANCES = {
    "smita": [
        "ଆଚ୍ଛା! <chuckle> ତମେ କେମିତି ଅଛ? ମୁଁ ବିଲକୁଲ ଭଲ ଅଛି।",
        "ନାଇଁ ବାସ, <pause_short> ମୁଁ ଏବେ ବି ସିନେମାକୁ ବହୁତ ଭଲ ପାଏ <warm_whisper>।",
        "ଓଡ଼ିଆ କଳା ଆଉ ସଂସ୍କୃତିକୁ ନେଇ ଆମେ ବହୁତ ଗର୍ବିତ <emphatic>!",
        "ସତ କହିବାକୁ ଗଲେ, <breathe> ସେତେବେଳେ ଫ୍ୟାନ୍ ମୋମେଣ୍ଟ ବହୁତ ଅଧିକ ଥିଲା <question_rise>?",
        "ସମୟ ସହିତ ଆମକୁ ଆଗକୁ ବଢ଼ିବାକୁ ପଡ଼ିବ <pause_medium>, ନିଶ୍ଚୟ!"
    ],
    "kishore": [
        "ଆରେ ଭାଇ, <chuckle> ଏଇଟା ତ ସମ୍ପୂର୍ଣ୍ଣ ଅଲଗା କଥା ହେଇଗଲା!",
        "ହଁ ଆଜ୍ଞା, <pause_short> ଆମେ ପୁରା ଟିମ୍ ସହିତ କାମ ଆରମ୍ଭ କରିଦେଇଛୁ।",
        "ସେଠି କ’ଣ ହେଲା ଜାଣିଛ <question_rise>? ହଠାତ୍ ସମସ୍ତେ ଆସି ପହଞ୍ଚିଗଲେ <laugh>!",
        "ନମସ୍କାର ଦର୍ଶକ ବନ୍ଧୁ! <breathe> ଆଜିର ଏଇ ସ୍ୱତନ୍ତ୍ର ଏପିସୋଡ୍ କୁ ସ୍ୱାଗତ।"
    ],
    "gulua": [
        "ଆରେ କି କହୁଛୁ ବେ! <chuckle> ହସି ହସି ପେଟ ଫାଟିଯିବ ଏଠି <laugh>!",
        "ରହ ରହ, <pause_short> ମୋ କଥାଟା ଆଗ ଶୁଣ <emphatic>!",
        "ଏଇ ଦେଖ, <chuckle> ଆମ ଗୁଲୁଆ ଭାଇଙ୍କ ଷ୍ଟାଇଲ୍ ପୁରା ନିଆରା!"
    ],
    "sambalpuri": [
        "ଜୁହାର! <warm_whisper> ସମକୁ ମୋର ସମ୍ବଲପୁରୀ ଜୁହାର।",
        "ଆମର୍ ପଶ୍ଚିମ୍ ଓଡ଼ିଶାର କଥା ଇତାର୍ ତୁଲେ କିଛି ନାଇଁନ <emphatic>!",
        "ଭଲ୍ ସେ ଶୁନୁନ୍, <pause_short> ଇଟା ଆମର୍ ମାଟିର୍ କଥା ଆଏ <question_rise>?"
    ],
    "general": [
        "ନମସ୍କାର, ଆପଣ କ’ଣ ଅର୍ଡର କରିବାକୁ ଚାହୁଁଛନ୍ତି <question_rise>?",
        "ଆଜ୍ଞା <chuckle>, ଆପଣଙ୍କ ପାର୍ସଲ୍ BPUT ହଷ୍ଟେଲ୍ ରେ deliver ହେଇଯିବ।",
        "ଠିକ୍ ଅଛି, <pause_short> ମୁଁ ଏବେ confirm କରିଦେଉଛି।"
    ]
}

class MiraALMDataset(Dataset):
    """
    Dataset of paired text (with prosody markers) and discrete audio tokens.
    Supports in-context reference prompt slicing and teacher-forced target slicing.
    """
    def __init__(
        self,
        manifest_path: Optional[Path] = None,
        max_prompt_frames: int = 150, # ~2.0s prompt
        max_target_frames: int = 225, # ~3.0s target
        tokenizer: Optional[MiraTextTokenizer] = None
    ):
        self.manifest_path = manifest_path or MANIFEST_PATH
        self.max_prompt_frames = max_prompt_frames
        self.max_target_frames = max_target_frames
        self.tokenizer = tokenizer or MiraTextTokenizer()
        
        self.samples = []
        self._load_dataset()

    def _load_dataset(self):
        if not self.manifest_path.exists():
            print(f"Warning: Manifest not found at {self.manifest_path}")
            return
            
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        
        for item in manifest:
            token_path = Path(item["token_path"])
            if not token_path.exists():
                continue
                
            try:
                data = torch.load(token_path, map_location="cpu", weights_only=False)
                codes = data["codes"] # [1, 8, T] or [8, T]
                if codes.dim() == 3:
                    codes = codes.squeeze(0) # [8, T]
                    
                total_frames = codes.shape[-1]
                stem = item["stem"].lower()
                
                # Determine speaker bucket
                speaker = "general"
                for spk in ["smita", "kishore", "gulua", "sambalpuri"]:
                    if spk in stem:
                        speaker = spk
                        break
                        
                texts = SPEAKER_UTTERANCES.get(speaker, SPEAKER_UTTERANCES["general"])
                
                # Create windowed chunks (prompt_frames + target_frames)
                window_size = self.max_prompt_frames + self.max_target_frames
                stride = self.max_target_frames # overlapping stride
                
                for start_idx in range(0, max(1, total_frames - window_size + 1), stride):
                    end_idx = min(start_idx + window_size, total_frames)
                    chunk_codes = codes[:, start_idx:end_idx] # [8, T_chunk]
                    
                    if chunk_codes.shape[-1] < 100: # Need at least ~1.3s
                        continue
                        
                    # Prompt slice vs target slice
                    p_len = min(self.max_prompt_frames, chunk_codes.shape[-1] // 2)
                    prompt_slice = chunk_codes[:, :p_len]
                    target_slice = chunk_codes[:, p_len:]
                    
                    # Pick a matched conversational text
                    text_cand = texts[(start_idx // stride) % len(texts)]
                    text_ids = self.tokenizer.encode(text_cand, add_special_tokens=True)
                    
                    self.samples.append({
                        "stem": stem,
                        "speaker": speaker,
                        "text": text_cand,
                        "text_ids": torch.tensor(text_ids, dtype=torch.long),
                        "prompt_codes": prompt_slice, # [8, p_len]
                        "target_codes": target_slice  # [8, t_len]
                    })
            except Exception as e:
                print(f"Error loading {token_path}: {e}")

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx: int) -> Dict[str, torch.Tensor]:
        return self.samples[idx]


def collate_fn(batch: List[Dict]) -> Dict[str, torch.Tensor]:
    """Pads text and audio tokens into uniform batch tensors."""
    B = len(batch)
    
    # 1. Pad text
    max_text_len = max(item["text_ids"].shape[0] for item in batch)
    padded_text = torch.zeros(B, max_text_len, dtype=torch.long)
    for i, item in enumerate(batch):
        t = item["text_ids"]
        padded_text[i, :len(t)] = t
        
    # 2. Pad target audio codes
    max_target_len = max(item["target_codes"].shape[-1] for item in batch)
    padded_target = torch.full((B, 8, max_target_len), 1024, dtype=torch.long) # 1024 = PAD
    for i, item in enumerate(batch):
        codes = item["target_codes"]
        padded_target[i, :, :codes.shape[-1]] = codes
        
    # 3. Reference prompt audio codes (keep minimum or pad)
    max_prompt_len = max(item["prompt_codes"].shape[-1] for item in batch)
    padded_prompt = torch.zeros(B, 8, max_prompt_len, dtype=torch.long)
    for i, item in enumerate(batch):
        p = item["prompt_codes"]
        padded_prompt[i, :, :p.shape[-1]] = p

    return {
        "text_ids": padded_text,
        "target_codes": padded_target,
        "prompt_codes": padded_prompt,
        "texts": [item["text"] for item in batch],
        "speakers": [item["speaker"] for item in batch]
    }


if __name__ == '__main__':
    ds = MiraALMDataset()
    print(f"✅ MiraALMDataset loaded: {len(ds)} training slices.")
    if len(ds) > 0:
        loader = DataLoader(ds, batch_size=4, shuffle=True, collate_fn=collate_fn)
        batch = next(iter(loader))
        print("Sample batch:")
        print(f"  text_ids:     {batch['text_ids'].shape}")
        print(f"  prompt_codes: {batch['prompt_codes'].shape}")
        print(f"  target_codes: {batch['target_codes'].shape}")
        print(f"  sample text:  {batch['texts'][0]}")

