"""
score_pronunciation.py - Objective pronunciation score for the Odia TTS voices.

"It fumbles some words" is not a signal you can tune or train against. This closes
the loop: synthesize a sentence, run the synthesized audio back through the
IndicConformer Odia ASR, and compare the recognized text to the text we asked for.
Character error rate against our own input is the fumbling metric -- a smeared
consonant or a swallowed syllable shows up as a substitution or deletion.

The ASR is itself imperfect (CER 5.5% on FLEURS test), so the absolute number is a
floor, not zero. What matters is the delta between configurations on the same
sentences, and the gap to the human reference recordings scored the same way.

  python score_pronunciation.py                      # score current male config
  python score_pronunciation.py --voice male --sweep  # compare conv_mode / pacing
  python score_pronunciation.py --human              # score the human reference clips
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

# Odia output to a cp1252 console raises UnicodeEncodeError and kills the run.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Sentences cover what actually fumbles: dense consonant clusters, English loanwords,
# retroflex/dental contrasts, conjuncts, and long multi-clause turns.
EVAL_SET = [
    "ନମସ୍କାର, ମୁଁ ମୀରା ।",
    "ଆଜି ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି ?",
    "ଭୁବନେଶ୍ୱରରେ ଏବେ ଟ୍ରାଫିକ ଟିକେ ଅଧିକ ଅଛି ।",
    "ମୋର ନାମ ସଚିନ, ମୁଁ ମେକାନିକାଲ ଇଞ୍ଜିନିୟରିଂ ପଢ଼ିଛି ।",
    "ଆର୍ଟିଫିସିଆଲ ଇଣ୍ଟେଲିଜେନ୍ସ ଏବଂ ଟେକ୍ନୋଲୋଜି କ୍ଷେତ୍ରରେ କାମ କରୁଛି ।",
    "ଏହି ପ୍ରକଳ୍ପଟି ସମ୍ପୂର୍ଣ୍ଣ ଭାବରେ ଅଫଲାଇନ କାମ କରେ ।",
    "ଆପଣ ଦୟାକରି ଟିକେ ଅପେକ୍ଷା କରନ୍ତୁ, ମୁଁ ଯାଞ୍ଚ କରୁଛି ।",
    "ଶୁକ୍ରବାର ଦିନ ବୈଠକ ଅଛି, ସକାଳ ଦଶଟାରେ ଆରମ୍ଭ ହେବ ।",
    "ସତରେ ଭଲ ଅଛି, ଜଗନ୍ନାଥଙ୍କ ଆଶୀର୍ବାଦ ଅଛି ।",
    "ଏହା ଏକ ବହୁତ ଗୁରୁତ୍ୱପୂର୍ଣ୍ଣ ପ୍ରଶ୍ନ, ଏବଂ ମୁଁ ଏହାର ଉତ୍ତର ଦେବାକୁ ଚେଷ୍ଟା କରିବି ।",
]


def edit_distance(a: str, b: str) -> int:
    """Levenshtein, iterative two-row. Reference is `a`."""
    if not a:
        return len(b)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _norm_for_cer(text: str) -> str:
    """Strip what the ASR cannot emit anyway: punctuation, Latin, collapsed whitespace.
    Without this, every danda and comma counts as a deletion and swamps the real errors."""
    keep = [c for c in text if ("଀" <= c <= "୿") or c == " "]
    return " ".join("".join(keep).split())


def cer(reference: str, hypothesis: str) -> float:
    r, h = _norm_for_cer(reference), _norm_for_cer(hypothesis)
    if not r:
        return 0.0
    return edit_distance(r, h) / len(r)


def wer(reference: str, hypothesis: str) -> float:
    r, h = _norm_for_cer(reference).split(), _norm_for_cer(hypothesis).split()
    if not r:
        return 0.0
    # same DP over word tokens
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r)


def load_asr():
    from huggingface_hub import snapshot_download
    from engine.indic_asr import IndicCTC
    snap = snapshot_download("sachinmallick/openflow-odia-asr-int8")
    return IndicCTC(os.path.join(snap, "or"), threads=8)


def to_16k(audio: np.ndarray, sr: int) -> np.ndarray:
    """ASR expects 16 kHz; the TTS renders 24 kHz."""
    if sr == 16000:
        return audio.astype(np.float32)
    import torch
    import torchaudio.functional as AF
    t = torch.from_numpy(np.asarray(audio, dtype=np.float32))
    return AF.resample(t, sr, 16000).numpy()


def score_config(engine, asr, label: str, sentences, save_dir: Path = None, **synth_kw):
    """Synthesize each sentence under one config and score it. Returns per-config summary."""
    rows = []
    for idx, text in enumerate(sentences):
        wav = engine.synthesize(text, **synth_kw)
        if len(wav) == 0:
            continue
        hyp = asr.text(to_16k(wav, engine.sr), beam=True)
        rows.append({
            "text": text,
            "asr": hyp,
            "cer": cer(text, hyp),
            "wer": wer(text, hyp),
            "dur": len(wav) / engine.sr,
            "chars_per_s": len(_norm_for_cer(text)) / (len(wav) / engine.sr),
        })
        if save_dir:
            save_dir.mkdir(parents=True, exist_ok=True)
            engine.save_wav(wav, str(save_dir / f"{label}_{idx:02d}.wav"))
    summary = {
        "config": label,
        "cer": float(np.mean([r["cer"] for r in rows])),
        "wer": float(np.mean([r["wer"] for r in rows])),
        "chars_per_s": float(np.mean([r["chars_per_s"] for r in rows])),
        "n": len(rows),
        "rows": rows,
    }
    return summary


def print_summary(s: dict, verbose: bool = False):
    print(f"{s['config']:34s} CER={s['cer']*100:5.2f}%  WER={s['wer']*100:5.2f}%  "
          f"pace={s['chars_per_s']:4.1f} ch/s  n={s['n']}")
    if verbose:
        for r in sorted(s["rows"], key=lambda r: -r["cer"]):
            print(f"    CER {r['cer']*100:5.1f}%  want: {r['text']}")
            print(f"                 got : {r['asr']}")


def score_human(asr):
    """Same metric on the human reference recordings, to show the achievable floor.
    Needs a transcript next to each wav; falls back to ASR-only output if absent."""
    import soundfile as sf
    refs = [
        _REPO_ROOT / "models" / "smita_mohanty_pure_female_speech.wav",
        _REPO_ROOT / "models" / "female_voice_reference.wav",
    ]
    for p in refs:
        if not p.exists():
            print(f"missing {p}")
            continue
        wav, sr = sf.read(str(p), dtype="float32")
        if wav.ndim > 1:
            wav = wav.mean(-1)
        print(f"{p.name}: {asr.text(to_16k(wav, sr), beam=True)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="male", choices=["male", "female"])
    ap.add_argument("--sweep", action="store_true", help="compare inference configs")
    ap.add_argument("--human", action="store_true", help="score human reference clips")
    ap.add_argument("--save", default=None, help="directory to write the rendered wavs")
    ap.add_argument("--json", default=None, help="write the full result as JSON")
    ap.add_argument("-v", "--verbose", action="store_true", help="per-sentence errors")
    args = ap.parse_args()

    asr = load_asr()
    if args.human:
        return score_human(asr)

    from engine.studio_voice import StudioVoiceEngine
    engine = StudioVoiceEngine(voice_persona=args.voice)
    save_dir = Path(args.save) if args.save else None

    if args.sweep:
        # The reference male podcast speakers sit at 13.9-15.1 ch/s (median 14.3). The base
        # voice renders 13.1 ch/s, so pace is one scalar away from the references -- sweep it
        # directly instead of training a duration predictor, which measured 6x worse.
        configs = [("speed=%.2f" % sp, dict(speed=sp)) for sp in
                   (1.00, 1.05, 1.10, 1.15, 1.20)]
    else:
        configs = [("current default", {})]

    results = []
    for label, kw in configs:
        s = score_config(engine, asr, label, EVAL_SET,
                         save_dir=save_dir, voice=args.voice, **kw)
        results.append(s)
        print_summary(s, args.verbose)

    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")


if __name__ == "__main__":
    # Self-check the metric before trusting any number it prints.
    assert edit_distance("କାମ", "କାମ") == 0
    assert edit_distance("କାମ", "କାମା") == 1
    assert cer("ନମସ୍କାର ।", "ନମସ୍କାର") == 0.0, "punctuation must not count as an error"
    assert abs(wer("ଭଲ ଅଛି ମାନସ", "ଭଲ ଅଛି") - 1 / 3) < 1e-9
    assert cer("", "") == 0.0
    main()
