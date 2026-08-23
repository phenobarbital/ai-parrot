"""FEAT-438 smoke script — OpenRouter (OpenRouterClient).

Exercises ask() / ask()+tool / invoke() against OpenRouter's multi-model
gateway.

Usage:
    python examples/clients/smoke/smoke_openrouter.py

Environment Variables:
    OPENROUTER_API_KEY    Required. Skips (exit 0) if unset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="openrouter",
        model="deepseek/deepseek-r1",
        env_vars=["OPENROUTER_API_KEY"],
    )
