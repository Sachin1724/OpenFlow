"""
Universal Dialect Communication Engine
----------------------------------------
Channel-agnostic core. Any adapter (WhatsApp, web, SMS, future voice)
calls `DialectEngine.handle(text, dialect_hint)` and gets back a
reply already styled in the same dialect/register.

Pipeline:
  1. normalize()  -> dialect text to Standard Odia (LLM + few-shot)
  2. understand()  -> intent + entities (LLM, structured JSON output)
  3. respond()     -> answer generation for that intent (LLM or business logic)
  4. stylize()     -> render the Standard Odia answer back in the
                      original dialect's phrasing/register (LLM + few-shot)

This file has NO channel-specific code. Adapters live in /adapters.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Optional

import urllib.request

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
EXAMPLES_PATH = os.path.join(DATA_DIR, "dialect_examples.json")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-6"  # swap as needed


def _load_examples():
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        return json.load(f)


EXAMPLES = _load_examples()


@dataclass
class EngineResult:
    dialect: str
    input_text: str
    normalized_text: str
    intent: str
    entities: dict
    response_standard: str
    response_dialect: str
    raw_debug: dict = field(default_factory=dict)


def _call_claude(system: str, user: str, api_key: str, max_tokens: int = 500) -> str:
    """Minimal Anthropic API call with no SDK dependency (stdlib only)."""
    body = json.dumps({
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return "".join(
        block.get("text", "") for block in data.get("content", [])
        if block.get("type") == "text"
    )


def _few_shot_block(dialect: str, n: int = 8) -> str:
    rows = EXAMPLES.get(dialect, [])[:n]
    if not rows:
        return "(no examples available for this dialect — do your best from general Odia knowledge)"
    lines = []
    for r in rows:
        lines.append(f'Standard Odia: "{r["standard_odia"]}"  ->  {dialect}: "{r["dialect_text"]}"')
    return "\n".join(lines)


# ---- Intent taxonomy (narrow, domain-specific for v1) ----
# Keep this small on purpose. Expand only once real usage data justifies it.
INTENT_TAXONOMY = [
    "greeting",
    "weather_query",
    "crop_price_query",
    "government_scheme_query",
    "complaint",
    "small_talk",
    "unknown",
]


class DialectEngine:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "Set ANTHROPIC_API_KEY env var, or pass api_key= to DialectEngine()."
            )

    def normalize(self, text: str, dialect: str) -> str:
        if dialect.lower().startswith("standard"):
            return text
        system = (
            "You convert colloquial Odia dialect speech into Standard Odia text. "
            "Output ONLY the Standard Odia rendering, nothing else — no preamble, "
            "no quotes, no explanation."
        )
        user = (
            f"Here are example pairs for the {dialect} dialect:\n"
            f"{_few_shot_block(dialect)}\n\n"
            f'Now convert this {dialect} utterance to Standard Odia:\n"{text}"'
        )
        return _call_claude(system, user, self.api_key, max_tokens=200).strip()

    def understand(self, normalized_text: str) -> dict:
        system = (
            "You classify the intent of a Standard Odia sentence for a rural "
            "helpline assistant (think: Ama Krushi farmer helpline). "
            f"Valid intents: {', '.join(INTENT_TAXONOMY)}. "
            "Respond ONLY with compact JSON: "
            '{"intent": "...", "entities": {...}}. No other text.'
        )
        user = f'Sentence: "{normalized_text}"'
        raw = _call_claude(system, user, self.api_key, max_tokens=200).strip()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"intent": "unknown", "entities": {}, "_raw": raw}

    def respond(self, intent: str, entities: dict, normalized_text: str) -> str:
        # v1: let the LLM draft the answer directly.
        # Swap this for real business logic / data lookups per intent as they mature
        # (e.g. crop_price_query -> hit a mandi price API instead of the LLM guessing).
        system = (
            "You are a helpful assistant for a rural Odisha helpline. "
            "Answer briefly and practically in Standard Odia. "
            "If you don't have real data for a factual query (like current prices), "
            "say so honestly rather than inventing numbers."
        )
        user = (
            f"Intent: {intent}\nEntities: {json.dumps(entities, ensure_ascii=False)}\n"
            f"User said (Standard Odia): \"{normalized_text}\"\n"
            "Write a short, natural reply in Standard Odia."
        )
        return _call_claude(system, user, self.api_key, max_tokens=300).strip()

    def stylize(self, standard_text: str, dialect: str) -> str:
        if dialect.lower().startswith("standard"):
            return standard_text
        system = (
            f"You rewrite Standard Odia text into natural {dialect} dialect phrasing, "
            "matching the register and word choices real speakers use. "
            "Output ONLY the rewritten text."
        )
        user = (
            f"Example pairs (Standard Odia -> {dialect}):\n{_few_shot_block(dialect)}\n\n"
            f'Now rewrite this into {dialect}:\n"{standard_text}"'
        )
        return _call_claude(system, user, self.api_key, max_tokens=200).strip()

    def handle(self, text: str, dialect: str) -> EngineResult:
        normalized = self.normalize(text, dialect)
        understanding = self.understand(normalized)
        intent = understanding.get("intent", "unknown")
        entities = understanding.get("entities", {})
        answer_std = self.respond(intent, entities, normalized)
        answer_dialect = self.stylize(answer_std, dialect)

        return EngineResult(
            dialect=dialect,
            input_text=text,
            normalized_text=normalized,
            intent=intent,
            entities=entities,
            response_standard=answer_std,
            response_dialect=answer_dialect,
            raw_debug={"understanding_raw": understanding},
        )
