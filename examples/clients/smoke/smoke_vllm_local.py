"""FEAT-438 smoke script — local vLLM server (vLLMClient).

Exercises ask() / ask()+tool / invoke() against a self-hosted vLLM
server. Unlike the cloud-hosted providers in this directory, there is no
API-key concept by default — the gate here is the server's *base URL*
being configured at all, so this script never attempts a connection on a
machine with no local server running.

Usage:
    VLLM_BASE_URL=http://localhost:8000/v1 python examples/clients/smoke/smoke_vllm_local.py

Environment Variables (any one of the base-url vars is sufficient):
    VLLM_BASE_URL        Preferred override for the vLLM server URL.
    LOCAL_LLM_BASE_URL   Shared fallback with LocalLLMClient.
    VLLM_API_KEY / LOCAL_LLM_API_KEY   Optional — most local servers
                         don't require authentication.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="vllm",
        model="llama3.1:8b",
        env_vars=["VLLM_BASE_URL", "LOCAL_LLM_BASE_URL"],
    )
