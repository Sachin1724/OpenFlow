"""
local_llm.py — MIRA: Multilingual Intelligent Refinement Agent (offline SLM)
=============================================================================
Runs on-device lightweight language models (Qwen2.5-0.5B/1.5B or SmolLM2)
quantized to int8 CTranslate2 for ultra-fast offline dictation refinement:
- Restores punctuation, capitalization, and paragraphing.
- Eliminates vocal stutters and filler words without dropping real content.
- Preserves technical identifiers, Indian English idioms, and Odia/Hindi code-mixing.
- Executes in ~80ms-150ms on CPU. Zero cloud latency. Zero data egress.
"""

import os
import re

# Spoken edit commands; the transcript must be only the command, so normal dictation never matches.
_COMMAND = re.compile(
    r"^\s*(?:please\s+)?(make (?:it|this|that)|rewrite (?:it|this|that)(?: as| to be| in)?|turn (?:it|this|that) into|"
    r"fix (?:the )?(?:grammar|spelling)|summari[sz]e (?:it|this|that)|"
    r"shorten (?:it|this|that)|make (?:it|this|that) shorter)\b(.*?)[.!?]?\s*$", re.I)


# The system prompt MIRA was fine-tuned with (data/mira_train.jsonl); the model expects it word for word.
MIRA_SYSTEM = (
    "You are MIRA (Multilingual Intelligent Refinement Agent), OpenFlow's ultra-fast offline dictation engine. "
    "Your job is to transform raw spoken audio transcripts into pristine, publication-grade written text. "
    "Fix misheard homophones, add natural punctuation, remove stutters and vocal ticks, and preserve technical "
    "identifiers, code, and Indian terms (Hindi/Odia/English) exactly as intended. When raw speech is in a regional "
    "Odia dialect (Sambalpuri, Ganjami, Kalahandia, Anugulia, Baleswari), normalize and standardize the dialect into "
    "clean Standard Odia while preserving its exact meaning. Reply with ONLY the refined text. Target Style: {style}.")


def edit_command(transcript: str):
    """'Make this more formal.' -> 'Make this more formal'; ordinary dictation -> None."""
    t = transcript.strip()
    if len(t.split()) > 12 or not _COMMAND.match(t):
        return None
    return t.rstrip(".!? ")


class LocalLLM:
    def __init__(self, folder: str, threads: int = 4):
        import ctranslate2
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(folder, "tokenizer.json"))
        self.gen = ctranslate2.Generator(folder, device="cpu", compute_type="int8", intra_threads=threads)

    def chat(self, system: str, user: str, max_tokens: int = 512) -> str:
        prompt = (f"<|im_start|>system\n{system}<|im_end|>\n"
                  f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")
        tokens = self.tok.encode(prompt, add_special_tokens=False).tokens
        res = self.gen.generate_batch([tokens], max_length=max_tokens, sampling_topk=1,
                                      include_prompt_in_result=False, end_token="<|im_end|>")
        return self.tok.decode(res[0].sequences_ids[0]).strip()

    def rewrite(self, text: str, command: str) -> str:
        return self.chat(
            "You edit text for the user. Apply their instruction to the text and reply with only the "
            "edited text: no preamble, no quotes, no explanation. Keep names, numbers and facts unchanged.",
            f"Instruction: {command}\n\nText:\n{text}", max_tokens=min(1024, 64 + 3 * len(text.split())))

    def refine_dictation(self, raw_transcript: str, style: str = "smart_clean") -> str:
        """MIRA speech-to-text refinement pass: cleans raw transcription into publication-grade prose."""
        return self.chat(MIRA_SYSTEM.format(style=style), f"Raw speech: {raw_transcript}",
                         max_tokens=min(1024, 64 + 3 * len(raw_transcript.split())))


# MIRA alias for the intelligent speech refiner
MIRA = LocalLLM


if __name__ == "__main__":
    assert edit_command("Make this more formal.") == "Make this more formal"
    assert edit_command("please rewrite it as a bullet list") == "please rewrite it as a bullet list"
    assert edit_command("fix the grammar") == "fix the grammar"
    assert edit_command("Make sure the report reaches Sarah by Friday and book the room") is None
    assert edit_command("I will send it tomorrow") is None
    print("ok")
