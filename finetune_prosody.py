"""
finetune_prosody.py - Teach the Odia Matcha acoustic model conversational rhythm.

The shipped model is trained on AI4Bharat Rasa read speech, so it reproduces the
average prosody of someone reading sentences aloud. This fine-tunes it on the
harvested podcast turns (data/podcasts/user_harvest/manifest_merged.jsonl).

Default trains the duration predictor + style embedding only: that is where rhythm
and pause length live, it is a tiny fraction of the weights, and it cannot damage
timbre. --full also unfreezes the encoder and CFM decoder, which is where pitch
contour lives, at the cost of overfitting risk on ~1h of audio.

  python finetune_prosody.py --smoke          # verify mel pipeline, no training
  python finetune_prosody.py                  # train rhythm only (safe)
  python finetune_prosody.py --full --epochs 30
"""
import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import torchaudio
from safetensors.torch import save_file

from engine.studio_voice import get_studio_voice

MANIFEST = Path("data/podcasts/female_harvest/manifest_female_combined.jsonl")
CKPT = Path("models/odia_female_prosody_ft.safetensors")
SR, N_FFT, HOP, N_MELS, F_MAX = 24000, 1024, 256, 100, 12000.0
OUT_FRAMES = 192          # Matcha random-segment trick; ~2s at hop 256
MAX_DUR_S = 14.0


def mel_transform(device):
    """Must match the features Vocos was trained on: config vocoder.source is
    charactr/vocos-mel-24khz (magnitude mel, slaney, n_fft 1024 / hop 256 / 100 mels)."""
    return torchaudio.transforms.MelSpectrogram(
        sample_rate=SR, n_fft=N_FFT, win_length=N_FFT, hop_length=HOP,
        n_mels=N_MELS, f_min=0.0, f_max=F_MAX, center=True, power=1.0).to(device)
    # torchaudio defaults (norm=None, mel_scale="htk") are what Vocos uses; slaney
    # filter normalization divides each filter by its bandwidth and shifts log-mel down.


def log_mel(mel_fn, wav: torch.Tensor) -> torch.Tensor:
    return torch.log(torch.clamp(mel_fn(wav), min=1e-7))


def speech_level(y: torch.Tensor) -> float:
    """Mean normalized-mel over the louder half of frames, i.e. ignoring silence.
    Comparing this between corpora is loudness without the silence-ratio confound."""
    per_frame = y.mean(dim=0)
    return float(y[:, per_frame >= per_frame.median()].mean())


def model_speech_level(tts, mel_fn, device) -> float:
    """Target level, measured from the pretrained model's own output rather than
    assumed. Podcast audio is loudness-compressed; without this the fine-tune would
    teach the model to emit systematically hotter mels than its vocoder expects."""
    from indic_tiny_tts.infer import LANG_ID, STYLE_ID
    lines = ["ନମସ୍କାର, ମୁଁ ମୀରା ।", "ଆଜି ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି ?",
             "ଭୁବନେଶ୍ୱରରେ ଏବେ ଟ୍ରାଫିକ ଟିକେ ଅଧିକ ଅଛି ।"]
    levels = []
    with torch.inference_mode():
        for line in lines:
            ids = tts._ids(tts.normalize(line))
            res = tts.acoustic.synthesise(
                torch.tensor([ids], device=device), torch.tensor([len(ids)], device=device),
                torch.tensor([LANG_ID["or"]], device=device),
                torch.tensor([tts.speaker_rows["or_F"]], device=device),
                torch.tensor([STYLE_ID["conv"]], device=device), n_timesteps=4)
            mel = res["mel"][0, :, :int(res["mel_lengths"][0])]
            levels.append(speech_level((mel - tts.acoustic.mel_mean) / tts.acoustic.mel_std))
    return float(np.mean(levels))


def _resolve_path(p: str | Path) -> Path:
    p = Path(p)
    if p.exists():
        return p
    if (Path("openflow") / p).exists():
        return Path("openflow") / p
    if p.parts and p.parts[0] == "openflow":
        stripped = Path(*p.parts[1:])
        if stripped.exists():
            return stripped
    return p


def load_rows(manifest_path: Path, gender: str, speaker: str | None):
    manifest_path = _resolve_path(manifest_path)
    rows = [json.loads(l) for l in open(manifest_path, encoding="utf-8")]
    rows = [r for r in rows if r["dur"] <= MAX_DUR_S]
    if speaker:
        rows = [r for r in rows if r["speaker"] == speaker]
    elif gender != "all":
        rows = [r for r in rows if r.get("gender") == gender]
    return rows


def build_batch(tts, mel_fn, rows, device, mel_mean, mel_std, target_level):
    xs, ys = [], []
    for r in rows:
        ids = tts._ids(tts.normalize(r["text"]))
        if not ids:
            continue
        wav_file = _resolve_path(r["wav"])
        if not wav_file.exists():
            continue
        wav, sr = sf.read(str(wav_file), dtype="float32")
        if sr != SR or len(wav) < HOP * 8:
            continue
        y = (log_mel(mel_fn, torch.from_numpy(wav).to(device)) - mel_mean) / mel_std
        y = y + (target_level - speech_level(y))     # match the model's own output level
        if y.shape[-1] <= len(ids):          # fewer mel frames than tokens: MAS cannot align
            continue
        xs.append(torch.tensor(ids, dtype=torch.long))
        ys.append(y)
    if not xs:
        return None
    x_len = torch.tensor([len(x) for x in xs], device=device)
    y_len = torch.tensor([y.shape[-1] for y in ys], device=device)
    x = torch.zeros(len(xs), int(x_len.max()), dtype=torch.long, device=device)
    y = torch.zeros(len(ys), N_MELS, int(y_len.max()), device=device)
    for i, (xi, yi) in enumerate(zip(xs, ys)):
        x[i, :len(xi)] = xi.to(device)
        y[i, :, :yi.shape[-1]] = yi
    return x, x_len, y, y_len


def smoke(tts, mel_fn, rows, device, mel_mean, mel_std):
    """If our mel extraction matches what the model was trained on, the normalized
    dataset mel is ~N(0,1) and a vocoder round-trip of the model's own mel
    reproduces that mel. Both are cheap and decisive."""
    target = model_speech_level(tts, mel_fn, device)
    raw, lvl = [], []
    for r in rows[:40]:
        wav, _ = sf.read(r["wav"], dtype="float32")
        y = (log_mel(mel_fn, torch.from_numpy(wav).to(device)) - mel_mean) / mel_std
        raw.append(speech_level(y))
        lvl.append(speech_level(y + (target - speech_level(y))))
    m = float(np.mean(raw))
    s = float(np.mean(lvl))
    print(f"model speech level={target:+.3f}  dataset raw={m:+.3f}  after match={s:+.3f}")

    from indic_tiny_tts.infer import LANG_ID, STYLE_ID
    with torch.inference_mode():
        ids = tts._ids(tts.normalize("ନମସ୍କାର, ମୁଁ ମୀରା ।"))
        res = tts.acoustic.synthesise(
            torch.tensor([ids], device=device), torch.tensor([len(ids)], device=device),
            torch.tensor([LANG_ID["or"]], device=device),
            torch.tensor([tts.speaker_rows["or_F"]], device=device),
            torch.tensor([STYLE_ID["conv"]], device=device), n_timesteps=4)
        ref = res["mel"][0, :, :int(res["mel_lengths"][0])]
        audio = tts.vocoder.decode(ref.unsqueeze(0).float()).squeeze().clamp(-1, 1)
        back = log_mel(mel_fn, audio)
        n = min(ref.shape[-1], back.shape[-1])
        err = float((ref[:, :n] - back[:, :n]).abs().mean())
    print(f"vocoder mel round-trip abs error: {err:.3f} log units")
    assert abs(s - target) < 0.05, "level match failed"
    assert err < 0.8, "mel extraction does not match the vocoder's expected features"
    print("smoke OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default=str(MANIFEST))
    ap.add_argument("--out", default=str(CKPT))
    ap.add_argument("--gender", default="female", choices=["female", "male", "all"])
    ap.add_argument("--speaker", default=None, help="train one merged cluster only")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--full", action="store_true", help="also train encoder + CFM decoder")
    ap.add_argument("--resume", action="store_true", help="resume from existing checkpoint")
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()

    torch.manual_seed(0)
    random.seed(0)
    eng = get_studio_voice("female")
    tts, device = eng.tts, eng.tts.device
    mel_fn = mel_transform(device)
    mel_mean, mel_std = float(tts.acoustic.mel_mean), float(tts.acoustic.mel_std)

    manifest_path = Path(args.manifest)
    out_ckpt = Path(args.out)
    rows = load_rows(manifest_path, args.gender, args.speaker)
    print(f"{len(rows)} clips, {sum(r['dur'] for r in rows)/60:.1f} min, device={device}")
    if args.smoke:
        return smoke(tts, mel_fn, rows, device, mel_mean, mel_std)

    target_level = model_speech_level(tts, mel_fn, device)
    print(f"target speech level {target_level:+.3f} (measured from pretrained output)")

    from indic_tiny_tts.infer import LANG_ID, STYLE_ID
    model = tts.acoustic
    if args.resume and out_ckpt.exists():
        from safetensors.torch import load_file
        print(f"Resuming fine-tuning from checkpoint: {out_ckpt}")
        model.load_state_dict(load_file(str(out_ckpt)), strict=False)
    spk_row = tts.speaker_rows["or_M" if args.gender == "male" else "or_F"]

    for p in model.parameters():
        p.requires_grad_(False)
    train_mods = [model.encoder.proj_w, model.style_emb, model.spk_emb]     # duration predictor + style + speaker embedding
    if args.full:
        train_mods += [model.encoder, model.decoder]
    for mod in train_mods:
        for p in mod.parameters():
            p.requires_grad_(True)
    params = [p for p in model.parameters() if p.requires_grad]
    total = sum(p.numel() for p in model.parameters())
    print(f"training {sum(p.numel() for p in params)/1e6:.2f}M / {total/1e6:.2f}M params")

    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=1e-6)
    random.shuffle(rows)
    cut = max(1, len(rows) // 20)
    val, train = rows[:cut], rows[cut:]

    def run(subset, training: bool):
        tot, nb = defaultdict(float), 0
        model.train(training)
        for i in range(0, len(subset), args.batch):
            batch = build_batch(tts, mel_fn, subset[i:i + args.batch], device,
                                mel_mean, mel_std, target_level)
            if batch is None:
                continue
            x, x_len, y, y_len = batch
            b = x.shape[0]
            with torch.set_grad_enabled(training):
                out = model(x, x_len, y, y_len,
                            torch.full((b,), LANG_ID["or"], device=device),
                            torch.full((b,), spk_row, device=device),
                            torch.full((b,), STYLE_ID["conv"], device=device),
                            out_size=OUT_FRAMES)
                loss = out["dur_loss"] + out["prior_loss"] + out["diff_loss"]
            if not torch.isfinite(loss):
                continue
            if training:
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 5.0)
                opt.step()
            for k in ("dur_loss", "prior_loss", "diff_loss"):
                tot[k] += float(out[k])
            tot["loss"] += float(loss)
            nb += 1
        return {k: v / max(nb, 1) for k, v in tot.items()}

    best = float("inf")
    for ep in range(1, args.epochs + 1):
        random.shuffle(train)
        tr = run(train, True)
        va = run(val, False)
        flag = ""
        if va["loss"] < best:
            best = va["loss"]
            out_ckpt.parent.mkdir(exist_ok=True)
            save_file({k: v.cpu().contiguous() for k, v in model.state_dict().items()}, str(out_ckpt))
            flag = " *saved"
        print(f"epoch {ep:3d}/{args.epochs}  train={tr['loss']:.4f} "
              f"(dur={tr['dur_loss']:.4f} prior={tr['prior_loss']:.4f} diff={tr['diff_loss']:.4f})"
              f"  val={va['loss']:.4f}{flag}", flush=True)

    print(f"best val {best:.4f} -> {out_ckpt}")


if __name__ == "__main__":
    main()
