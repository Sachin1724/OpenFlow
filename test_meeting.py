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
    assert "[00:05] Person 1:" in notes


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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
