"""FEAT-438 smoke script — Nvidia NIM (NvidiaClient).

Exercises ask() / ask()+tool / invoke() against Nvidia's OpenAI-compatible
NIM gateway. Also implicitly exercises the free-tier rate limiter (every
call reserves a slot via the completion funnel).

Usage:
    python examples/clients/smoke/smoke_nvidia.py

Environment Variables:
    NVIDIA_API_KEY    Required. Skips (exit 0) if unset.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="nvidia",
        model="minimaxai/minimax-m3",
        env_vars=["NVIDIA_API_KEY"],
    )
