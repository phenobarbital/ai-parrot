"""FEAT-438 smoke script — Z.ai (ZaiClient, native zai SDK).

Exercises ask() / ask()+tool / invoke() against Z.ai's synchronous SDK
(wrapped in asyncio.to_thread() behind the completion funnel — see
ZaiClient._chat_completion). Uses the free-tier lightweight model.

Usage:
    python examples/clients/smoke/smoke_zai.py

Environment Variables:
    ZAI_API_KEY    Required. Skips (exit 0) if unset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="zai",
        model="glm-4.5-flash:free",
        env_vars=["ZAI_API_KEY"],
    )
