"""
compare_prosody.py - A/B the prosody fine-tune against the shipped read-speech model.

Writes scratch/prosody_base.wav and scratch/prosody_ft.wav for listening, and reports
per-token predicted durations. The complaint being tested is metronomic rhythm, so the
measure is spread of token durations: a read-speech model gives every token nearly the
same length, a conversational speaker does not.
"""
import numpy as np
import torch
from safetensors.torch import load_file

from engine.studio_voice import get_studio_voice

CKPT = "models/odia_prosody_ft.safetensors"
LINES = [
    "ନମସ୍କାର ଭାଇ । ମୁଁ ମୀରା, ଆପଣଙ୍କ ଓଡ଼ିଆ ସାଥୀ । ଆଜି କଣ କଥା ହେବା ?",
    "ଆଚ୍ଛା, ସତ କହିବାକୁ ଗଲେ ଭୁବନେଶ୍ୱରରେ ଏବେ ଟ୍ରାଫିକ ଟିକେ ଅଧିକ ଅଛି ।",
]


def durations_for(eng, text):
    """Per-token frame durations the duration predictor assigns."""
    from indic_tiny_tts.infer import LANG_ID, STYLE_ID
    tts = eng.tts
    dev = tts.device
    ids = tts._ids(tts.normalize(text))
    with torch.inference_mode():
        res = tts.acoustic.synthesise(
            torch.tensor([ids], device=dev), torch.tensor([len(ids)], device=dev),
            torch.tensor([LANG_ID["or"]], device=dev),
            torch.tensor([tts.speaker_rows["or_F"]], device=dev),
            torch.tensor([STYLE_ID["conv"]], device=dev), n_timesteps=4)
    return res["durations"][0].float().cpu().numpy()


def report(tag, eng):
    out = []
    for i, line in enumerate(LINES):
        d = durations_for(eng, line)
        out.append(d)
        print(f"  {tag} line{i+1}: tokens={len(d)} mean={d.mean():.2f} "
              f"std={d.std():.2f} cv={d.std()/d.mean():.3f} max={d.max():.0f}")
    audio = eng.synthesize(" ".join(LINES))
    eng.save_wav(audio, f"scratch/prosody_{tag}.wav")
    print(f"  {tag}: {len(audio)/eng.sr:.2f}s -> scratch/prosody_{tag}.wav")
    return np.concatenate(out)


def main():
    eng = get_studio_voice("female")
    base_sd = {k: v.clone() for k, v in eng.tts.acoustic.state_dict().items()}

    print("baseline (shipped read-speech model):")
    base = report("base", eng)

    eng.tts.acoustic.load_state_dict(load_file(CKPT), strict=True)
    eng.tts.acoustic.eval()
    print("fine-tuned (podcast prosody):")
    ft = report("ft", eng)

    eng.tts.acoustic.load_state_dict(base_sd, strict=True)   # leave the engine as found
    print(f"\nduration spread (coefficient of variation, higher = less metronomic)")
    print(f"  baseline   cv={base.std()/base.mean():.3f}")
    print(f"  fine-tuned cv={ft.std()/ft.mean():.3f}")
    print(f"  change     {100*((ft.std()/ft.mean())/(base.std()/base.mean())-1):+.1f}%")


if __name__ == "__main__":
    main()
