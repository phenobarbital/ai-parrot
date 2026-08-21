"""FEAT-438 smoke script — Amazon Bedrock Mantle (BedrockMantleClient).

Exercises ask() / ask()+tool / invoke() against the real Bedrock Mantle
endpoint. This is the original production repro path (DeepSeek V3.2
receiving an OpenAI gpt-4.1 default via the invoke() fallback chain,
FEAT-438's motivating bug) — the invoke() leg is the most important one
here.

Usage:
    python examples/clients/smoke/smoke_mantle.py

Environment Variables (any one of the API-key vars is sufficient):
    BEDROCK_MANTLE_API_KEY   Dedicated Bedrock Mantle bearer token.
    AWS_NOVA_API_KEY         Shared Bedrock API key fallback.
    BEDROCK_AWS_REGION / AWS_REGION_NAME   Optional region override
                             (defaults to us-east-1).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from _runner import main_for

if __name__ == "__main__":
    main_for(
        provider="bedrock-mantle",
        model="openai.gpt-oss-120b",
        env_vars=["BEDROCK_MANTLE_API_KEY", "AWS_NOVA_API_KEY"],
    )
