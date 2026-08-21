"""FEAT-438 smoke script — OpenAI (positive control).

Exercises ask() / ask()+tool / invoke() against the real OpenAI API using
the cheapest available model. This is the positive control for the
OpenAI-compatible client base: OpenAIClient legitimately KEEPS its
gpt-* defaults (it IS OpenAI-the-provider), unlike every other script in
this directory.

Usage:
    python examples/clients/smoke/smoke_openai.py

Environment Variables:
    OPENAI_API_KEY    Required. Skips (exit 0) if unset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="openai",
        model="gpt-5-nano",
        env_vars=["OPENAI_API_KEY"],
    )
