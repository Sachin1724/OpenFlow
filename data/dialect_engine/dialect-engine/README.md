# Universal Dialect Communication Engine — v1 (text-first)

A channel-agnostic core that takes text in a person's Odia dialect,
understands intent, and replies back in that same dialect's phrasing.
Voice (ASR in, VANI TTS out) plugs in later as just another adapter —
the core pipeline doesn't change.

```
core/engine.py        <- the whole brain (normalize -> understand -> respond -> stylize)
adapters/              <- thin per-channel wrappers (CLI now; WhatsApp/web/voice later)
data/dialect_examples.json  <- few-shot pairs extracted from your VANI metadata.csv
```

## Setup

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python3 adapters/cli_adapter.py
```

## What's real vs. what's a placeholder right now

**Real:**
- Few-shot examples pulled from your actual dataset, grouped by dialect
  (151 Standard Odia, 33 Anugulia, 31 Ganjami, 25 Sambalpuri, 11 Baleswari,
  10 Kalahandia pairs after filtering junk placeholder rows)
- Working normalize -> understand -> respond -> stylize pipeline via the
  Anthropic API
- Clean separation so a new channel adapter never touches dialect logic

**Placeholder / needs your decision:**
- `INTENT_TAXONOMY` in `core/engine.py` is a starter guess
  (greeting, weather_query, crop_price_query, government_scheme_query,
  complaint, small_talk, unknown). Replace with your real target
  domain's intents once you pick one (Ama Krushi use case, most likely).
- `respond()` currently lets the LLM freehand the answer. For anything
  factual (crop prices, scheme details) you'll want to swap in a real
  data lookup per intent instead of trusting the LLM's guess.
- Dialect hint is passed in manually for now. A WhatsApp adapter will
  need a way to know which dialect a given user speaks — either ask
  once and store it, or run a lightweight classifier on their first
  message.

## Next steps, in order

1. Run the CLI adapter with a few real dialect sentences per dialect
   you have data for. Judge normalize/understand/stylize quality
   honestly — this tells you if the few-shot approach is enough or if
   you need real fine-tuning sooner than expected.
2. Pick the one real domain (Ama Krushi angle: weather, crop prices,
   govt schemes) and replace the placeholder intent taxonomy + wire
   real data sources into `respond()`.
3. Build `web_adapter.py` (a 20-line FastAPI wrapper) so you can demo
   this in a browser instead of a terminal.
4. Build `whatsapp_adapter.py` once the web version is validated.
5. Only then: `voice_adapter.py` — ASR in, VANI TTS out, same core
   underneath.
