"""
demo_alm_interactive.py — Interactive Audio Language Model (ALM) Voice Studio
=============================================================================
Interactive console for testing Odia & Hindi conversational speech with prosody tags:
Tags supported: <chuckle>, <laugh>, <breathe>, <sigh>, <pause_short>, <question_rise>, <emphatic>, <warm_whisper>
Speakers: smita, kishore, gulua, sambalpuri, conv_female, conv_male
"""

import sys
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Alias alm module for pickle compatibility
import openflow.alm as _alm_pkg
import openflow.alm.model as _alm_model_pkg
sys.modules['alm'] = _alm_pkg
sys.modules['alm.model'] = _alm_model_pkg

from openflow.alm.inference import MiraALMEngine

PRESET_PROMPTS = [
    ("Smita - Conversational", "smita", "ଆଚ୍ଛା! <chuckle> ତମେ କେମିତି ଅଛ? ମୁଁ ବିଲକୁଲ ଭଲ ଅଛି। <breathe> ଆମର ନୂଆ ଅର୍ଡର ଟା ରେଡି ହେଇଗଲା!"),
    ("Kishore - Podcast Host", "kishore", "ଆରେ ଭାଇ, <laugh> ଏଇଟା ତ ଏକଦମ୍ ଚମତ୍କାର ହେଇଛି! <pause_short> ସତରେ ବହୁତ ଖୁସି ଲାଗିଲା <question_rise>?"),
    ("Gulua - High Energy Comedy", "gulua", "ଏଇ ଦେଖ, <chuckle> ଆମ ଗୁଲୁଆ ଭାଇଙ୍କ ଷ୍ଟାଇଲ୍ ପୁରା ନିଆରା <emphatic>! ହସି ହସି ପେଟ ଫାଟିଯିବ!"),
    ("Sambalpuri - Regional Dialect", "sambalpuri", "ଜୁହାର! <warm_whisper> ସମକୁ ମୋର ସମ୍ବଲପୁରୀ ଜୁହାର। <pause_medium> ଆମର୍ ସମ୍ବଲପୁରୀ ଭାଷା କେତେ ସୁନ୍ଦର!"),
    ("Food Delivery Confirmation", "smita", "ହଁ ଆଜ୍ଞା! <chuckle> ମସାଲା ଦୋସା ଆଉ ରସଗୋଲା ପ୍ୟାକ୍ ହେଇଗଲା। <pause_short> BPUT ହଷ୍ଟେଲରେ deliver ହେବ <question_rise>?")
]

def run_interactive():
    print("=" * 80)
    print("🎙️ MIRA AUDIO LANGUAGE MODEL (ALM) — CONVERSATIONAL VOICE STUDIO")
    print("=" * 80)
    print("Available Speakers: smita, kishore, gulua, sambalpuri, conv_female, conv_male")
    print("Prosody Tags: <chuckle>, <laugh>, <breathe>, <sigh>, <pause_short>, <question_rise>, <emphatic>, <warm_whisper>")
    print("-" * 80)
    
    engine = MiraALMEngine()
    out_dir = REPO_ROOT / "scratch"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print("\nPreset Examples:")
    for idx, (title, spk, text) in enumerate(PRESET_PROMPTS, 1):
        print(f"  [{idx}] {title} ({spk}) -> {text[:60]}...")
    print("  [0] Custom input")
    
    choice = input("\nChoose an option [1-5 or 0, default=1]: ").strip() or "1"
    
    if choice in ["1", "2", "3", "4", "5"]:
        title, speaker, text = PRESET_PROMPTS[int(choice) - 1]
    else:
        speaker = input("Speaker (smita/kishore/gulua/sambalpuri) [default=smita]: ").strip() or "smita"
        text = input("Enter Odia/Hindi text with prosody tags: ").strip()
        if not text:
            text = "ନମସ୍କାର! <chuckle> ମୁଁ ମୀରା। ଆଜି ମୁଁ ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି <question_rise>?"
            
    out_wav = str(out_dir / f"mira_alm_interactive_{speaker}.wav")
    print(f"\n⚡ Synthesizing with speaker '{speaker}'...")
    print(f"📝 Prompt: {text}")
    
    res = engine.synthesize(
        text=text,
        speaker=speaker,
        output_wav=out_wav,
        temperature=0.65,
        top_p=0.85
    )
    
    print("\n" + "=" * 60)
    print("✅ SYNTHESIS COMPLETE!")
    print(f"  Duration:   {res['duration_s']}s (24,000 Hz Broadcast Audio)")
    print(f"  Latency:    {res['latency_ms']}ms")
    print(f"  RTF:        {res['rtf']} (Real-Time Factor)")
    print(f"  Saved to:   {out_wav}")
    print("=" * 60)
    
    # Try playback via Windows winsound if available
    try:
        import winsound
        print("🔊 Playing audio through speakers...")
        winsound.PlaySound(out_wav, winsound.SND_FILENAME)
    except Exception:
        pass

if __name__ == '__main__':
    run_interactive()

