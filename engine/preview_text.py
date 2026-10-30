"""Live preview text: each update decodes only the last few seconds of audio, so successive texts overlap and
slide. Merge them into one steadily growing line instead of replacing it, so already-shown words never re-appear."""
import re


def _norm(word: str) -> str:
    return re.sub(r"\W+", "", word.lower())


def merge_preview(old: str, new: str) -> str:
    """The text so far, extended (or its tail corrected) by the latest window of speech."""
    old_w, new_w = old.split(), new.split()
    if not old_w:
        return new.strip()
    if not new_w:
        return old
    o, n = [_norm(w) for w in old_w], [_norm(w) for w in new_w]
    best_at, best_len = None, 0
    for at in range(max(0, len(o) - 40), len(o)):  # where the new window lines up with the end of the old text
        k = 0
        while at + k < len(o) and k < len(n) and o[at + k] == n[k]:
            k += 1
        reaches_end = at + k == len(o)  # the window repeats everything from `at` to the end
        if k and (reaches_end or k == len(n)) and k >= best_len:
            best_at, best_len = at, k
    if best_at is None:
        # the tail may have been re-decoded differently: realign on the window's first word
        for at in range(max(0, len(o) - 12), len(o)):
            if o[at] and o[at] == n[0]:
                best_at = at
                break
    if best_at is None:
        return " ".join(old_w + new_w)  # no overlap: the window moved on to new words
    return " ".join(old_w[:best_at] + new_w)
