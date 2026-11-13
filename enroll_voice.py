"""
enroll_voice.py — Interactive Studio Voice Enrollment & Cloned Speech Console
=============================================================================
Allows users to:
1. Enroll their voice via live microphone recording (10 seconds).
2. Enroll voice from any audio file (.wav, .mp3, .m4a).
3. Synthesize any Odia/English paragraph with their cloned voice.
4. Adjust synthesis parameters:
   - Temperature (0.1 = Calm/Consistent, 0.67 = Natural Realism, 1.0 = Highly Expressive)
   - Speed (0.8x to 1.3x)
   - Expressiveness / Style Guidance
5. Instantly audition and compare cloned voices through speakers.
"""

import os
import sys
import io
import time
import winsound
from pathlib import Path
from typing import Optional, Dict, Any, List

import numpy as np
import soundfile as sf
import sounddevice as sd

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

_MODULE_DIR = Path(__file__).resolve().parent
if str(_MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(_MODULE_DIR))

from engine.enrollment import VoiceEnrollmentManager, get_enrollment_manager
from engine.cloned_voice import ClonedVoiceEngine, get_cloned_voice_engine
from engine.studio_voice import get_studio_voice

_CHATTERBOX_ENGINE = None


def _get_chatterbox():
    """Lazy-loads ChatterboxTTS (real zero-shot cloning) on first enrolled-speaker synthesis."""
    global _CHATTERBOX_ENGINE
    if _CHATTERBOX_ENGINE is None:
        from alm.chatterbox_engine import ChatterboxEngine
        print("\n[Loading Chatterbox voice cloning engine, first run may take a minute...]")
        _CHATTERBOX_ENGINE = ChatterboxEngine()
    return _CHATTERBOX_ENGINE

SCRATCH_DIR = _MODULE_DIR / "scratch"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_CLONED_OUT = SCRATCH_DIR / "cloned_paragraph_output.wav"

SAMPLE_TEXTS = {
    "1": {
        "title": "Everyday Assistant Conversation",
        "text": "ନମସ୍କାର ! ମୁଁ ମୀରା । ଆପଣ କେମିତି ଅଛନ୍ତି ? ଆଜି ଆପଣଙ୍କ ଦିନ କିପରି କଟିଲା ? ମୁଁ ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି ?"
    },
    "2": {
        "title": "Restaurant Host & Ordering Dialogue",
        "text": "ନମସ୍କାର ଆଜ୍ଞା ! ରୟାଲ ରେଷ୍ଟୁରାଣ୍ଟକୁ ଆପଣଙ୍କୁ ସ୍ୱାଗତ । ଆଜି ଆପଣଙ୍କ ପାଇଁ କ'ଣ ଅର୍ଡର କରିବି ? ଆମ ପାଖରେ ମଟନ କସା ଏବଂ ଗରମ ନାନ୍ ବହୁତ ସ୍ୱାଦିଷ୍ଟ ହୋଇଛି ।"
    },
    "3": {
        "title": "Odisha Cultural & Festival Narration",
        "text": "ଓଡ଼ିଶାର ସଂସ୍କୃତି ଏବଂ ପରମ୍ପରା ଅତ୍ୟନ୍ତ ମହାନ । ରଥଯାତ୍ରା ଏବଂ ରଜ ପର୍ବ ସମଗ୍ର ବିଶ୍ୱରେ ପ୍ରସିଦ୍ଧ । ଏହା ଭାଇଚାରା ଏବଂ ପ୍ରେମର ପ୍ରତୀକ ଅଟେ ।"
    }
}


def print_banner():
    print("\n" + "=" * 80)
    print("      🎙️  MIRA STUDIO: ZERO-SHOT ODIA VOICE ENROLLMENT & CLONING CONSOLE      ")
    print("=" * 80)
    print("  Engine: 24kHz HD MultiCondMatcha + Vocos Vocoder + ERes2Net Fingerprinting")
    print("  Hardware: Offline Local Execution (RTX 4050 GPU / CPU Fallback)")
    print("-" * 80)


def list_available_voices(mgr: VoiceEnrollmentManager) -> List[Dict[str, Any]]:
    voices = [
        {"id": "builtin_female", "name": "MIRA Studio Voice (Female / Smita)", "gender": "female", "source": "Built-in"},
        {"id": "builtin_male", "name": "MIRA Studio Voice (Male / Kishore)", "gender": "male", "source": "Built-in"}
    ]
    # Check if female reference exists
    ref_f = _MODULE_DIR / "models" / "female_voice_reference.wav"
    if ref_f.exists():
        voices.append({"id": "ref_female", "name": "Smita Anchor Reference (Studio 24kHz)", "gender": "female", "source": "Reference"})

    for s in mgr.list_enrolled_speakers():
        voices.append({
            "id": s["speaker_id"],
            "name": f"{s['name']} (Enrolled)",
            "gender": s["gender"],
            "source": "Enrolled User"
        })
    return voices


def show_voices(voices: List[Dict[str, Any]]):
    print("\nAvailable Voice Personas:")
    for idx, v in enumerate(voices, 1):
        print(f"  [{idx}] {v['name']}  [{v['gender'].upper()}] ({v['source']})")
    print("-" * 80)


def enroll_mic_flow(mgr: VoiceEnrollmentManager, cloner: Optional[ClonedVoiceEngine] = None):
    print("\n--- [1] ENROLL VOICE VIA MICROPHONE (10-SECOND RECORDING) ---")
    name = input("Enter speaker display name (e.g., 'Sachin' or 'Smita'): ").strip()
    if not name:
        name = "User Voice"

    gender_in = input("Select gender (f = female, m = male, Enter = auto-detect): ").strip().lower()
    gender = "female" if gender_in == "f" else ("male" if gender_in == "m" else "auto")

    print("\nRecommended Reading Calibration Prompts (read naturally in Odia or English):")
    print("  [Odia]:    'ନମସ୍କାର, ମୁଁ ମୋର ସ୍ୱର ରେକର୍ଡ କରୁଛି । ଆଜିର ପାଗ ବହୁତ ସୁନ୍ଦର ଅଟେ । ମୁଁ ଓଡ଼ିଆ ଭାଷାରେ କଥାବାର୍ତ୍ତା କରିବାକୁ ପସନ୍ଦ କରେ ।'")
    print("  [English]: 'Hello! I am recording my voice sample. The weather is beautiful today, and I am excited to clone my voice.'")
    print("-" * 80)
    input("Press Enter when ready to start 10-second recording...")

    for i in range(3, 0, -1):
        print(f"Recording starts in {i}...", end="\r", flush=True)
        time.sleep(1.0)
    print("\n🔴 RECORDING NOW... Please speak clearly into your microphone!")

    target_sr = 24000
    duration = 10.0
    audio_data = None
    actual_sr = target_sr

    # Try native 24000Hz first, with 48000Hz fallback if driver requires it
    for try_sr in [24000, 48000, 16000]:
        try:
            raw_rec = sd.rec(int(duration * try_sr), samplerate=try_sr, channels=1, dtype='float32')
            actual_sr = try_sr
            break
        except Exception:
            continue
    else:
        print("\n[ERROR] Unable to open audio recording stream on default microphone.")
        return

    # Visualizer loop with level meter
    start_t = time.time()
    while time.time() - start_t < duration:
        elapsed = time.time() - start_t
        rem = max(0.0, duration - elapsed)
        # Compute recent energy for VU meter
        cur_idx = min(int(elapsed * actual_sr), len(raw_rec))
        recent_chunk = raw_rec[max(0, cur_idx - int(0.15 * actual_sr)):cur_idx]
        cur_rms = float(np.sqrt(np.mean(recent_chunk**2))) if len(recent_chunk) > 0 else 0.0
        bars = int(min(20, cur_rms * 120))
        vu_meter = "█" * bars + "░" * (20 - bars)
        print(f"  [{vu_meter}] {cur_rms:.3f} RMS | {rem:.1f}s remaining ", end="\r", flush=True)
        time.sleep(0.1)

    sd.wait()
    print("\n✅ Recording finished! Processing acoustic features...")

    audio = raw_rec.flatten()
    if actual_sr != target_sr:
        import scipy.signal
        target_len = int(len(audio) * (target_sr / actual_sr))
        audio = scipy.signal.resample(audio, target_len).astype(np.float32)

    try:
        profile = mgr.enroll_speaker(
            name=name,
            audio_input=audio,
            sr=target_sr,
            gender=gender
        )
        print("\n🎉 VOICE SUCCESSFULLY ENROLLED!")
        print(f"  Speaker ID:      {profile['speaker_id']}")
        print(f"  Name:            {profile['name']}")
        print(f"  Detected Gender: {profile['gender'].upper()}")
        print(f"  Median Pitch F0: {profile['f0_median']} Hz")
        print(f"  SNR:             {profile['snr_db']} dB")
        print(f"  Sample Saved:    {profile['sample_path']}")

        if cloner:
            test_now = input("\nWould you like to test speak with your cloned voice now? [Y/n]: ").strip().lower()
            if test_now != "n":
                synthesize_flow(cloner, mgr, default_speaker_id=profile["speaker_id"])
    except Exception as e:
        print(f"\n[ERROR] Enrollment quality validation failed: {e}")


def enroll_file_flow(mgr: VoiceEnrollmentManager):
    print("\n--- [2] ENROLL VOICE FROM AUDIO FILE ---")
    path_str = input("Enter path to audio file (.wav / .mp3 / .m4a): ").strip().strip('"').strip("'")
    if not path_str or not Path(path_str).exists():
        print(f"[ERROR] File does not exist: {path_str}")
        return

    name = input("Enter speaker display name: ").strip()
    if not name:
        name = Path(path_str).stem

    gender_in = input("Select gender (f = female, m = male, Enter = auto-detect): ").strip().lower()
    gender = "female" if gender_in == "f" else ("male" if gender_in == "m" else "auto")

    try:
        profile = mgr.enroll_speaker(
            name=name,
            audio_input=path_str,
            gender=gender
        )
        print("\n🎉 VOICE SUCCESSFULLY ENROLLED FROM FILE!")
        print(f"  Speaker ID:      {profile['speaker_id']}")
        print(f"  Name:            {profile['name']}")
        print(f"  Detected Gender: {profile['gender'].upper()}")
        print(f"  Duration:        {profile['duration_s']}s")
        print(f"  Median Pitch F0: {profile['f0_median']} Hz")
        print(f"  SNR:             {profile['snr_db']} dB")
    except Exception as e:
        print(f"\n[ERROR] Failed to enroll audio file: {e}")


def synthesize_flow(cloner: ClonedVoiceEngine, mgr: VoiceEnrollmentManager, default_speaker_id: Optional[str] = None):
    voices = list_available_voices(mgr)
    
    if default_speaker_id:
        # Auto-match preselected voice
        selected = None
        for v in voices:
            if v["id"] == default_speaker_id:
                selected = v
                break
        if not selected:
            selected = voices[-1]
    else:
        show_voices(voices)
        choice = input(f"Select voice persona [1-{len(voices)}]: ").strip()
        try:
            v_idx = int(choice) - 1
            selected = voices[v_idx]
        except Exception:
            print("Invalid selection. Using MIRA Female default.")
            selected = voices[0]

    print(f"\nActive Persona: {selected['name']} [{selected['gender'].upper()}]")
    print("\nChoose Text Source:")
    print("  [1] Everyday Assistant Prompt")
    print("  [2] Restaurant Host Dialogue")
    print("  [3] Cultural / Festival Narration")
    print("  [C] Enter Custom Paragraph")
    t_choice = input("Select [1/2/3/C, default C]: ").strip().upper()
    if not t_choice:
        t_choice = "C"

    if t_choice in SAMPLE_TEXTS:
        text = SAMPLE_TEXTS[t_choice]["text"]
    else:
        text = input("\nEnter Odia or transliterated paragraph to synthesize:\n> ").strip()
        if not text:
            text = SAMPLE_TEXTS["1"]["text"]

    print("\nParameter Tuning:")
    print("  Temperature Controls ODE Stochasticity:")
    print("    • 0.1 - 0.3: Calm, consistent, deterministic cadence")
    print("    • 0.67:      Natural conversational realism (Recommended)")
    print("    • 1.0 - 1.2: Highly expressive with dynamic pitch excursions")
    temp_in = input("  Enter Temperature [0.1 - 1.2, default 0.67]: ").strip()
    try:
        temperature = float(temp_in) if temp_in else 0.667
    except ValueError:
        temperature = 0.667

    speed_in = input("  Enter Speed [0.8x - 1.3x, default 1.0x]: ").strip()
    try:
        speed = float(speed_in) if speed_in else 1.0
    except ValueError:
        speed = 1.0

    print(f"\n⚡ Synthesizing with Temperature={temperature:.2f}, Speed={speed:.2f}x...")
    t0 = time.perf_counter()

    # Route synthesis
    if selected["id"] == "builtin_female":
        wav = cloner.studio.synthesize(text, voice="female", speed=speed, temperature=temperature)
        meta = {"speaker_name": selected["name"], "duration_s": len(wav)/24000}
    elif selected["id"] == "builtin_male":
        wav = cloner.studio.synthesize(text, voice="male", speed=speed, temperature=temperature)
        meta = {"speaker_name": selected["name"], "duration_s": len(wav)/24000}
    elif selected["id"] == "ref_female":
        ref_path = _MODULE_DIR / "models" / "female_voice_reference.wav"
        wav, meta = cloner.synthesize(text, reference_audio=ref_path, temperature=temperature, speed=speed)
    else:
        # Enrolled custom speaker: real zero-shot cloning via Chatterbox audio-prompt
        # conditioning (measured cos_sim=0.80 to real voice vs 0.005 for the old latent hack).
        spk_meta = mgr.get_speaker(selected["id"])
        if not spk_meta:
            raise ValueError(f"Speaker '{selected['id']}' not found in enrolled speakers registry.")
        chatterbox = _get_chatterbox()
        wav, out_sr, rtf_cb = chatterbox.synthesize(
            text,
            audio_prompt_path=spk_meta["sample_path"],
            temperature=max(0.05, min(1.5, temperature)),
        )
        meta = {"speaker_name": selected["name"], "duration_s": len(wav) / out_sr}

    latency = time.perf_counter() - t0
    dur = len(wav) / 24000.0
    rtf = latency / max(dur, 1e-4)

    cloner.save_wav(wav, DEFAULT_CLONED_OUT)
    print("\n✨ SYNTHESIS COMPLETED!")
    print(f"  Duration:         {dur:.2f}s")
    print(f"  Compute Time:     {latency:.3f}s ({1.0/rtf:.1f}x real-time)")
    print(f"  Output Saved:     {DEFAULT_CLONED_OUT}")

    # Playback
    play_in = input("\nPlay audio now through speakers? [Y/n]: ").strip().lower()
    if play_in != "n":
        print("🔊 Playing audio... (Press Ctrl+C to stop)")
        try:
            winsound.PlaySound(str(DEFAULT_CLONED_OUT), winsound.SND_FILENAME)
        except KeyboardInterrupt:
            winsound.PlaySound(None, winsound.SND_PURGE)
            print("\nPlayback stopped.")
        except Exception as e:
            print(f"Playback error: {e}")


def audition_enrolled_voices(mgr: VoiceEnrollmentManager):
    speakers = mgr.list_enrolled_speakers()
    if not speakers:
        print("\nNo custom enrolled voices found yet. Enroll one via Option [1] or [2]!")
        return

    print("\nEnrolled Speaker Samples:")
    for idx, s in enumerate(speakers, 1):
        print(f"  [{idx}] {s['name']} ({s['gender']}) - {s['sample_path']}")

    c = input(f"Select sample to audition [1-{len(speakers)}]: ").strip()
    try:
        s = speakers[int(c) - 1]
        p = Path(s["sample_path"])
        if p.exists():
            print(f"🔊 Playing {s['name']} reference sample...")
            winsound.PlaySound(str(p), winsound.SND_FILENAME)
        else:
            print(f"Audio file not found: {p}")
    except Exception as e:
        print(f"Invalid selection: {e}")


def main():
    mgr = get_enrollment_manager()
    cloner = get_cloned_voice_engine()

    while True:
        print_banner()
        voices = list_available_voices(mgr)
        print(f"Active Voice Registry: {len(voices)} voices available.")
        print("\nOperations:")
        print("  [1] 🎙️  Enroll New Voice via Microphone (10s live recording)")
        print("  [2] 📁  Enroll New Voice from Audio File (.wav / .mp3)")
        print("  [3] ✍️  Synthesize Paragraph with Cloned Voice (Adjust Temperature & Speed)")
        print("  [4] 🔊  Audition Enrolled Voice Reference Samples")
        print("  [5] 🗑️  Delete an Enrolled Voice")
        print("  [Q] 🚪  Quit")
        print("-" * 80)

        choice = input("Select an option [1-5 or Q]: ").strip().upper()
        if choice == "1":
            enroll_mic_flow(mgr, cloner)
        elif choice == "2":
            enroll_file_flow(mgr)
        elif choice == "3":
            synthesize_flow(cloner, mgr)
        elif choice == "4":
            audition_enrolled_voices(mgr)
        elif choice == "5":
            speakers = mgr.list_enrolled_speakers()
            if not speakers:
                print("\nNo custom voices to delete.")
            else:
                for idx, s in enumerate(speakers, 1):
                    print(f"  [{idx}] {s['name']} ({s['speaker_id']})")
                d_choice = input(f"Select speaker to delete [1-{len(speakers)}]: ").strip()
                try:
                    s_del = speakers[int(d_choice) - 1]
                    mgr.delete_speaker(s_del["speaker_id"])
                    print(f"✅ Deleted speaker: {s_del['name']}")
                except Exception as e:
                    print(f"Delete failed: {e}")
        elif choice == "Q":
            print("\nExiting MIRA Voice Studio. Goodbye!")
            break
        else:
            print("Invalid choice, please select 1-5 or Q.")
        input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()

