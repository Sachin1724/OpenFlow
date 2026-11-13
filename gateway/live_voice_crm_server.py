"""
live_voice_crm_server.py — Real-Time Voice Ordering CRM Server for MIRA
========================================================================
Integrates:
1. Fast local OrderStateMachine for natural Odia/English food ordering & non-linear diffs.
2. 24,000 Hz Studio Neural Voice Engine (Matcha-Vocos Odia) for crystal-clear voice replies.
3. Real-Time WebSockets broadcasting live cart updates to the Merchant CRM Dashboard.
"""

import os
import sys
import time
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Set, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import soundfile as sf
import uvicorn

# Ensure repository root is on sys.path
_MODULE_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _MODULE_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from gateway.order_state_machine import OrderStateMachine
from engine.studio_voice import StudioVoiceEngine

app = FastAPI(title="MIRA Live Voice Ordering CRM", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TEMPLATES_DIR = _MODULE_DIR / "templates"
SCRATCH_AUDIO_DIR = _REPO_ROOT / "scratch" / "crm_audio"
SCRATCH_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# State
order_fsm = OrderStateMachine()
studio_voice = None

def get_voice_engine() -> StudioVoiceEngine:
    global studio_voice
    if studio_voice is None:
        print("[MIRA Live CRM] Initializing 24kHz Studio Neural Voice Engine...", flush=True)
        studio_voice = StudioVoiceEngine(voice_persona="female")
        print("[MIRA Live CRM] Voice Engine Ready!", flush=True)
    return studio_voice

# WebSocket Connection Manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        dead_conns = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_conns.add(connection)
        for dead in dead_conns:
            self.active_connections.discard(dead)

manager = ConnectionManager()


# Models
class TurnRequest(BaseModel):
    utterance: str
    speaker_persona: Optional[str] = "female"


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    html_file = TEMPLATES_DIR / "crm_dashboard.html"
    if not html_file.exists():
        raise HTTPException(status_code=404, detail="Dashboard template not found")
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.websocket("/ws/crm")
async def websocket_crm_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    # Send initial state
    cart = order_fsm.get_cart_summary()
    await websocket.send_json({
        "type": "state_update",
        "cart": cart,
        "diffs": []
    })
    try:
        while True:
            # Keepalive / ping
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.post("/api/order/turn")
async def process_order_turn(req: TurnRequest):
    utterance = req.utterance.strip()
    if not utterance:
        raise HTTPException(status_code=400, detail="Empty utterance")

    print(f"\n[MIRA CRM] 🗣️ Customer: \"{utterance}\"", flush=True)

    # 1. Process with Non-Linear Order State Machine
    t0 = time.perf_counter()
    res = order_fsm.process_turn(utterance)
    cart = order_fsm.get_cart_summary()
    fsm_time_ms = (time.perf_counter() - t0) * 1000

    reply_odia = res.get("reply_odia", "ଆଜ୍ଞା, ଆପଣଙ୍କ ଅର୍ଡର ନୋଟ୍ କରିନେଲି।")

    # 2. Synthesize 24kHz Studio Speech
    audio_filename = f"mira_reply_{int(time.time() * 1000)}.wav"
    audio_path = SCRATCH_AUDIO_DIR / audio_filename
    audio_url = f"/api/audio/{audio_filename}"

    voice = get_voice_engine()
    t_synth = time.perf_counter()
    wav = voice.synthesize(reply_odia, voice=req.speaker_persona, style="conv")
    sf.write(str(audio_path), wav, voice.sr)
    synth_time_ms = (time.perf_counter() - t_synth) * 1000

    print(f"[MIRA CRM] 🤖 MIRA: \"{reply_odia}\"", flush=True)
    print(f"[MIRA CRM] ⚡ Latency: FSM={fsm_time_ms:.1f}ms | TTS={synth_time_ms:.1f}ms | Total={fsm_time_ms+synth_time_ms:.1f}ms", flush=True)

    # 3. Broadcast to all Dashboard Clients over WebSocket
    turn_time = time.strftime("%I:%M %p")
    
    # Broadcast caller dialogue turn
    await manager.broadcast({
        "type": "new_turn",
        "turn": {
            "role": "customer",
            "text": utterance,
            "time": turn_time
        }
    })

    # Broadcast MIRA dialogue turn with 24kHz audio
    await manager.broadcast({
        "type": "new_turn",
        "turn": {
            "role": "mira",
            "text": reply_odia,
            "time": turn_time,
            "audio_url": audio_url
        },
        "audio_url": audio_url
    })

    # Broadcast updated Cart and Surgical Diffs
    await manager.broadcast({
        "type": "state_update",
        "cart": cart,
        "diffs": res.get("diffs", [])
    })

    return {
        "status": "success",
        "customer_utterance": utterance,
        "mira_reply_odia": reply_odia,
        "mira_reply_en": res.get("reply_en", ""),
        "audio_url": audio_url,
        "cart": cart,
        "diffs": res.get("diffs", []),
        "latency_ms": round(fsm_time_ms + synth_time_ms, 1)
    }


@app.get("/api/audio/{filename}")
async def get_audio_file(filename: str):
    file_path = SCRATCH_AUDIO_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(file_path, media_type="audio/wav")


@app.post("/api/order/kot")
async def dispatch_kot():
    cart = order_fsm.get_cart_summary()
    await manager.broadcast({
        "type": "kot_dispatched",
        "cart": cart,
        "time": time.strftime("%I:%M %p")
    })
    return {"status": "DISPATCHED", "cart": cart}


@app.post("/api/order/reset")
async def reset_order_session():
    order_fsm.reset()
    cart = order_fsm.get_cart_summary()
    await manager.broadcast({
        "type": "state_update",
        "cart": cart,
        "diffs": []
    })
    return {"status": "RESET", "cart": cart}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"\n==================================================================")
    print(f"🚀 MIRA LIVE VOICE ORDERING CRM SERVER LAUNCHING ON http://127.0.0.1:{port}")
    print(f"==================================================================\n")
    uvicorn.run("live_voice_crm_server:app", host="127.0.0.1", port=port, reload=False, app_dir=str(_MODULE_DIR))

