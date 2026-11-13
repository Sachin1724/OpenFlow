"""Fine-tunes the Odia IndicConformer with reinforcement learning on word error rate.

Policy gradient with a self-critical baseline (SCST): for each clip the model samples a few
transcripts from its CTC posteriors, each is rewarded with minus its word error rate, and the
greedy transcript's reward is the baseline, so only samples that beat the model's own best guess
are reinforced. A CTC loss on the reference text keeps the model anchored while it explores.

Data: SPRINGLab/IndicTTS_Odia (11.5k studio sentences, 2 speakers; 400 held out for testing) plus
FLEURS Odia train (3.4 h, many speakers), repeated 3x so studio voices don't dominate: trained on
IndicTTS alone, the model improved on those 2 voices and got worse on everyone else.
Model selection on FLEURS Odia dev; FLEURS test stays untouched until the end.

Run from the repo's parent:
  python -m openflow.train_odia_rl prep <indictts parquet dir> <fleurs or_in dir> <work dir>
  python -m openflow.train_odia_rl train <fp32 model.onnx> <work dir>
  python -m openflow.train_odia_rl export <work dir>          # best.pt -> int8 model.onnx
"""
import glob
import io
import json
import os
import sys
import tarfile
import time
import csv

import numpy as np

from openflow.bench_odia import edits, norm
from openflow.engine.indic_asr import ctc_greedy, features, odia_only

SR = 16000
SAMPLES, ALPHA_PG = 4, 0.05   # transcripts sampled per clip; weight of the RL loss next to CTC
LR, STEPS, EVAL_EVERY = 5e-6, 6000, 500
FLEURS_REPEAT = 3
MAX_FRAMES = 2000            # feature frames per batch (10 ms each): ~20 s of audio, fits 6 GB


# ---------- data ----------

def _to16k(data: bytes):
    import soundfile
    from scipy.signal import resample_poly
    a, sr = soundfile.read(io.BytesIO(data), dtype="float32")
    if a.ndim > 1:
        a = a.mean(1)
    return (resample_poly(a, SR, sr) if sr != SR else a).astype(np.float32)


def _save(path, clips):
    audio = [np.clip(a * 32767, -32768, 32767).astype(np.int16) for a, _ in clips]
    np.savez(path, audio=np.concatenate(audio), lens=np.array([len(a) for a in audio]),
             texts=np.array([t for _, t in clips]))


def _load(path):
    d = np.load(path)
    audio, offs = d["audio"], np.concatenate([[0], np.cumsum(d["lens"])])  # read the array once
    return [(audio[offs[i]:offs[i + 1]], str(t)) for i, t in enumerate(d["texts"])]


def prep(parquets, fleurs, work):
    import pyarrow.parquet as pq
    os.makedirs(work, exist_ok=True)
    clips = []
    for p in sorted(glob.glob(os.path.join(parquets, "**", "*.parquet"), recursive=True)):
        t = pq.read_table(p, columns=["audio", "text"])
        for i in range(len(t)):
            row = t.slice(i, 1).to_pylist()[0]
            clips.append((_to16k(row["audio"]["bytes"]), row["text"]))
        print(p, len(clips))
    order = np.random.default_rng(0).permutation(len(clips))
    _save(os.path.join(work, "tts_test.npz"), [clips[i] for i in order[:400]])
    _save(os.path.join(work, "tts_train.npz"), [clips[i] for i in order[400:]])
    for split in ("train", "dev", "test"):
        with open(os.path.join(fleurs, f"{split}.tsv"), encoding="utf-8") as f:
            refs = {r[1]: r[3] for r in csv.reader(f, delimiter="\t", quoting=csv.QUOTE_NONE)}
        out = []
        with tarfile.open(os.path.join(fleurs, "audio", f"{split}.tar.gz"), "r:gz") as tar:
            for m in tar:
                name = m.name.rsplit("/", 1)[-1]
                if m.isfile() and name in refs:
                    out.append((_to16k(tar.extractfile(m).read()), refs[name]))
        _save(os.path.join(work, f"fleurs_{split}.npz"), out)
        print(split, len(out))


# ---------- tokens and scoring ----------

class Pieces:
    """Reference text -> CTC targets over the Odia pieces of the shared vocab.

    The model's SentencePiece model isn't shipped with the ONNX export, and a different split of the
    same word into pieces teaches the model new word boundaries. So each word is split the way the
    model itself splits it when it gets the word right (learn()); unseen words use longest match."""

    def __init__(self, vocab):
        self.vocab = vocab
        self.ids = {p: i for i, p in enumerate(vocab) if odia_only(vocab)[i] == 0}
        self.longest = max(len(p) for p in self.ids)
        self.seen = {}

    def learn(self, id_seqs, refs):
        from collections import Counter
        counts = {}
        for ids, ref in zip(id_seqs, refs):
            words = set(norm(ref).split())
            word = []
            for i in list(ids) + [None]:
                if (i is None or self.vocab[i].startswith("▁")) and word:
                    text = "".join(self.vocab[j] for j in word)[1:]
                    if text in words:
                        counts.setdefault(text, Counter())[tuple(word)] += 1
                    word = []
                if i is not None:
                    word.append(i)
        self.seen = {w: list(c.most_common(1)[0][0]) for w, c in counts.items()}

    def encode(self, text):
        out = []
        for word in norm(text).split():
            if word in self.seen:
                out += self.seen[word]
                continue
            s, i = "▁" + word, 0
            while i < len(s):
                for n in range(min(self.longest, len(s) - i), 0, -1):
                    if s[i:i + n] in self.ids:
                        out.append(self.ids[s[i:i + n]])
                        i += n
                        break
                else:
                    return None  # a character no Odia piece covers: skip the clip
        return out


def wer(ref, hyp):
    r = norm(ref).split()
    return edits(r, norm(hyp).split()) / max(1, len(r))


def score(texts, refs):
    w = [0, 0, 0, 0]
    for h, r in zip(texts, refs):
        r, h = norm(r), norm(h)
        w[0] += edits(r.split(), h.split()); w[1] += len(r.split())
        w[2] += edits(r.replace(" ", ""), h.replace(" ", "")); w[3] += len(r.replace(" ", ""))
    return 100 * w[0] / w[1], 100 * w[2] / w[3]


# ---------- model ----------

def load_model(path):
    """ONNX (fp32) -> torch via onnx2torch; its weights arrive as buffers, so make them trainable."""
    import onnx
    import torch
    from onnx2torch import convert
    model = convert(onnx.load(path)) if path.endswith(".onnx") else torch.load(path, weights_only=False)
    init = model.initializers
    for name, buf in list(init.named_buffers(recurse=False)):
        if buf.is_floating_point() and buf.numel() >= 64:
            del init._buffers[name]
            init.register_parameter(name, torch.nn.Parameter(buf))
    return model


def batches(clips, pieces, rng):
    order = rng.permutation(len(clips))
    batch, frames = [], 0
    for i in order:
        audio, text = clips[i]
        n = len(audio) // 160 + 1
        if batch and frames + n > MAX_FRAMES:
            yield batch
            batch, frames = [], 0
        batch.append((audio, text))
        frames += n
    if batch:
        yield batch


def forward(model, audios, augment, rng):
    import torch
    feats = [features(a.astype(np.float32) / 32767) for a in audios]
    if augment:  # SpecAugment: two frequency and two time masks per clip
        for f in feats:
            for _ in range(2):
                w = rng.integers(0, 15); s = rng.integers(0, 80 - w); f[s:s + w] = 0
                w = rng.integers(0, max(1, min(40, f.shape[1] // 10))); s = rng.integers(0, max(1, f.shape[1] - w)); f[:, s:s + w] = 0
    T = max(f.shape[1] for f in feats)
    x = np.zeros((len(feats), 80, T), np.float32)
    for i, f in enumerate(feats):
        x[i, :, :f.shape[1]] = f
    lens = torch.tensor([f.shape[1] for f in feats], device="cuda")
    with torch.autocast("cuda", dtype=torch.bfloat16):
        out = model(torch.from_numpy(x).cuda(), lens)
    out = out[0] if isinstance(out, (tuple, list)) else out
    out_lens = torch.div(lens - 1, 4, rounding_mode="floor") + 1  # 4x subsampling, as the model does
    return out, out_lens.clamp(max=out.shape[1])


def greedy_ids(model, clips, mask):
    """Collapsed CTC piece ids of the greedy transcript of each clip."""
    import torch
    model.train(False)
    out = []
    with torch.no_grad():
        for i in range(0, len(clips), 8):
            logp, lens = forward(model, [a for a, _ in clips[i:i + 8]], False, None)
            best = (logp.float().cpu().numpy() + mask).argmax(-1)
            for j, n in enumerate(lens.tolist()):
                ids, prev = [], -1
                for t in best[j, :n]:
                    if t != prev and t < len(mask) - 1:
                        ids.append(int(t))
                    prev = t
                out.append(ids)
    model.train(True)
    return out


def transcribe(model, clips, mask, vocab, lm=None):
    import torch
    from openflow.engine.indic_asr import ctc_beam_lm
    model.train(False)
    texts = []
    with torch.no_grad():
        for i in range(0, len(clips), 8):
            chunk = clips[i:i + 8]
            logp, lens = forward(model, [a for a, _ in chunk], False, None)
            logp = logp.float().cpu().numpy() + mask
            for j, n in enumerate(lens.tolist()):
                lp = logp[j, :n]
                texts.append(ctc_beam_lm(lp, vocab, lm, 0.15, 1.0, 16) if lm else ctc_greedy(lp.argmax(-1), vocab))
    model.train(True)
    return texts


def train(onnx_path, work, steps=STEPS):
    import torch
    import torch.nn.functional as F
    vocab = json.load(open(os.path.join(os.path.dirname(onnx_path), "vocab.json"), encoding="utf-8"))
    pieces, mask = Pieces(vocab), odia_only(vocab)
    mask_t = torch.from_numpy(mask).cuda()
    blank = len(vocab)
    tts_test, dev = _load(os.path.join(work, "tts_test.npz")), _load(os.path.join(work, "fleurs_dev.npz"))
    model = load_model(onnx_path).cuda()
    train_clips = _load(os.path.join(work, "tts_train.npz")) + _load(os.path.join(work, "fleurs_train.npz")) * FLEURS_REPEAT
    pieces.learn(greedy_ids(model, train_clips, mask), [t for _, t in train_clips])
    train_clips = [(a, t) for a, t in train_clips if pieces.encode(t)]
    print(f"{len(train_clips)} training clips, {len(pieces.seen)} words split as the model splits them")

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=LR, weight_decay=0.0)
    rng = np.random.default_rng(1)
    log = open(os.path.join(work, "train.log"), "a", encoding="utf-8")

    def evaluate(step):
        d = score(transcribe(model, dev, mask, vocab), [t for _, t in dev])
        s = score(transcribe(model, tts_test, mask, vocab), [t for _, t in tts_test])
        line = f"step {step}: FLEURS dev WER {d[0]:.2f} CER {d[1]:.2f} | IndicTTS test WER {s[0]:.2f} CER {s[1]:.2f}"
        print(line); log.write(line + "\n"); log.flush()
        return d[0]

    best = evaluate(0)
    torch.save(model, os.path.join(work, "best.pt"))
    step, t0 = 0, time.time()
    while step < steps:
        for batch in batches(train_clips, pieces, rng):
            logp, lens = forward(model, [a for a, _ in batch], True, rng)
            logp = torch.log_softmax(logp.float() + mask_t, -1)  # Odia pieces only, renormalised
            targets = [torch.tensor(pieces.encode(t)) for _, t in batch]
            ctc = F.ctc_loss(logp.transpose(0, 1), torch.cat(targets).cuda(), lens,
                             torch.tensor([len(t) for t in targets]), blank=blank, zero_infinity=True)
            # RL: sample transcripts, reward = -WER, baseline = the greedy transcript's reward
            pg = []
            greedy = logp.argmax(-1).cpu().numpy()
            for j, (_, ref) in enumerate(batch):
                n = int(lens[j])
                base = -wer(ref, ctc_greedy(greedy[j, :n], vocab))
                dist = torch.distributions.Categorical(logits=logp[j, :n].detach())
                for _ in range(SAMPLES):
                    path = dist.sample()
                    r = -wer(ref, ctc_greedy(path.cpu().numpy(), vocab))
                    if r != base:
                        pg.append((r - base) * logp[j, :n].gather(1, path[:, None]).sum() / n)
            rl = -torch.stack(pg).sum() / (len(batch) * SAMPLES) if pg else logp.sum() * 0
            loss = ctc + ALPHA_PG * rl
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            step += 1
            if step % 10 == 0:
                print(f"step {step} ctc {ctc.item():.3f} rl {rl.item():.4f} ({time.time() - t0:.0f}s)", flush=True)
            if step % EVAL_EVERY == 0:
                w = evaluate(step)
                if w < best:
                    best = w
                    torch.save(model, os.path.join(work, "best.pt"))
                    print(f"  new best {best:.2f}")
            if step >= steps:
                break


def export(work):
    """best.pt -> fp32 ONNX -> int8 (MatMul weights), the format the app ships."""
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    model = torch.load(os.path.join(work, "best.pt"), weights_only=False).cpu().train(False)
    x, n = torch.zeros(1, 80, 500), torch.tensor([500])
    fp32, int8 = os.path.join(work, "model_fp32.onnx"), os.path.join(work, "model.onnx")
    torch.onnx.export(model, (x, n), fp32, input_names=["audio_signal", "length"], output_names=["logprobs"],
                      dynamic_axes={"audio_signal": {0: "b", 2: "t"}, "length": {0: "b"}, "logprobs": {0: "b", 1: "t"}},
                      opset_version=17)
    quantize_dynamic(fp32, int8, op_types_to_quantize=["MatMul"], weight_type=QuantType.QInt8)
    print("->", int8, os.path.getsize(int8) // 2**20, "MB")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"prep": prep, "train": train, "export": export}[cmd](*args)
