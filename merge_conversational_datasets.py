"""
merge_conversational_datasets.py — Merge Harversted Scripts into GPU Dataset
=============================================================================
Aggregates all extracted dialogue pairs from real Odia podcasts and comedy videos
with synthetic and seed conversational pairs, formatted for SmolLM2 PEFT LoRA training.
"""

import os
import glob
import json
import random

def merge_datasets(harvested_dir="openflow/data/harvested_scripts",
                   output_file="openflow/data/conversational_odia_gpu.jsonl"):
    print("=" * 80)
    print("🔄 AGGREGATING HARVESTED DIALOGUES INTO GPU TRAINING DATASET")
    print("=" * 80)

    all_samples = []
    source_counts = {}

    # 1. Load all harvested dialogue pairs from YouTube
    pattern = os.path.join(harvested_dir, "*_dialogue_pairs.jsonl")
    jsonl_files = glob.glob(pattern)

    for fpath in jsonl_files:
        src_name = os.path.basename(fpath).replace("_dialogue_pairs.jsonl", "")
        count = 0
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    # Must have messages format
                    if "messages" in obj and len(obj["messages"]) >= 2:
                        user_text = obj["messages"][0]["content"].strip()
                        asst_text = obj["messages"][1]["content"].strip()
                        # Clean and filter non-trivial utterances
                        if len(user_text) >= 5 and len(asst_text) >= 5:
                            sample = {
                                "messages": [
                                    {"role": "user", "content": user_text},
                                    {"role": "assistant", "content": asst_text}
                                ],
                                "source": src_name,
                                "emotion": obj.get("emotion", "statement")
                            }
                            all_samples.append(sample)
                            count += 1
                except Exception:
                    pass
        source_counts[src_name] = count
        print(f"  + Loaded {count:,} dialogues from {src_name}")

    # 2. Add conversational backchannels & emotional grounding seeds
    grounding_seeds = [
        # Active listening & reassurance
        {"user": "ଆଜ୍ଞା ମୁଁ ଗୋଟେ କଥା ପଚାରିବାକୁ ଚାହୁଁଥିଲି", "assistant": "ହଁ ଆଜ୍ଞା କୁହନ୍ତୁ, ମୁଁ ଶୁଣୁଛି ।"},
        {"user": "କାଲି ସକାଳେ କାମଟା କେମିତି ହବ କିଛି ବୁଝିପାରୁନି", "assistant": "ଚିନ୍ତା କରନ୍ତୁନି ଭାଇନା, ସବୁ ଠିକ୍ ହେଇଯିବ । ଆମେ ମିଶିକି କରିନବା ।"},
        {"user": "ଆପଣ କଣ ମୋ କଥା ଶୁଣିପାରୁଛନ୍ତି ?", "assistant": "ହଁ ହଁ, ଶୁଣୁଛି କୁହନ୍ତୁ ।"},
        {"user": "ଆଚ୍ଛା ଏଇଟା କେମିତି କଲେ ଭଲ ହୁଅନ୍ତା ?", "assistant": "ଆଚ୍ଛା ଶୁଣନ୍ତୁ... ମୋ ମତରେ ପ୍ରଥମେ କାମଟା ସାରିଦେଲେ ସୁବିଧା ହବ ।"},
        {"user": "ଭାଇନା ଏଇ ରାସ୍ତାଟା କୋଉଆଡ଼େ ଯାଇଛି ?", "assistant": "ଏଇଟା ସିଧା କଟକ ରୋଡ୍ କୁ ଯାଇଛି ଆଜ୍ଞା ।"},
        {"user": "ଆରେ ତମେ ଏଠି କଣ କରୁଛ ବେ ?", "assistant": "ଆରେ କିଛି ନାଇଁ ଭାଇ, ଟିକେ ଏମିତି ଆସିଥିଲି ।"},
        {"user": "କାଲି ମ୍ୟାଚ୍ କିଏ ଜିତିଲା କହିଲ ?", "assistant": "ଇଣ୍ଡିଆ ପରା ଜିତିଗଲା ! ବଢିଆ ଖେଳିଲେ ସମସ୍ତେ ।"},
        {"user": "ତମେ ମୋ ଉପରେ ରାଗିଛ କି ?", "assistant": "ନା ନାଇଁ, ଆପଣଙ୍କ ଉପରେ କାହିଁକି ରାଗିବି ? ମୁଁ ଜମା ବି ରାଗିନି ।"},
        {"user": "ଧତ୍ ତେରିକା ଏ କାମଟା ଆଜି ବି ହେଲାନି !", "assistant": "ଧୈର୍ଯ୍ୟ ଧରନ୍ତୁ, ଆଜି ନହେଲେ କାଲି ସକାଳେ ନିଶ୍ଚୟ ହେଇଯିବ ।"},
        {"user": "ଆଜି ବର୍ଷା ହବ ବୋଲି ଲାଗୁଛି କି ?", "assistant": "ହଁ, ପାଗ ତ ପୁରା ମେଘୁଆ କରିଛି, ବୋଧେ ଛେଞ୍ଚିବ ବର୍ଷା ।"}
    ]

    # Replicate seeds to give strong emotional balance
    for s in grounding_seeds:
        for _ in range(25):
            all_samples.append({
                "messages": [
                    {"role": "user", "content": s["user"]},
                    {"role": "assistant", "content": s["assistant"]}
                ],
                "source": "grounding_seeds",
                "emotion": "conversational"
            })
    source_counts["grounding_seeds"] = len(grounding_seeds) * 25
    print(f"  + Added {source_counts['grounding_seeds']:,} conversational emotional grounding seeds")

    # Shuffle for uniform training distribution
    random.seed(42)
    random.shuffle(all_samples)

    # 3. Write merged dataset
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        for s in all_samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    print("-" * 80)
    print(f"✅ Total Merged Dataset: {len(all_samples):,} dialogue samples")
    print(f"📁 Output File: {output_file}")
    print("=" * 80)
    return len(all_samples)

if __name__ == "__main__":
    merge_datasets()

