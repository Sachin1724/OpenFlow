"""
live_voice_conversation.py — Real-Time Live Voice-to-Voice Conversation with MIRA
===================================================================================
1. Listens to user microphone input in real-time (16kHz mono).
2. Transcribes spoken Odia via SOTA IndicConformer CTC ASR.
3. Formulates human-like Odia responses via trained LoRA model on RTX 4050 GPU.
4. Normalizes spelling & emotion via MIRA Sub-ms Dialect Normalizer.
5. Speaks the response out loud in native Odia voice via MMS-TTS.
6. Learns user conversation tempo and habits via on-device Reinforcement Learning.
"""

import os
import sys
import io
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
import torch
from pathlib import Path
from transformers import AutoModelForCausalLM, AutoTokenizer, VitsModel, VitsTokenizer
from peft import PeftModel
from huggingface_hub import snapshot_download

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

# Ensure openflow modules can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.indic_asr import IndicCTC
from engine.dialect_normalizer import get_dialect_normalizer
from engine.conversational_rl import get_conversational_rl_agent

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_LM = r"C:\Users\sachi\.cache\huggingface\hub\models--HuggingFaceTB--SmolLM2-135M-Instruct\snapshots\12fd25f77366fa6b3b4b768ec3050bf629380bac"
LORA_PATH = str(SCRIPT_DIR / "models" / "mira_conversational_gpu")
TTS_MODEL_ID = "facebook/mms-tts-ory"
SYSTEM_PROMPT = "You are MIRA, a natural Odia voice assistant. Respond naturally in authentic colloquial Odia with warm emotions, active listening, and proper discourse markers."

class MiraLiveVoiceSession:
    def __init__(self):
        print("=" * 80)
        print("🎙️ INITIALIZING MIRA LIVE VOICE-TO-VOICE SYSTEM")
        print("=" * 80)

        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"
        print(f"⚡ Compute Engine : {self.device} (NVIDIA RTX 4050 GPU Acceleration)")

        # 1. IndicConformer ASR
        print("[1/4] Loading IndicConformer Odia ASR...")
        snap = snapshot_download("sachinmallick/openflow-odia-asr-int8")
        self.asr = IndicCTC(os.path.join(snap, "or"), threads=4)

        # 2. Conversational LLM + LoRA
        print("[2/4] Loading MIRA Conversational Model on GPU...")
        self.tokenizer = AutoTokenizer.from_pretrained(BASE_LM)
        base_lm = AutoModelForCausalLM.from_pretrained(
            BASE_LM,
            torch_dtype=torch.float16,
            device_map={"": self.device}
        )
        self.llm = PeftModel.from_pretrained(base_lm, LORA_PATH)
        self.llm.eval()

        # 3. MIRA Sub-ms Normalizer & RL Agent
        print("[3/4] Initializing MIRA Normalizer & Adaptive RL Policy...")
        self.normalizer = get_dialect_normalizer()
        self.rl = get_conversational_rl_agent()

        # 4. MMS Odia TTS
        print("[4/4] Loading Native Odia TTS Voice Engine...")
        self.tts_tokenizer = VitsTokenizer.from_pretrained(TTS_MODEL_ID)
        self.tts_model = VitsModel.from_pretrained(TTS_MODEL_ID)
        self.tts_sr = self.tts_model.config.sampling_rate

        print("\n✨ ALL ENGINES ONLINE! MIRA IS READY TO TALK!")
        print("=" * 80)

    def speak(self, text: str):
        """Synthesize and play audio response out loud."""
        if not text.strip():
            return
        inputs = self.tts_tokenizer(text, return_tensors="pt")
        with torch.no_grad():
            output = self.tts_model(**inputs).waveform
        audio_arr = output[0].cpu().numpy()
        sd.play(audio_arr, self.tts_sr)
        sd.wait()

    def generate_reply(self, user_text: str) -> str:
        """Formulate a clean, authentic Odia response."""
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text}
        ]
        prompt = self.tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)

        with torch.no_grad():
            outputs = self.llm.generate(
                **inputs,
                max_new_tokens=160,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id,
                eos_token_id=self.tokenizer.eos_token_id
            )

        gen_tokens = outputs[0][inputs["input_ids"].shape[1]:]
        raw = self.tokenizer.decode(gen_tokens, skip_special_tokens=True).strip()

        # Sentence/clause boundary clean
        for punct in ["।", "!", "?"]:
            if punct in raw:
                idx = raw.find(punct)
                raw = raw[:idx + 1].strip()
                break
        if "," in raw and len(raw.split(",")) > 1:
            clause = raw.split(",")[0].strip()
            if len(clause.split()) >= 3:
                raw = clause + " !"

        # MIRA Normalizer clean
        clean = self.normalizer.normalize(raw)["normalized"]
        return clean

    def record_microphone(self, max_duration=10.0, sr=16000) -> np.ndarray:
        """Records from microphone with Push-to-Talk or Enter-to-stop."""
        print("\n🔴 [RECORDING...] Speak in Odia into your microphone! (Press Enter when done speaking):", end="", flush=True)
        recording = []
        stop_flag = False

        def callback(indata, frames, time_info, status):
            if not stop_flag:
                recording.append(indata.copy())

        stream = sd.InputStream(samplerate=sr, channels=1, dtype="float32", callback=callback)
        with stream:
            try:
                input() # Wait for user to press Enter
                stop_flag = True
            except (KeyboardInterrupt, EOFError):
                stop_flag = True

        if not recording:
            return np.zeros(0, dtype=np.float32)

        audio = np.concatenate(recording, axis=0).flatten()
        print(f" ⏹️ Stopped ({len(audio)/sr:.1f}s recorded)")
        return audio

    def run_interactive_loop(self):
        print("\n💬 LIVE CONVERSATION STARTED!")
        print("Instructions:")
        print(" • Press [ENTER] to start speaking in Odia.")
        print(" • Speak your sentence (e.g., 'ନମସ୍କାର, ଆପଣ କେମିତି ଅଛନ୍ତି ?').")
        print(" • Press [ENTER] again to send your voice.")
        print(" • MIRA will instantly listen, understand, and speak back out loud!")
        print(" • Type 'exit' or press Ctrl+C to quit.\n")

        # Initial Welcome Greeting
        welcome_odia = "ନମସ୍କାର ! ମୁଁ ମୀରା, ଆପଣଙ୍କ ଓଡ଼ିଆ ଭଏସ ଆସିଷ୍ଟାଣ୍ଟ । କୁହନ୍ତୁ, ମୁଁ ଆପଣଙ୍କୁ କିପରି ସାହାଯ୍ୟ କରିପାରିବି ?"
        print(f"🤖 MIRA: {welcome_odia}")
        print("🔊 (Speaking welcome message...)")
        self.speak(welcome_odia)

        turn = 0
        while True:
            turn += 1
            print(f"\n--- [Conversation Turn {turn}] ---")
            print("Press [ENTER] to speak into mic, or type your query (or 'q' to quit): ", end="", flush=True)
            choice = input().strip()
            if choice.lower() in ['q', 'quit', 'exit']:
                print("👋 ଧନ୍ୟବାଦ ! ପୁଣି ଦେଖାହେବ । (Session Ended)")
                break

            if choice:
                # Text mode
                user_clean = self.normalizer.normalize(choice)["normalized"]
                print(f"✍️ YOU ENTERED  : {user_clean}")
                audio_dur = 2.0
            else:
                # 1. Voice Record Mode
                audio = self.record_microphone()
                if len(audio) < 8000:  # under 0.5s
                    print("⚠️ Speech too short or silent. Please try speaking again.")
                    continue

                # 2. ASR Transcription
                t0 = time.perf_counter()
                user_transcript = self.asr.text(audio, beam=True)
                t_asr = (time.perf_counter() - t0) * 1000

                if not user_transcript.strip():
                    print("⚠️ Could not hear clearly. Please speak closer to the mic.")
                    continue

                user_clean = self.normalizer.normalize(user_transcript)["normalized"]
                print(f"🗣️ YOU SPOKE    : {user_clean} (ASR: {t_asr:.1f}ms)")
                audio_dur = len(audio) / 16000

            # 3. MIRA LLM Response
            t1 = time.perf_counter()
            reply = self.generate_reply(user_clean)
            t_llm = (time.perf_counter() - t1) * 1000
            print(f"🤖 MIRA REPLIED : {reply} (LLM: {t_llm:.1f}ms)")

            # 4. RL Adaptation
            self.rl.record_turn_outcome(
                user_utterance=user_clean,
                speech_duration_sec=audio_dur,
                was_incomplete_pause=False,
                user_interrupted_ai=False,
                smooth_turnaround=True
            )

            # 5. Live Speech Output
            print(f"🔊 MIRA IS SPEAKING...")
            self.speak(reply)


if __name__ == "__main__":
    session = MiraLiveVoiceSession()
    session.run_interactive_loop()
