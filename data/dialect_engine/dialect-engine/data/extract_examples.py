import csv, json, re
from collections import defaultdict

SRC = "/mnt/user-data/uploads/metadata.csv"
examples = defaultdict(list)

junk_patterns = [
    r"^(yes|no|neutral|normal|gentle)\.?$",
    r"^\w+\+\w+",  # e.g. "Bhadrak+baleshwar"
    r"^(puri|kendrapara odia)$",
]

def is_junk(text):
    t = text.strip().lower()
    if not t:
        return True
    for p in junk_patterns:
        if re.match(p, t):
            return True
    if len(t) < 4:
        return True
    return False

with open(SRC, encoding="utf-8", errors="replace") as f:
    reader = csv.DictReader(f)
    for row in reader:
        dialect = (row.get("dialect") or "").strip()
        std = (row.get("standard_text") or "").strip()
        trans = (row.get("translated_text") or "").strip()
        if not dialect or not std or not trans:
            continue
        if is_junk(trans):
            continue
        # skip rows where translated_text is basically an English gloss/explanation
        # (heuristic: contains multiple common English function words AND no Odia script)
        has_odia_script = any('\u0B00' <= ch <= '\u0B7F' for ch in trans)
        examples[dialect].append({
            "standard_odia": std,
            "dialect_text": trans,
            "district": row.get("district", "").strip(),
        })

# Dedup per dialect (keep unique dialect_text per standard_odia pair)
clean = {}
for dialect, rows in examples.items():
    seen = set()
    uniq = []
    for r in rows:
        key = (r["standard_odia"], r["dialect_text"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    clean[dialect] = uniq

with open("data/dialect_examples.json", "w", encoding="utf-8") as f:
    json.dump(clean, f, ensure_ascii=False, indent=2)

for d, rows in sorted(clean.items(), key=lambda x: -len(x[1])):
    print(f"{d}: {len(rows)} usable pairs")
