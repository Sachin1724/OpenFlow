"""
CLI adapter — for local testing.
This is intentionally thin: it just collects input, calls the core
engine, and prints output. A WhatsApp/SMS/web adapter should look
exactly this simple — same call, different transport.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from core.engine import DialectEngine, INTENT_TAXONOMY


def main():
    print("Universal Dialect Engine — CLI test")
    print(f"Known intents: {', '.join(INTENT_TAXONOMY)}")
    print("Available dialects with example data:", end=" ")
    from core.engine import EXAMPLES
    print(", ".join(EXAMPLES.keys()))
    print()

    dialect = input("Dialect (e.g. Sambalpuri, Ganjami, Anugulia, Standard Odia): ").strip()
    text = input("User's message (in that dialect): ").strip()

    engine = DialectEngine()  # reads ANTHROPIC_API_KEY from env
    result = engine.handle(text, dialect)

    print("\n--- Result ---")
    print(f"Input ({dialect}):        {result.input_text}")
    print(f"Normalized (Standard):   {result.normalized_text}")
    print(f"Intent:                  {result.intent}")
    print(f"Entities:                {result.entities}")
    print(f"Response (Standard):     {result.response_standard}")
    print(f"Response ({dialect}):    {result.response_dialect}")


if __name__ == "__main__":
    main()
