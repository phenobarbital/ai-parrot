"""FEAT-438 smoke script — Groq (GroqClient, native AsyncGroq SDK).

Exercises ask() / ask()+tool / invoke() against Groq's OpenAI-compatible
API. Groq's payloads must never carry "strict": true (Groq rejects it) —
that gate is covered offline in tests/clients/test_openai_base_parity.py;
this script only proves the real endpoint accepts the shapes we send.

Usage:
    python examples/clients/smoke/smoke_groq.py

Environment Variables:
    GROQ_API_KEY    Required. Skips (exit 0) if unset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="groq",
        model="kimi-k2-instruct",
        env_vars=["GROQ_API_KEY"],
    )
