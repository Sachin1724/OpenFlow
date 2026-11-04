"""
live_subtitles.py — Live YouTube / System Audio Subtitle Overlay (Odia / Hindi / English)
========================================================================================
Captures Windows desktop audio via WASAPI Loopback (YouTube, Spotify, browser videos)
even with background music, transcribes it in real-time, and displays live subtitles
either on a sleek floating overlay window or directly in the terminal.

Usage:
  python openflow/live_subtitles.py --lang odia            # Live Odia subtitles (IndicCTC, 26x real-time)
  python openflow/live_subtitles.py --lang odia --translate # Live Odia audio -> English subtitles!
  python openflow/live_subtitles.py --lang en              # Live English subtitles
  python openflow/live_subtitles.py --lang hi              # Live Hindi subtitles
  python openflow/live_subtitles.py --cli                  # Pure terminal streaming mode
"""

import os
import sys
import time
import queue
import argparse
import threading
import numpy as np

# Ensure openflow modules can be imported
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from engine import model_manager

SR = 16000


class LiveAudioCapture:
    """Captures desktop audio using WASAPI Loopback (speakers output)."""

    def __init__(self, callback):
        self.callback = callback
        self._pa = None
        self._stream = None
        self.running = False

    def start(self):
        import pyaudiowpatch as pyaudio
        self._pa = pyaudio.PyAudio()
        dev = self._pa.get_default_wasapi_loopback()
        rate = int(dev["defaultSampleRate"])
        ch = int(dev["maxInputChannels"])

        print(f"[LiveAudio] Capturing from: {dev['name']} ({rate} Hz, {ch} channels)")

        def audio_cb(in_data, frame_count, time_info, status):
            if not self.running:
                return (None, pyaudio.paComplete)
            # Convert raw bytes to float32
            raw = np.frombuffer(in_data, dtype=np.float32)
            if ch > 1:
                # Downmix stereo/multichannel to mono
                raw = raw.reshape(-1, ch).mean(axis=1)
            # Resample to 16 kHz mono if needed
            if rate != SR:
                target_len = int(len(raw) * SR / rate)
                samples = np.interp(
                    np.linspace(0, len(raw) - 1, target_len),
                    np.arange(len(raw)),
                    raw
                ).astype(np.float32)
            else:
                samples = raw.astype(np.float32)

            self.callback(samples)
            return (None, pyaudio.paContinue)

        self.running = True
        self._stream = self._pa.open(
            format=pyaudio.paFloat32,
            channels=ch,
            rate=rate,
            input=True,
            input_device_index=dev["index"],
            frames_per_buffer=int(rate * 0.1),  # 100 ms buffers
            stream_callback=audio_cb
        )

    def stop(self):
        self.running = False
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass


class VoiceSegmenter:
    """Continuous VAD segmenter that cuts audio at natural pauses (~0.4s silence)."""

    def __init__(self, on_utterance, silence_thresh=0.012, max_dur=8.0):
        self.on_utterance = on_utterance
        self.silence_thresh = silence_thresh
        self.max_dur = max_dur
        self._buf = []
        self._lead = np.zeros(0, dtype=np.float32)
        self._speech_dur = 0.0
        self._silence_dur = 0.0

    def feed(self, chunk: np.ndarray):
        dur = len(chunk) / SR
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        is_speech = rms >= self.silence_thresh

        if not self._buf:
            if is_speech:
                self._buf = [self._lead, chunk]
                self._speech_dur = dur
                self._silence_dur = 0.0
            else:
                self._lead = np.concatenate([self._lead, chunk])[-int(SR * 0.25):]
            return

        self._buf.append(chunk)
        if is_speech:
            self._speech_dur += dur
            self._silence_dur = 0.0
        else:
            self._silence_dur += dur

        total_dur = sum(len(b) for b in self._buf) / SR
        # Trigger on 0.45s silence or max duration (8s)
        if (self._silence_dur >= 0.45 and self._speech_dur >= 0.4) or total_dur >= self.max_dur:
            self.flush()

    def flush(self):
        if self._buf and self._speech_dur >= 0.35:
            audio = np.concatenate(self._buf)
            self.on_utterance(audio)
        self._buf = []
        self._lead = np.zeros(0, dtype=np.float32)
        self._speech_dur = 0.0
        self._silence_dur = 0.0


def create_subtitle_overlay(q_subtitles, lang="odia", translate=False):
    """PyQt6 floating semi-transparent live subtitle window."""
    from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QFont, QColor

    app = QApplication.instance() or QApplication(sys.argv)

    window = QWidget()
    window.setWindowFlags(
        Qt.WindowType.WindowStaysOnTopHint |
        Qt.WindowType.FramelessWindowHint |
        Qt.WindowType.Tool
    )
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    screen = app.primaryScreen().geometry()
    w = min(1100, int(screen.width() * 0.75))
    h = 130
    x = (screen.width() - w) // 2
    y = screen.height() - h - 70
    window.setGeometry(x, y, w, h)

    layout = QVBoxLayout(window)
    layout.setContentsMargins(20, 10, 20, 10)

    label = QLabel("OpenFlow Live Subtitles — Ready")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)

    font_family = "Nirmala UI" if lang in ("odia", "hi") else "Segoe UI"
    label.setFont(QFont(font_family, 18, QFont.Weight.Bold))

    # Dark translucent glass styling
    label.setStyleSheet("""
        QLabel {
            color: #FFFFFF;
            background-color: rgba(15, 18, 25, 215);
            border: 1px solid rgba(255, 255, 255, 0.18);
            border-radius: 16px;
            padding: 12px 24px;
        }
    """)
    layout.addWidget(label)
    window.show()

    def check_subtitles():
        try:
            while not q_subtitles.empty():
                text = q_subtitles.get_nowait()
                if text:
                    label.setText(text)
        except Exception:
            pass

    timer = QTimer()
    timer.timeout.connect(check_subtitles)
    timer.start(50)  # 50 ms polling for responsive live text

    app.exec()


def main():
    parser = argparse.ArgumentParser(description="OpenFlow Live YouTube Subtitles")
    parser.add_argument("--lang", choices=["odia", "hi", "en", "auto"], default="odia")
    parser.add_argument("--translate", action="store_true", help="Translate Odia speech into live English subtitles")
    parser.add_argument("--cli", action="store_true", help="Run in terminal without GUI overlay")
    args = parser.parse_args()

    print("=" * 80)
    print("OPENFLOW LIVE SUBTITLES & AUDIO TRANSCRIBER")
    print(f"Target Language: {args.lang.upper()} {'(Translating to English)' if args.translate else ''}")
    print(f"Mode: {'Terminal CLI' if args.cli else 'Floating Desktop Overlay'}")
    print("Play any YouTube video with background music on your PC.")
    print("=" * 80)

    # 1. Initialize ASR engine
    indic_ctc = None
    whisper_model = None
    translator = None

    if args.lang == "odia":
        from engine.indic_asr import IndicCTC
        from engine.odia_mix import to_mixed
        odia_root = model_manager.cached_path("odia")
        indic_ctc = IndicCTC(os.path.join(odia_root, "or"), threads=8)
        print("[Engine] Odia IndicConformer loaded (25x real-time speed).")

        if args.translate:
            from engine.translator import OdiaToEnglish
            tr_dir = os.path.join(model_manager.cached_path("odia-en"), model_manager.TRANSLATOR_DIR)
            translator = OdiaToEnglish(tr_dir, threads=8)
            print("[Engine] Offline Odia->English translator loaded.")
    else:
        import faster_whisper
        model_name = "small"
        m_path = model_manager.cached_path(model_name)
        whisper_model = faster_whisper.WhisperModel(m_path, device="cpu", compute_type="int8", cpu_threads=8)
        print(f"[Engine] Whisper {model_name} loaded.")

    q_audio = queue.Queue()
    q_subtitles = queue.Queue()

    def process_utterance(audio: np.ndarray):
        q_audio.put(audio)

    segmenter = VoiceSegmenter(process_utterance)

    def audio_feed(chunk: np.ndarray):
        segmenter.feed(chunk)

    capture = LiveAudioCapture(audio_feed)

    # Worker thread to process queued speech
    def worker():
        while True:
            audio = q_audio.get()
            if audio is None:
                break
            try:
                t0 = time.time()
                if args.lang == "odia":
                    raw = indic_ctc.text(audio, beam=False)
                    text = to_mixed(raw)
                    if args.translate and text:
                        text = translator.translate(raw)
                else:
                    segs, _ = whisper_model.transcribe(
                        audio,
                        language="hi" if args.lang == "hi" else "en",
                        beam_size=1,
                        vad_filter=True
                    )
                    text = " ".join(s.text.strip() for s in segs)

                lat = time.time() - t0
                if text and len(text.strip()) > 1:
                    ts = time.strftime("%H:%M:%S")
                    print(f"[{ts}] ({lat:.2f}s) {text}")
                    q_subtitles.put(text)
            except Exception as e:
                print(f"[ASR Error] {e}")

    t_worker = threading.Thread(target=worker, daemon=True)
    t_worker.start()

    capture.start()

    try:
        if args.cli:
            print("\n[Live Subtitles Active] Listening to desktop audio... Press Ctrl+C to stop.\n")
            while True:
                time.sleep(0.5)
        else:
            create_subtitle_overlay(q_subtitles, lang=args.lang, translate=args.translate)
    except KeyboardInterrupt:
        print("\nStopping live subtitles...")
    finally:
        capture.stop()
        q_audio.put(None)


if __name__ == "__main__":
    main()
