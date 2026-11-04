# Adapters

Every adapter does the same three things:
1. Get text + a dialect hint from the channel
2. Call `DialectEngine.handle(text, dialect)`
3. Send `result.response_dialect` back out on that channel

None of them should contain intent logic, prompts, or dialect
handling — that all lives in `core/engine.py`. If you find yourself
writing dialect-specific code in an adapter, stop — it belongs in
the core.

## Planned adapters

- `cli_adapter.py` — done. Local testing.
- `whatsapp_adapter.py` — Twilio/WhatsApp Business webhook. Receives
  incoming message, dialect hint can come from a stored per-user
  preference (ask once, remember) or a lightweight text-based
  language-ID heuristic before falling back to Standard Odia.
- `web_adapter.py` — simple REST endpoint (Flask/FastAPI) wrapping
  `DialectEngine.handle`, so a website/chat widget can hit it.
- `voice_adapter.py` (phase 2) — wraps the core with:
  - ASR in (Whisper / IndicWav2Vec) -> produces `text` + dialect
    guess from the audio's dialect classifier
  - `DialectEngine.handle(text, dialect)` — UNCHANGED, same core
  - TTS out (VANI, once trained) on `result.response_dialect`

The whole point of this structure: voice is just a new adapter,
not a rewrite. The core (normalize -> understand -> respond ->
stylize) never changes when you add a channel.
