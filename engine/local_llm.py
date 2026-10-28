"""
local_llm.py — small on-device language model for rewriting and meeting notes
=============================================================================
Qwen2.5-1.5B-Instruct (Apache-2.0), int8 CTranslate2 build, run with ctranslate2 and
tokenizers, which faster-whisper already installs. Nothing leaves the machine, no Ollama.
Used only when asked: a spoken "make this formal" on selected text, or meeting notes.
"""

import os
import re

# Spoken edit commands; the transcript must be only the command, so normal dictation never matches.
_COMMAND = re.compile(
    r"^\s*(?:please\s+)?(make (?:it|this|that)|rewrite (?:it|this|that)(?: as| to be| in)?|turn (?:it|this|that) into|"
    r"fix (?:the )?(?:grammar|spelling)|summari[sz]e (?:it|this|that)|"
    r"shorten (?:it|this|that)|make (?:it|this|that) shorter)\b(.*?)[.!?]?\s*$", re.I)


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


if __name__ == "__main__":
    assert edit_command("Make this more formal.") == "Make this more formal"
    assert edit_command("please rewrite it as a bullet list") == "please rewrite it as a bullet list"
    assert edit_command("fix the grammar") == "fix the grammar"
    assert edit_command("Make sure the report reaches Sarah by Friday and book the room") is None
    assert edit_command("I will send it tomorrow") is None
    print("ok")
