"""Self-check for meeting mode: python test_meeting.py (run from the repo's parent: python -m openflow.test_meeting)."""
import time

import numpy as np

from openflow.engine import meeting as m


def test_app_detection():
    assert m.app_for("chrome.exe", ["Meet - Weekly Sprint Sync - Google Chrome"]) == "Google Meet"
    assert m.app_for("chrome.exe", ["YouTube - Google Chrome"]) is None
    assert m.app_for("ms-teams.exe", []) == "Microsoft Teams"
    assert m.app_for("Zoom.exe", []) == "Zoom"
    assert m.app_for("notepad.exe", []) is None
    assert m._is_self("openflow.exe") and not m._is_self("zoom.exe")


def test_mic_watch_fires():
    """Opening our own mic stream rewrites the consent key, which must wake the watcher fast."""
    import threading
    import sounddevice as sd
    fired = threading.Event()
    m.watch_mic(fired.set)
    time.sleep(0.3)
    t0 = time.monotonic()
    with sd.InputStream(samplerate=m.SR, channels=1):
        assert fired.wait(3), "mic watcher never fired"
    print(f"mic watch latency: {(time.monotonic() - t0) * 1000:.0f} ms")


def test_segmenter_cuts_at_pause():
    out = []
    seg = m._Segmenter(0.01, lambda a, t: out.append(a))
    loud, quiet = np.full(1600, 0.1, np.float32), np.zeros(1600, np.float32)
    for _ in range(10):
        seg.feed(loud)       # 1 s of speech
    for _ in range(8):
        seg.feed(quiet)      # 0.8 s pause ends the utterance
    assert len(out) == 1 and len(out[0]) >= 16000
    seg.feed(loud)           # a 0.1 s blip is too short to count
    seg.flush()
    assert len(out) == 1


def test_notes_without_llm():
    m._ollama = lambda prompt: None
    notes = m.format_meeting_notes(m.transcript_text([
        (0, "You", "Good morning everyone. Today we are reviewing the Q4 roadmap."),
        (5, "Person 1", "We decided to launch OpenFlow 1.0 next Tuesday."),
        (9, "Person 2", "Action item: review the PR by tomorrow afternoon."),
    ]), app_name="Google Meet")
    for h in ("## Meeting Summary", "## Key Decisions", "## Action Items", "## Transcript"):
        assert h in notes, h
    assert "- We decided to launch OpenFlow 1.0" in notes
    assert "- [ ] Action item: review the PR" in notes
    assert "### Person 1" in notes and "[00:05]" in notes


def test_live_capture():
    class FakeTranscriber:
        def transcribe(self, audio, language=None):
            return "hello", 0, 0, "en"
    s = m.MeetingSession(FakeTranscriber(), "auto", lambda who, text: None)
    s.start()
    time.sleep(3)
    s.stop()
    assert s._call_stream is not None, "call audio (loopback) did not open"
    print("live meeting app:", m.active_meeting_app())


def test_file_lines_use_file_time():
    import tempfile, soundfile
    loud, quiet = np.full(16000 * 2, 0.1, np.float32), np.zeros(16000 * 3, np.float32)
    path = f"{tempfile.mkdtemp()}/talk.wav"
    soundfile.write(path, np.concatenate([quiet, loud, quiet, loud, quiet]), m.SR)  # speech at 3 s and 8 s

    class FakeTranscriber:
        def transcribe(self, audio, **kw):
            return ("hello",)
    m._Speakers.label = lambda self, audio: "Person 1"  # no speaker model download in tests
    lines = m.MeetingSession(FakeTranscriber(), "or", lambda *a: None, mic=False).transcribe_file(path)
    assert [round(t) for t, _, _ in lines] == [3, 8], lines


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def test_transcript_keeps_utterances_as_separate_paragraphs():
    lines = [(3, "You", "Hi everyone."), (9, "Them", "We decided to ship Friday."), (14, "Them", "Rahul follows up."),
             (22, "Them", "Budget is approved."), (80, "Them", "New topic.")]
    raw = m.transcript_text(lines)
    assert "We decided to ship Friday.\n\nRahul follows up.\n\nBudget is approved." in raw  # not one run-on paragraph
    assert raw.count("###") == 3  # You, Them, then Them again once a minute has passed
    assert "\n\nRahul follows up.\n\n" in m.format_meeting_notes(raw, "Meeting")
