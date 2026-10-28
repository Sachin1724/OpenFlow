"""
translator.py — Odia text to English, offline (AI4Bharat IndicTrans2, distilled 200M)
====================================================================================
Runs the CTranslate2 build of IndicTrans2 Indic->En (MIT) through ctranslate2, which
faster-whisper already installs; sentencepiece is the only extra package.

Preprocessing follows IndicTrans2's inference/engine.py for Odia sources: split off
punctuation, map Odia letters onto Devanagari (the model's shared script), sentencepiece,
then the "ory_Orya eng_Latn" tags. URL/email placeholders are skipped: speech has none.
"""

import os
import re
import string

_PUNCT = re.compile(r"([" + re.escape(string.punctuation) + "।॥])")
_ODIA_DIGITS = {chr(0x0B66 + i): str(i) for i in range(10)}
_SENTENCE_END = re.compile(r"(?<=[।॥.?!])\s+")
_MAX_WORDS = 60  # model takes 160 subword tokens; CTC output has no full stops to split on


def odia_to_devanagari(text: str) -> str:
    """indic-nlp UnicodeIndicTransliterator('or' -> 'hi'): same offset in the parallel Unicode block."""
    out = []
    for c in text:
        off = ord(c) - 0x0B00
        out.append(chr(0x0900 + off) if 0 <= off <= 0x6F else c)
    return "".join(out)


def preprocess(sent: str) -> str:
    sent = "".join(_ODIA_DIGITS.get(c, c) for c in sent)
    sent = " ".join(_PUNCT.sub(r" \1 ", sent).split())
    return odia_to_devanagari(sent).replace(" ् ", "्")


def detokenize(pieces) -> str:
    """Sentencepiece pieces -> English, then undo the spaces Moses tokenization left around punctuation."""
    s = "".join(pieces).replace("▁", " ").strip()
    s = re.sub(r" ([.,!?;:%)\]}])", r"\1", s)
    s = re.sub(r"([(\[{$]) ", r"\1", s)
    return re.sub(r"(\w) ?' ?(t|s|re|ve|ll|d|m)\b", r"\1'\2", s)  # "don 't", "it ' s" -> "don't", "it's"


def chunks(text: str):
    """Sentences, and long unpunctuated dictations cut every _MAX_WORDS words."""
    for sent in _SENTENCE_END.split(text.strip()):
        words = sent.split()
        for i in range(0, len(words), _MAX_WORDS):
            yield " ".join(words[i:i + _MAX_WORDS])


class OdiaToEnglish:
    def __init__(self, folder: str, threads: int = 4, device: str = "cpu"):
        import ctranslate2
        import sentencepiece as spm
        self.sp = spm.SentencePieceProcessor(model_file=os.path.join(folder, "vocab", "model.SRC"))
        self.tr = ctranslate2.Translator(folder, device=device, compute_type="int8", intra_threads=threads)

    def translate(self, text: str) -> str:
        sents = [s for s in chunks(text) if s]
        if not sents:
            return ""
        batch = [["ory_Orya", "eng_Latn"] + self.sp.encode(preprocess(s), out_type=str) for s in sents]
        res = self.tr.translate_batch(batch, beam_size=2, max_input_length=160, max_decoding_length=256)
        return " ".join(detokenize(r.hypotheses[0]) for r in res)


if __name__ == "__main__":
    assert odia_to_devanagari("ଭଲ") == "भल"
    assert preprocess("ଭଲ, ୨୦୨୬।") == "भल , 2026 ।"
    assert detokenize(["▁It", "▁is", "▁good", "▁."]) == "It is good."
    assert detokenize(["▁don", "▁'", "t", "▁joke"]) == "don't joke"
    assert detokenize(["▁the", "▁students", "'", "▁books"]) == "the students' books"
    assert list(chunks("କ ଖ। ଗ")) == ["କ ଖ।", "ଗ"] and len(list(chunks("ଏ " * 130))) == 3
    print("ok")
