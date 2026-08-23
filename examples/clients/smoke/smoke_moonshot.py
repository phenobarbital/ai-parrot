"""FEAT-438 smoke script — Moonshot / Kimi (MoonshotClient).

Exercises ask() / ask()+tool / invoke() against Moonshot's OpenAI-
compatible API. Uses a legacy (non-K-series) model so the request never
needs the K-series fixed-sampling-parameter stripping — that path is
already covered offline in tests/clients/test_moonshot_client.py.

Usage:
    python examples/clients/smoke/smoke_moonshot.py

Environment Variables:
    MOONSHOT_API_KEY    Required. Skips (exit 0) if unset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="moonshot",
        model="moonshot-v1-128k",
        env_vars=["MOONSHOT_API_KEY"],
    )
