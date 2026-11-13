"""
train_mira_v2.py — MIRA v2: SmolLM2-135M-Instruct LoRA writer that cleans English dictation.
==============================================================================================
Fixes over v1 (train_lora_mira.py):
  - v1 masked the pad token in the labels, and pad == <|im_end|> for SmolLM2, so the model never
    learned to stop. v2 trains on the answer only, end token included; padding is masked by position.
  - v1's English data was 78 unique pairs repeated with filler prefixes, so it memorised and invented
    content. v2 learns from Google FLEURS English (CC-BY-4.0): 'transcription' (lowercase, unpunctuated,
    what a recogniser emits) -> 'raw_transcription' (the human text), plus the same sentences with
    spoken disfluencies added. The target never adds or drops words, so MIRA learns form, not content.
  - Scope is Latin-script text. Odia script stays with engine/odia_refine.py: SmolLM2's tokenizer spends
    ~17 tokens per Odia word, too slow for dictation.
Writes models/mira_v2_merged and the app's int8 CTranslate2 build models/mira_v2_ct2_int8.
Run from the repo's parent:  python -m openflow.train_mira_v2
"""
import csv
import io
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.request

import torch
from peft import LoraConfig, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer

from openflow.engine.local_llm import MIRA_SYSTEM

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = r"C:\Users\sachi\.cache\huggingface\hub\models--HuggingFaceTB--SmolLM2-135M-Instruct\snapshots\12fd25f77366fa6b3b4b768ec3050bf629380bac"
FLEURS = "https://huggingface.co/datasets/google/fleurs/resolve/main/data/en_us/{}.tsv"
MERGED = os.path.join(HERE, "models", "mira_v2_merged")
CT2 = os.path.join(HERE, "models", "mira_v2_ct2_int8")
FILLERS = ["um", "uh", "you know", "like", "so", "basically", "i mean"]
ODIA = re.compile("[\u0B00-\u0B7F]")
WORD = re.compile(r"[a-z0-9]+")


def fleurs(split):
    """Unique (spoken, written) sentence pairs from one FLEURS English split."""
    with urllib.request.urlopen(FLEURS.format(split)) as r:
        rows = csv.reader(io.TextIOWrapper(r, encoding="utf-8"), delimiter="\t", quoting=csv.QUOTE_NONE)
        return sorted({(row[3], row[2].replace("’", "'")) for row in rows if len(row) > 3})


def disfluent(text, rng):
    """The same words as someone might say them: a filler or two, maybe a stutter."""
    words = text.split()
    for _ in range(rng.choice((1, 1, 2))):
        words.insert(rng.randrange(len(words) + 1), rng.choice(FILLERS))
    if rng.random() < 0.3 and words:
        i = rng.randrange(len(words))
        words.insert(i, words[i])
    return " ".join(words)


def adds_words(spoken, written):
    """True when the written side has words the speaker never said (v1's sign-offs, invented details)."""
    said = set(WORD.findall(spoken.lower()))
    new = [w for w in WORD.findall(written.lower()) if w not in said]
    return len(new) > max(1, len(said) // 10)


def examples(rng):
    pairs = []
    for spoken, written in fleurs("train"):
        pairs.append((spoken, written))
        pairs.append((disfluent(spoken, rng), written))
    v1 = set()
    for line in open(os.path.join(HERE, "data", "mira_train.jsonl"), encoding="utf-8"):
        m = json.loads(line)["messages"]
        spoken, written = m[1]["content"].removeprefix("Raw speech: "), m[2]["content"]
        if not ODIA.search(spoken + written) and not adds_words(spoken, written):
            v1.add((spoken, written))
    rng.shuffle(pairs)
    return pairs + sorted(v1), len(v1)


def encode(tok, spoken, written, max_len):
    """Prompt tokens are context only; the model is trained on the answer and its end token."""
    msgs = [{"role": "system", "content": MIRA_SYSTEM.format(style="smart_clean")},
            {"role": "user", "content": f"Raw speech: {spoken}"}]
    prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    p = tok(prompt, add_special_tokens=False)["input_ids"]
    a = tok(written + "<|im_end|>", add_special_tokens=False)["input_ids"]
    ids = (p + a)[:max_len]
    return ids, ([-100] * len(p) + a)[:max_len]


def main():
    rng = random.Random(7)
    pairs, n_v1 = examples(rng)
    print(f"{len(pairs)} training pairs ({n_v1} kept from v1)")
    tok = AutoTokenizer.from_pretrained(BASE)
    data = [encode(tok, s, w, 384) for s, w in pairs]

    model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.float32).cuda()
    model = get_peft_model(model, LoraConfig(task_type=TaskType.CAUSAL_LM, r=16, lora_alpha=32, lora_dropout=0.05,
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                                             "gate_proj", "up_proj", "down_proj"]))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4, weight_decay=0.01)
    epochs, bs = 2, 16
    steps = epochs * ((len(data) + bs - 1) // bs)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=2e-4, total_steps=steps, pct_start=0.05)
    model.train()
    step, t0 = 0, time.time()
    for _ in range(epochs):
        rng.shuffle(data)
        for i in range(0, len(data), bs):
            batch = data[i:i + bs]
            n = max(len(ids) for ids, _ in batch)
            ids = torch.tensor([x + [tok.pad_token_id] * (n - len(x)) for x, _ in batch]).cuda()
            labels = torch.tensor([y + [-100] * (n - len(y)) for _, y in batch]).cuda()  # padding by position
            mask = torch.tensor([[1] * len(x) + [0] * (n - len(x)) for x, _ in batch]).cuda()
            loss = model(input_ids=ids, attention_mask=mask, labels=labels).loss
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            step += 1
            if step % 50 == 0 or step == steps:
                print(f"  step {step}/{steps}  loss {loss.item():.4f}  {time.time() - t0:.0f}s")

    merged = model.merge_and_unload()
    merged.save_pretrained(MERGED)
    tok.save_pretrained(MERGED)
    subprocess.run([sys.executable, "-m", "ctranslate2.converters.transformers", "--model", MERGED,
                    "--output_dir", CT2, "--quantization", "int8", "--copy_files", "tokenizer.json", "--force"],
                   check=True)
    print(f"MIRA v2 -> {CT2}")


if __name__ == "__main__":
    assert not adds_words("send the invoice to sarah", "Send the invoice to Sarah.")
    assert adds_words("hi team let me know by eod", "Hi Team, please let me know by EOD. Best regards, Rahul")
    main()
