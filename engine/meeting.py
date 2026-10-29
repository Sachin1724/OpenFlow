"""Meeting mode: spot a call, record your mic plus the call audio, caption it live with
speaker labels, and turn the transcript into notes."""
import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
import psutil  # type: ignore[import]
import sounddevice as sd

SR = 16000

# Exe-name fragment -> meeting app. Matched against processes that hold a mic open right now,
# so Teams sitting in the tray all day doesn't count; only a live call does.
_APPS = [
    ("zoom", "Zoom"),
    ("teams", "Microsoft Teams"),
    ("webex", "Webex"),
    ("ciscocollabhost", "Webex"),
    ("slack", "Slack Huddle"),
    ("discord", "Discord"),
    ("whatsapp", "WhatsApp"),
    ("skype", "Skype"),
    ("telegram", "Telegram"),
    ("gotomeeting", "GoToMeeting"),
    ("bluejeans", "BlueJeans"),
    ("ringcentral", "RingCentral"),
    ("chime", "Amazon Chime"),
    ("lark", "Lark"),
    ("feishu", "Feishu"),
    ("dingtalk", "DingTalk"),
]
_BROWSERS = (
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "arc.exe",
    "vivaldi.exe", "zen.exe", "waterfox.exe", "sidekick.exe"
)
# Browser window title -> meeting app (only the active tab's title is visible).
_WEB = [(re.compile(r"^Meet\b|meet\.google\.com", re.I), "Google Meet"),
        (re.compile(r"\bZoom\b", re.I), "Zoom"),
        (re.compile(r"\bTeams\b", re.I), "Microsoft Teams"),
        (re.compile(r"\bWebex\b", re.I), "Webex")]


def app_for(process: str, titles: List[str]) -> Optional[str]:
    """Which meeting app a mic-using process is. Browsers are judged by their window titles."""
    p = process.lower()
    if p in _BROWSERS:
        for title in titles:
            for pat, name in _WEB:
                if pat.search(title):
                    return name
        return None
    for frag, name in _APPS:
        if frag in p:
            return name
    return None


_MIC_KEY = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"
# Our own process holds the mic for dictation and meeting capture; never mistake it for a call.
_SELF = {"python.exe", "pythonw.exe", "py.exe", "openflow.exe", os.path.basename(sys.executable).lower()}


def _is_self(exe: str) -> bool:
    return exe in _SELF or "openflow" in exe or "antigravity" in exe


def _mic_process_names() -> set:
    """Exe names actively recording from any microphone via Windows CapabilityAccessManager."""
    names = set()
    roots = [_MIC_KEY + r"\NonPackaged", _MIC_KEY]
    import winreg
    for base in roots:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    subkey_name = winreg.EnumKey(key, i)
                    if subkey_name == "NonPackaged":
                        continue
                    try:
                        with winreg.OpenKey(key, subkey_name) as sub:
                            stop, _ = winreg.QueryValueEx(sub, "LastUsedTimeStop")
                            # If stop == 0, the microphone is actively capturing audio right now
                            if stop == 0:
                                exe = subkey_name.replace("#", "\\").split("\\")[-1].lower()
                                names.add(exe)
                    except Exception:
                        pass
        except Exception:
            pass
    return names


def _window_titles(names: set) -> List[str]:
    """Titles of visible top-level windows owned by processes with these exe names."""
    user32 = ctypes.windll.user32
    titles: List[str] = []
    pid_names: dict = {}  # a browser owns dozens of windows; look each pid up once

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value not in pid_names:
                try:
                    pid_names[pid.value] = psutil.Process(pid.value).name().lower()
                except psutil.Error:
                    pid_names[pid.value] = ""
            if pid_names[pid.value] in names:
                buf = ctypes.create_unicode_buffer(512)
                user32.GetWindowTextW(hwnd, buf, 512)
                if buf.value:
                    titles.append(buf.value)
        return True

    user32.EnumWindows(cb, 0)
    return titles


def active_meeting_app() -> Optional[str]:
    """Name of the meeting app holding a microphone right now, else None.

    Only a live mic counts: an open Teams window or a browser tab titled "Zoom" is not a call,
    and treating it as one kept meetings from ever auto-stopping. One registry read when no
    browser is on the mic, plus one window walk when one is."""
    try:
        mic_procs = {p for p in _mic_process_names() if not _is_self(p)}
        browsers = {p for p in mic_procs if p in _BROWSERS}
        titles = _window_titles(browsers) if browsers else []
        for p in mic_procs:
            app = app_for(p, titles)
            if app:
                return app
    except Exception as e:
        print(f"[OpenFlow Meeting] Detection error: {e}")
    return None


def watch_mic(on_change: Callable[[], None]) -> None:
    """Call on_change whenever any app starts or stops using a microphone.

    Windows rewrites the CapabilityAccessManager key at that moment, so a blocking
    RegNotifyChangeKeyValue wakes us within milliseconds with no polling. Returns at once;
    the watch runs on a daemon thread and quietly ends if the key can't be watched."""
    import winreg

    def run():
        notify = ctypes.windll.advapi32.RegNotifyChangeKeyValue
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MIC_KEY)
        except OSError:
            return
        with key:
            while True:
                # watch subtree, REG_NOTIFY_CHANGE_LAST_SET, synchronous (blocks until a write)
                if notify(wintypes.HKEY(key.handle), True, 0x4, None, False) != 0:
                    return
                time.sleep(0.15)  # an app writes Start then Stop values; read once they settle
                on_change()

    threading.Thread(target=run, daemon=True, name="openflow-mic-watch").start()


class _Segmenter:
    """Cuts a continuous audio feed into utterances at pauses, so each caption is a sentence or so."""

    def __init__(self, threshold: float, emit: Callable[[np.ndarray, float], None]):
        self.threshold = threshold
        self.emit = emit
        self._buf: List[np.ndarray] = []
        self._lead = np.zeros(0, dtype=np.float32)  # 0.3 s before speech, so first syllables survive
        self._speech = 0.0
        self._silence = 0.0
        self._t0 = 0.0
        self._voiced: List[Tuple[float, float]] = []  # (time, seconds) of loud chunks, last 30 s
        self.clock = time.time  # a file's position replaces wall time when transcribing from disk

    def voiced_between(self, t0: float, t1: float) -> float:
        return sum(d for t, d in self._voiced if t0 <= t <= t1)

    def feed(self, x: np.ndarray):
        dur = len(x) / SR
        loud = float(np.sqrt(np.mean(x ** 2))) >= self.threshold
        if loud:
            now = self.clock()
            self._voiced = [v for v in self._voiced if v[0] > now - 30] + [(now, dur)]
        if not self._buf:
            if loud:
                self._buf, self._speech, self._silence, self._t0 = [self._lead, x], dur, 0.0, self.clock()
            else:
                self._lead = np.concatenate([self._lead, x])[-int(SR * 0.3):]
            return
        self._buf.append(x)
        if loud:
            self._speech += dur
            self._silence = 0.0
        else:
            self._silence += dur
        total = sum(len(b) for b in self._buf) / SR
        if self._silence >= 0.7 or total >= 15:
            self.flush()

    def flush(self):
        if self._buf and self._speech >= 0.4:
            self.emit(np.concatenate(self._buf), self._t0)
        self._buf, self._lead = [], np.zeros(0, dtype=np.float32)


_SPEAKER_MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
                      "3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx")
_SPEAKER_MODEL = Path.home() / ".openflow" / "models" / "speaker-eres2net.onnx"


class _Speakers:
    """Labels call voices Person 1, Person 2... by comparing voice fingerprints."""

    MATCH = 0.55  # ERes2Net cosine threshold for distinct speaker clusters

    def __init__(self):
        self._extractor = None
        self._centroids: List[np.ndarray] = []
        self._last = "Person 1"
        try:
            import sherpa_onnx
            if not _SPEAKER_MODEL.exists():
                _SPEAKER_MODEL.parent.mkdir(parents=True, exist_ok=True)
                tmp = _SPEAKER_MODEL.with_suffix(".part")
                urllib.request.urlretrieve(_SPEAKER_MODEL_URL, tmp)
                tmp.replace(_SPEAKER_MODEL)
            self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(_SPEAKER_MODEL), num_threads=2))
        except Exception as e:
            print(f"[OpenFlow Meeting] Speaker labels unavailable ({e}); call audio will be one speaker")

    def label(self, audio: np.ndarray) -> str:
        if self._extractor is None or len(audio) < SR:  # under a second is too little to fingerprint
            return self._last
        stream = self._extractor.create_stream()
        stream.accept_waveform(SR, audio)
        stream.input_finished()
        emb = np.array(self._extractor.compute(stream), dtype=np.float32)
        emb /= np.linalg.norm(emb) + 1e-9
        scores = [float(c @ emb) for c in self._centroids]
        if scores and max(scores) >= self.MATCH:
            i = int(np.argmax(scores))
            c = self._centroids[i] + emb
            self._centroids[i] = c / np.linalg.norm(c)
        else:
            self._centroids.append(emb)
            i = len(self._centroids) - 1
        self._last = f"Person {i + 1}"
        return self._last


# Speaker accent themes: Apple-grade palette for clean differentiation
SPEAKER_PALETTE = {
    "You": {"color": "#38bdf8", "border": "#0284c7", "bg": "rgba(56, 189, 248, 0.14)"},
    "Person 1": {"color": "#34d399", "border": "#059669", "bg": "rgba(52, 211, 153, 0.14)"},
    "Person 2": {"color": "#fbbf24", "border": "#d97706", "bg": "rgba(251, 191, 36, 0.14)"},
    "Person 3": {"color": "#c084fc", "border": "#9333ea", "bg": "rgba(192, 132, 252, 0.14)"},
    "Person 4": {"color": "#fb7185", "border": "#e11d48", "bg": "rgba(251, 113, 133, 0.14)"},
    "Person 5": {"color": "#22d3ee", "border": "#0891b2", "bg": "rgba(34, 211, 238, 0.14)"},
}


def speaker_theme(who: str) -> dict:
    """Retrieve consistent color theme for any speaker name."""
    for k, v in SPEAKER_PALETTE.items():
        if k.lower() == who.lower() or (k == "You" and "you" in who.lower()):
            return v
    # Person N extraction
    m = re.search(r"person\s*(\d+)", who, re.I)
    if m:
        idx = int(m.group(1))
        keys = list(SPEAKER_PALETTE.keys())
        key = f"Person {idx}" if f"Person {idx}" in SPEAKER_PALETTE else keys[1 + (idx % 4)]
        return SPEAKER_PALETTE[key]
    # Fallback pseudo-random stable choice based on name hash
    choices = list(SPEAKER_PALETTE.values())
    return choices[abs(hash(who)) % len(choices)]


INDIC_MEETING_PROMPT = (
    "Meeting notes in Indian English, Hinglish, Hindi, and Odia. "
    "Accurately transcribe Hindi and Odia phrases in clean Latin/Roman script or Devanagari. "
    "Common terms: kya, kyu, kaise, kuch, nahi, haan, theek, accha, bhai, yaar, "
    "kete, kan, kemiti, kichi, ghare, aama, bhala, namaskar, dhanyabad. "
    "Never output Urdu or Arabic script."
)


class MeetingSession:
    """Records mic + call audio, transcribes each utterance in the background, reports captions."""

    def __init__(self, transcriber, language: str, on_line: Callable[[str, str], None],
                 mic_device: Optional[int] = None, mic: bool = True):
        self.transcriber = transcriber
        self.mic = mic  # False: only what the speakers play (podcasts, videos)
        self.language = language
        self.on_line = on_line
        self.mic_device = mic_device
        self.lines: List[Tuple[float, str, str]] = []
        self.started = 0.0
        self._q: "queue.Queue" = queue.Queue()
        self._mic = _Segmenter(0.010, self._mic_clip)
        self._call = _Segmenter(0.004, lambda a, t: self._q.put(("call", a, t)))
        self._mic_stream = None
        self._pa = None
        self._call_stream = None
        self._worker = None

    def _mic_clip(self, audio: np.ndarray, t0: float):
        # Without headphones the mic also hears the call. Drop mic clips the call was mostly talking over.
        dur = len(audio) / SR
        if self._call.voiced_between(t0, t0 + dur) > 0.5 * dur:
            return
        self._q.put(("mic", audio, t0))

    def start(self):
        self.started = time.time()
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        if not self.mic:
            self._open_call_audio()  # nothing else to record: let a failure reach the caller
            return
        self._mic_stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", device=self.mic_device,
                                          blocksize=1600, callback=lambda d, *_: self._mic.feed(d[:, 0].copy()))
        self._mic_stream.start()
        try:
            self._open_call_audio()
        except Exception as e:
            print(f"[OpenFlow Meeting] Call audio unavailable ({e}); recording mic only")

    def transcribe_file(self, path: str) -> List[Tuple[float, str, str]]:
        """An audio or video file (podcast, recording): same utterance cuts and speaker labels as a call."""
        from faster_whisper.audio import decode_audio  # PyAV: mp3, m4a, webm, mp4, wav...
        audio = decode_audio(path, sampling_rate=SR)  # ponytail: whole file in memory, ~230 MB an hour
        pos = [0.0]
        self.started, self._call.clock = 0.0, lambda: pos[0]
        self._worker = threading.Thread(target=self._work, daemon=True)
        self._worker.start()
        for i in range(0, len(audio), 1600):
            self._call.feed(audio[i:i + 1600])
            pos[0] += 0.1
        return self.stop()

    def _open_call_audio(self):
        """What the speakers play (WASAPI loopback): everyone else on the call."""
        import pyaudiowpatch as pyaudio
        self._pa = pyaudio.PyAudio()
        dev = self._pa.get_default_wasapi_loopback()
        rate, ch = int(dev["defaultSampleRate"]), int(dev["maxInputChannels"])

        def cb(data, frames, info, status):
            x = np.frombuffer(data, dtype=np.float32).reshape(-1, ch).mean(axis=1)
            n = int(len(x) * SR / rate)
            self._call.feed(np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32))
            return (None, pyaudio.paContinue)

        self._call_stream = self._pa.open(format=pyaudio.paFloat32, channels=ch, rate=rate, input=True,
                                          input_device_index=dev["index"], frames_per_buffer=rate // 10,
                                          stream_callback=cb)

    def _work(self):
        speakers = _Speakers()
        while True:
            item = self._q.get()
            if item is None:
                return
            src, audio, t0 = item
            try:
                # Prime Whisper with anti-Urdu / Indic biasing prompt so Hindi/Odia speech is never misclassified
                text = self.transcriber.transcribe(
                    audio,
                    language=self.language,
                    initial_prompt=INDIC_MEETING_PROMPT
                )[0].strip()
            except Exception as e:
                print(f"[OpenFlow Meeting] Transcription failed: {e}")
                continue
            if not text:
                continue
            who = "You" if src == "mic" else speakers.label(audio)
            self.lines.append((t0 - self.started, who, text))
            try:
                self.on_line(who, text)
            except Exception:
                pass

    def stop(self) -> List[Tuple[float, str, str]]:
        """Stops recording, finishes transcribing what is queued, returns (seconds, speaker, text) lines."""
        for s in (self._mic_stream, self._call_stream):
            try:
                if s is not None:
                    s.stop_stream() if hasattr(s, "stop_stream") else s.stop()
                    s.close()
            except Exception:
                pass
        if self._pa is not None:
            self._pa.terminate()
        self._mic.flush()
        self._call.flush()
        self._q.put(None)
        if self._worker:
            self._worker.join()
        return self.lines


def group_speaker_turns(lines: List[Tuple[float, str, str]]) -> List[dict]:
    """
    Groups consecutive utterances by the same speaker within 30 seconds into clean dialog turns.
    Prevents single-sentence fragmentation and run-together text.
    """
    turns: List[dict] = []
    for t, who, text in lines:
        if not text or not text.strip():
            continue
        cleaned = text.strip()
        # If the same speaker spoke again within 30 seconds, append to the current turn
        if turns and turns[-1]["who"] == who and (t - turns[-1]["t_end"] <= 30.0):
            turns[-1]["t_end"] = t
            turns[-1]["texts"].append(cleaned)
        else:
            turns.append({
                "who": who,
                "t_start": t,
                "t_end": t,
                "texts": [cleaned],
            })
    return turns


def transcript_text(lines: List[Tuple[float, str, str]]) -> str:
    """Format lines into cleanly structured Markdown transcript with separated speaker turns."""
    turns = group_speaker_turns(lines)
    if not turns:
        return "\n\n".join(f"[{int(t) // 60:02d}:{int(t) % 60:02d}] {who}: {text}" for t, who, text in lines)

    blocks: List[str] = []
    for turn in turns:
        s_min, s_sec = int(turn["t_start"]) // 60, int(turn["t_start"]) % 60
        e_min, e_sec = int(turn["t_end"]) // 60, int(turn["t_end"]) % 60
        time_tag = f"[{s_min:02d}:{s_sec:02d}]" if turn["t_start"] == turn["t_end"] else f"[{s_min:02d}:{s_sec:02d} - {e_min:02d}:{e_sec:02d}]"
        speech = " ".join(turn["texts"])
        blocks.append(f"### {turn['who']} · {time_tag}\n\n{speech}")
    return "\n\n".join(blocks)


_DECISION = re.compile(r"\b(decided|decide|agreed|agree|final|approved|going with|we will|we'll)\b", re.I)
_ACTION = re.compile(r"\b(action item|todo|to-do|follow up|need to|needs to|will|by (tomorrow|monday|tuesday|"
                     r"wednesday|thursday|friday|eod|end of day|next week))\b", re.I)


def _ollama(prompt: str) -> Optional[str]:
    """Local LLM through Ollama, if it is running. Nothing leaves the machine."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            models = json.load(r).get("models", [])
        if not models:
            return None
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps({"model": models[0]["name"], "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r).get("response", "").strip() or None
    except Exception:
        return None


def format_meeting_notes(transcript: str, app_name: str = "Meeting", llm=None) -> str:
    """Markdown notes: summary, decisions, action items, then the full transcript with clean separation."""
    prompt = (
        "You are writing meeting notes from a transcript. The transcript may mix languages; write the notes "
        "in English. Use exactly these markdown headings and nothing before them:\n"
        "## Meeting Summary\n(3-5 sentences)\n## Key Decisions\n(bullets, or 'None recorded')\n"
        "## Action Items\n(- [ ] task — owner if named)\n\nTranscript:\n" + transcript
    )
    notes = None
    if llm is not None:  # built-in writing model (engine/local_llm.py)
        try:
            notes = llm.chat("You write concise, accurate meeting notes.", prompt, max_tokens=700)
        except Exception as e:
            print(f"[OpenFlow] Local notes model failed ({e})")
    notes = notes or _ollama(prompt)
    if not notes or "## Action Items" not in notes:
        # Keyword rules when no local LLM; clean offline and instant
        body = re.sub(r"^### [^\n]+\n+", "", transcript, flags=re.M)
        body = re.sub(r"^\[\d+:\d+\] [^:]+: ", "", body, flags=re.M)
        sentences = [s.strip() for s in re.split(r"(?<=[.!?।])\s+|\n+", body) if s.strip()]
        decisions = [s for s in sentences if _DECISION.search(s)]
        actions = [s for s in sentences if _ACTION.search(s) and s not in decisions]
        notes = "\n\n".join([
            "## Meeting Summary\n" + (" ".join(sentences[:3]) or "Nothing was transcribed."),
            "## Key Decisions\n" + ("\n".join(f"- {s}" for s in decisions) or "None recorded"),
            "## Action Items\n" + ("\n".join(f"- [ ] {s}" for s in actions) or "None recorded"),
        ])
    return f"# {app_name} notes\n\n{notes}\n\n## Transcript\n\n{transcript}\n"


def render_meeting_html(markdown_notes: str, app_name: str = "Meeting") -> str:
    """
    Renders structured meeting notes into a rich, beautiful Apple-grade dark UI document.
    Differentiates speakers with high-contrast color badges, avatar tags, and dedicated speech cards.
    """
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Parse sections out of the markdown
    summary_text = ""
    decisions_list: List[str] = []
    actions_list: List[str] = []
    transcript_raw = ""

    lines = markdown_notes.split("\n")
    curr_sec = ""
    transcript_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## Meeting Summary"):
            curr_sec = "summary"
            continue
        elif stripped.startswith("## Key Decisions"):
            curr_sec = "decisions"
            continue
        elif stripped.startswith("## Action Items"):
            curr_sec = "actions"
            continue
        elif stripped.startswith("## Transcript"):
            curr_sec = "transcript"
            continue

        if curr_sec == "summary":
            if stripped and not stripped.startswith("#"):
                summary_text += (" " if summary_text else "") + stripped
        elif curr_sec == "decisions":
            if stripped.startswith("-"):
                decisions_list.append(stripped[1:].strip())
            elif stripped and "None recorded" not in stripped:
                decisions_list.append(stripped)
        elif curr_sec == "actions":
            if stripped.startswith("- [ ]") or stripped.startswith("- []"):
                actions_list.append(stripped[5:].strip())
            elif stripped.startswith("-"):
                actions_list.append(stripped[1:].strip())
            elif stripped and "None recorded" not in stripped:
                actions_list.append(stripped)
        elif curr_sec == "transcript":
            transcript_lines.append(line)

    transcript_raw = "\n".join(transcript_lines).strip()

    # Build HTML blocks
    # 1. Decisions HTML
    if decisions_list:
        decisions_html = "".join(f'<li style="margin-bottom: 6px; color: #e2e8f0;">{esc(d)}</li>' for d in decisions_list)
    else:
        decisions_html = '<div style="color: #64748b; font-style: italic;">None recorded</div>'

    # 2. Actions HTML
    if actions_list:
        actions_html = "".join(
            f'<div style="margin-bottom: 8px; color: #e2e8f0; display: flex; align-items: flex-start;">'
            f'<span style="display:inline-block; width:16px; height:16px; margin-right:8px; margin-top:2px; border: 1.5px solid #38bdf8; border-radius: 4px; background: rgba(56,189,248,0.1);"></span>'
            f'<span>{esc(a)}</span></div>'
            for a in actions_list
        )
    else:
        actions_html = '<div style="color: #64748b; font-style: italic;">None recorded</div>'

    # 3. Transcript Cards with Color-Coded Speaker Badges
    turn_cards_html = []
    # Match both format types: '### Speaker · [Time]' or old '[Time] Speaker:'
    pattern_turn = re.compile(r"###\s+([^·\n]+)\s*·\s*(\[[^\]]+\])")
    pattern_old = re.compile(r"^\[(\d+:\d+)\]\s*([^:]+):\s*(.*)$")

    current_who = "You"
    current_time = ""
    current_speech: List[str] = []

    def flush_turn():
        nonlocal current_speech
        if not current_speech:
            return
        theme = speaker_theme(current_who)
        text_body = esc(" ".join(current_speech))
        turn_cards_html.append(
            f'<div style="margin-bottom: 12px; background: #131720; border-left: 4px solid {theme["color"]}; '
            f'border-radius: 8px; padding: 10px 14px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);">'
            f'  <div style="margin-bottom: 6px; display: flex; align-items: center;">'
            f'    <span style="background: {theme["bg"]}; color: {theme["color"]}; font-weight: 700; '
            f'font-size: 11px; padding: 3px 10px; border-radius: 12px; border: 1px solid {theme["border"]}; '
            f'letter-spacing: 0.3px;">{esc(current_who)}</span>'
            f'    <span style="color: #64748b; font-size: 11px; margin-left: 10px; font-family: monospace;">{esc(current_time)}</span>'
            f'  </div>'
            f'  <div style="color: #f1f5f9; font-size: 13.5px; line-height: 1.6; word-break: break-word;">'
            f'    {text_body}'
            f'  </div>'
            f'</div>'
        )
        current_speech = []

    for line in transcript_raw.split("\n"):
        line_s = line.strip()
        if not line_s:
            continue
        m_turn = pattern_turn.match(line_s)
        if m_turn:
            flush_turn()
            current_who = m_turn.group(1).strip()
            current_time = m_turn.group(2).strip()
            continue
        m_old = pattern_old.match(line_s)
        if m_old:
            flush_turn()
            current_time = f"[{m_old.group(1)}]"
            current_who = m_old.group(2).strip()
            current_speech.append(m_old.group(3).strip())
            continue
        current_speech.append(line_s)

    flush_turn()

    if not turn_cards_html:
        turn_cards_html.append(f'<div style="color: #64748b; font-style: italic;">{esc(transcript_raw) or "No transcript recorded"}</div>')

    full_transcript_rendered = "".join(turn_cards_html)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
          background-color: #0b0e14;
          color: #f8fafc;
          padding: 16px 20px;
          margin: 0;
          line-height: 1.5;
        }}
        h1 {{
          font-size: 22px;
          font-weight: 700;
          color: #ffffff;
          margin-top: 0;
          margin-bottom: 16px;
          display: flex;
          align-items: center;
        }}
        .badge {{
          background: rgba(56, 189, 248, 0.15);
          color: #38bdf8;
          border: 1px solid rgba(56, 189, 248, 0.4);
          font-size: 12px;
          font-weight: 600;
          padding: 3px 10px;
          border-radius: 12px;
          margin-left: 10px;
        }}
        .card {{
          background: #11151f;
          border: 1px solid #1e2638;
          border-radius: 10px;
          padding: 14px 16px;
          margin-bottom: 16px;
        }}
        .card-header {{
          font-size: 13px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.6px;
          color: #94a3b8;
          margin-bottom: 10px;
          display: flex;
          align-items: center;
        }}
        .card-header-icon {{
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: #38bdf8;
          margin-right: 8px;
        }}
        .summary-text {{
          color: #e2e8f0;
          font-size: 13.5px;
          line-height: 1.6;
        }}
      </style>
    </head>
    <body>
      <h1>
        {esc(app_name)} Meeting Notes
        <span class="badge">Wispr Flow Mode</span>
      </h1>

      <div class="card">
        <div class="card-header"><span class="card-header-icon" style="background:#38bdf8;"></span>Executive Summary</div>
        <div class="summary-text">{esc(summary_text) or "No summary available."}</div>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-header-icon" style="background:#10b981;"></span>Key Decisions</div>
        <ul style="margin: 0; padding-left: 20px;">
          {decisions_html}
        </ul>
      </div>

      <div class="card">
        <div class="card-header"><span class="card-header-icon" style="background:#f59e0b;"></span>Action Items</div>
        <div>
          {actions_html}
        </div>
      </div>

      <div style="margin-top: 22px; margin-bottom: 10px; display: flex; align-items: center;">
        <span style="font-size: 15px; font-weight: 700; color: #ffffff;">Diarized Transcript by Speaker</span>
        <span style="font-size: 11px; color: #64748b; margin-left: 12px;">Identified distinct voices</span>
      </div>

      <div>
        {full_transcript_rendered}
      </div>
    </body>
    </html>
    """

