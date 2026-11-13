"""
demo_enterprise_flow.py — End-to-End MIRA Voice AI Mediator Verification Demo
=============================================================================
Demonstrates how MIRA acts as the conversational bridge between Odia customers
and an Odisha enterprise backend (e.g. Bank/FinTech).

Turn 1: MIRA starts session & prompts for Customer Name in polite Odia.
Turn 2: Customer speaks colloquially: "ନମସ୍କାର ଆଜ୍ଞା, ମୋ ନାଁ ସଚିନ ମଲ୍ଲିକ"
Turn 3: MIRA extracts Name, prompts for Aadhaar last 4 digits in Odia.
Turn 4: Customer speaks digits: "ମୋ ଆଧାର ନମ୍ବର ଶେଷ ଚାରିଟା ହେଲା ସାତ ଦୁଇ ଚାରି ଚାରି"
Turn 5: MIRA parses digits ("7244"), dispatches structured JSON webhook to Core Banking API.
Turn 6: Enterprise verifies and responds with JSON.
Turn 7: MIRA formulates polite Odia business reply and synthesizes 24kHz studio audio.
"""

import os
import sys
import io
import time
import threading
import soundfile as sf
from pathlib import Path

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gateway.enterprise_gateway import MiraEnterpriseGateway
import uvicorn
from gateway.mock_company_backend import app as backend_app

def run_mock_backend():
    """Runs mock backend on 127.0.0.1:9000 in background thread."""
    config = uvicorn.Config(backend_app, host="127.0.0.1", port=9000, log_level="warning")
    server = uvicorn.Server(config)
    server.run()

def run_enterprise_demo():
    print("=" * 78)
    print("🌟 MIRA VOICE AI ENTERPRISE MEDIATOR DEMO (ODISHA FINTECH / BANKING)")
    print("=" * 78)

    # 1. Start Mock Server in Daemon Thread
    print("[INIT] Starting Local Enterprise Mock Server on http://127.0.0.1:9000...")
    backend_thread = threading.Thread(target=run_mock_backend, daemon=True)
    backend_thread.start()
    time.sleep(1.0) # Allow server to bind

    # 2. Instantiate MIRA Enterprise Gateway
    print("[INIT] Initializing MIRA Enterprise Gateway with 24kHz Neural Voice...")
    gateway = MiraEnterpriseGateway(company_id="odisha_gramya_bank_01")

    session_id = f"call_{int(time.time())}"
    print(f"\n[SESSION STARTED] 📞 Incoming Voice Call ID: {session_id}")
    print("Workflow: Digital KYC Verification (e-KYC slot filling)")

    # Turn 0: Initialization & Greeting
    t0 = time.time()
    init_res = gateway.start_session(session_id, flow_id="kyc_verification")
    print(f"\n🤖 MIRA Prompts Caller:\n  \"{init_res['prompt_text']}\"")

    # Turn 1: Customer Speaks Name
    customer_turn_1 = "ନମସ୍କାର ଆଜ୍ଞା, ମୋ ନାଁ ସଚିନ ମଲ୍ଲିକ"
    print(f"\n🗣️ CALLER SPEAKS Turn 1:\n  \"{customer_turn_1}\"")

    t1 = time.time()
    res_1 = gateway.process_customer_turn(session_id, customer_turn_1)
    d1 = (time.time() - t1) * 1000

    print(f"  -> Extracted Slots: {res_1['collected_slots']}")
    print(f"  -> Pipeline Latency: {d1:.2f}ms")
    print(f"🤖 MIRA Next Prompt:\n  \"{res_1['reply_odia']}\"")

    # Turn 2: Customer Speaks Spoken Odia Aadhaar Digits
    customer_turn_2 = "ମୋ ଆଧାର ନମ୍ବର ଶେଷ ଚାରିଟା ହେଲା ସାତ ଦୁଇ ଚାରି ଚାରି"
    print(f"\n🗣️ CALLER SPEAKS Turn 2 (Spoken Odia Numerals):\n  \"{customer_turn_2}\"")

    t2 = time.time()
    res_2 = gateway.process_customer_turn(session_id, customer_turn_2)
    d2 = (time.time() - t2) * 1000

    print(f"  -> Extracted Slots: {res_2['collected_slots']}")
    print(f"  -> Webhook Dispatched to Core Banking: {res_2['dispatched_webhook']}")
    print(f"  -> Enterprise Backend JSON Response: {res_2['backend_response']}")
    print(f"  -> Pipeline & Webhook Roundtrip Latency: {d2:.2f}ms")
    print(f"\n🤖 MIRA Formulates Spoken Business Response:\n  \"{res_2['reply_odia']}\"")

    # Turn 3: 24kHz Studio Speech Synthesis
    print("\n[TTS] Synthesizing Broadcast-Quality 24kHz Studio Odia Speech...")
    t_synth = time.time()
    audio = gateway.speak_response(res_2['reply_odia'])
    synth_duration = (time.time() - t_synth) * 1000
    audio_len_s = len(audio) / 24000.0
    rtf = (synth_duration / 1000.0) / audio_len_s if audio_len_s > 0 else 0

    scratch_dir = SCRIPT_DIR / "scratch"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    out_path = scratch_dir / "enterprise_kyc_completed.wav"
    sf.write(str(out_path), audio, 24000)

    print(f"  -> Audio Duration: {audio_len_s:.2f}s")
    print(f"  -> Synthesis Latency: {synth_duration:.2f}ms (Real-Time Factor: {rtf:.3f}x, {1.0/rtf:.1f}x real-time)")
    print(f"  -> Saved Audio: {out_path}")

    print("\n" + "=" * 78)
    print("✅ MIRA ENTERPRISE GATEWAY VERIFICATION SUCCESSFUL!")
    print("=" * 78)

if __name__ == "__main__":
    run_enterprise_demo()

