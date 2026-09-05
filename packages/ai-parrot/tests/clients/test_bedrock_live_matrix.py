"""Live model-support matrix for AWS Bedrock (FEAT-407 / FEAT-405 follow-up).

These tests make **real, billable** calls to AWS Bedrock through
``BedrockConverseClient`` (native Converse API, SigV4/bearer auth) and
``BedrockMantleClient`` (Project Mantle's OpenAI-compatible endpoint). They
are marked ``real_llm`` and are skipped entirely unless
``PARROT_TEST_REAL_LLM=1`` is set (see ``tests/conftest.py``).

Purpose: this is a *probe*, not a fixed-answer regression test. Every model
listed in ``parrot.clients.amazon.models.PUBLIC_TO_BEDROCK`` /
``AmazonModel`` that is plausibly reachable via a plain ``ask()`` call is
exercised here with a single, tiny prompt and a small ``max_tokens`` budget
so a full run is cheap. A model that the account/region genuinely cannot
reach (no entitlement, no cross-region access, not yet published by AWS)
reports as **SKIPPED** with the provider's error text rather than failing
the suite — only an unexpected error (a real bug in our client code) fails
a case. Run it and read the pass/skip/fail breakdown to see, empirically,
which models this AWS account can actually use today.

Excluded on purpose (not chat/completion models, so ``ask()`` does not
apply): ``nova-sonic`` / ``nova-2-sonic`` (speech-to-speech, real-time
bidirectional protocol — see ``NovaClient`` instead), ``nova-canvas`` /
``nova-reel`` (image/video generation, not chat completion).

Run with::

    source .venv/bin/activate
    PARROT_TEST_REAL_LLM=1 pytest \\
        packages/ai-parrot/tests/clients/test_bedrock_live_matrix.py -v -s

Narrow to one client with ``-k converse`` or ``-k mantle``.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import pytest

from parrot.clients.amazon.bedrock import BedrockConverseClient
from parrot.clients.amazon.nova.mantle import BedrockMantleClient

pytestmark = [pytest.mark.real_llm, pytest.mark.asyncio]

#: Kept small on purpose — this is a connectivity/wiring probe, not a quality
#: eval. One short word is enough to prove the round trip produced real text.
#: 16 is NOT enough: several catalogued models (Claude 5's adaptive thinking,
#: gpt-oss-120b / minimax-m2.5's hidden chain-of-thought) spend part of the
#: completion budget on reasoning before emitting a single visible character,
#: so a too-tight cap truncates before any answer appears — Bedrock Converse
#: just returns a stopReason of "max_tokens" with empty/partial text, but the
#: OpenAI SDK's chat.completions.parse() helper that BedrockMantleClient goes
#: through raises ``openai.LengthFinishReasonError`` outright. 256 clears the
#: reasoning overhead on every model above while staying cheap.
PROMPT = "Reply with exactly one word: PONG"
MAX_TOKENS = 256
TIMEOUT_SECONDS = 60.0


# --------------------------------------------------------------------------- #
# Credential preflight — mirrors artifacts/feat481_structured_output_matrix.py
# so a missing-credential run reports SKIP instead of a wall of errors.
# --------------------------------------------------------------------------- #


def _conf_get(name: str):
    """Read a setting the way the framework does (navconfig, then os.environ)."""
    try:
        from navconfig import config

        value = config.get(name)
        if value:
            return value
    except Exception:
        pass
    return os.environ.get(name)


def _aws_sigv4_available() -> bool:
    """True when a static keypair or a local profile can sign Bedrock calls."""
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if (Path.home() / ".aws" / "credentials").exists():
        return True
    try:
        from parrot.conf import AWS_CREDENTIALS

        return bool(AWS_CREDENTIALS)
    except Exception:
        return False


def _bedrock_bearer_available() -> bool:
    """True when a Bedrock API key (bearer token) is configured."""
    try:
        from parrot.conf import AWS_NOVA_API_KEY
    except Exception:
        AWS_NOVA_API_KEY = None
    return bool(_conf_get("AWS_BEARER_TOKEN_BEDROCK") or AWS_NOVA_API_KEY)


def _missing_converse_credentials() -> Optional[str]:
    if _bedrock_bearer_available() or _aws_sigv4_available():
        return None
    return "no AWS credentials for Bedrock Converse (profile, static keys, or bearer token)"


def _missing_mantle_credentials() -> Optional[str]:
    try:
        from parrot.conf import BEDROCK_MANTLE_API_KEY
    except Exception:
        BEDROCK_MANTLE_API_KEY = None
    if BEDROCK_MANTLE_API_KEY or _bedrock_bearer_available():
        return None
    return "no Bedrock API key for Mantle (BEDROCK_MANTLE_API_KEY or AWS_NOVA_API_KEY)"


# --------------------------------------------------------------------------- #
# Error classification — an account/entitlement problem is not a code bug.
# --------------------------------------------------------------------------- #

_UNAVAILABLE_MARKERS = (
    "accessdenied",
    "access denied",
    "don't have access",
    "not authorized",
    "unauthorized",
    "unrecognizedclient",
    "security token",
    "resourcenotfound",
    "validationexception",
    "model identifier is invalid",
    "on-demand throughput isn't supported",
    "provisioned throughput",
    "could not be resolved",  # DNS failure — region/endpoint not live yet
    "name or service not known",
    "404",
    "not found",
)


def _classify(exc: Exception) -> str:
    """Return ``"unavailable"`` for an account/entitlement/DNS error, else ``"error"``."""
    text = f"{type(exc).__name__}: {exc}".lower()
    if any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return "unavailable"
    return "error"


async def _probe_ask(client, model: str) -> None:
    """Send the minimal prompt to *model* and assert a real text reply came back.

    Skips (does not fail) the case when the provider reports an
    account/entitlement/DNS problem; fails on anything else.
    """
    try:
        try:
            async with client:
                result = await asyncio.wait_for(
                    client.ask(PROMPT, model=model, max_tokens=MAX_TOKENS),
                    timeout=TIMEOUT_SECONDS,
                )
        finally:
            # __aexit__ only closes the plain aiohttp `session` (use_session=True
            # clients) — it does NOT close the per-event-loop SDK client that
            # _ensure_client() caches (aioboto3 Bedrock client / AsyncOpenAI
            # client), which is what actually owns the open TCP connector. Each
            # parametrized case here builds a fresh client on a fresh
            # pytest-asyncio loop, so without this the run leaks one
            # ClientSession per case ("Unclosed client session" from asyncio's
            # exception handler when it's later garbage-collected).
            await client.close()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"[:300]
        if _classify(exc) == "unavailable":
            pytest.skip(f"{model}: not available on this account/region — {detail}")
        raise AssertionError(f"{model}: unexpected error — {detail}") from exc

    assert isinstance(result.output, str) and result.output.strip(), (
        f"{model}: empty response (stop_reason={getattr(result, 'stop_reason', None)!r})"
    )
    print(f"OK  {model!r} -> {result.output.strip()[:60]!r}")


# --------------------------------------------------------------------------- #
# BedrockConverseClient — native Converse API, public IDs from
# parrot.clients.amazon.models.PUBLIC_TO_BEDROCK (translate() resolves the
# Bedrock modelId, including any required cross-region inference prefix).
# --------------------------------------------------------------------------- #

CONVERSE_MODELS = [
    # Claude 5 (2026 generation, FEAT-405) — region-prefix auto-applied.
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-fable-5-1",
    # Claude 4.6 — speculative dated IDs per models.py; may not exist on
    # Bedrock yet, in which case they report SKIP, not FAIL.
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    # Claude 4.5 / 4.1 / 4 / 3.x
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4-5",
    "claude-opus-4-1",
    "claude-sonnet-4-20250514",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-haiku-20241022",
    # Amazon Nova (text-capable only)
    "nova-pro",
    "nova-lite",
    "nova-micro",
    "nova-premier",
    "nova-2-lite",
    # Third-party models served on Bedrock
    "llama4-maverick-17b-instruct",
    "qwen3-coder-480b-a35b",
    "glm-5",
    "kimi-k2.5",
]


@pytest.mark.parametrize("model", CONVERSE_MODELS)
async def test_bedrock_converse_model_live(model):
    """Every catalogued Converse-API model answers a minimal prompt."""
    reason = _missing_converse_credentials()
    if reason:
        pytest.skip(reason)
    client = BedrockConverseClient()
    await _probe_ask(client, model)


# --------------------------------------------------------------------------- #
# BedrockMantleClient — OpenAI-compatible endpoint. Mantle does NOT run
# public IDs through translate(): ids are passed to the endpoint verbatim,
# so this list uses the Mantle-native spellings documented in
# parrot/clients/amazon/models.py / nova/mantle.py.
# --------------------------------------------------------------------------- #

MANTLE_MODELS = [
    "openai.gpt-oss-120b",  # BedrockMantleClient._default_model
    # NOT "google.gemma-4-26b-a4b": confirmed live (2026-09-05) to 400 with
    # "isn't supported on this route" — not a valid id on Mantle's
    # chat-completions route at all. BedrockMantleClient._fallback_model
    # was dropped to None over this finding; see nova/mantle.py.
    "anthropic.claude-sonnet-4-5-20250929-v1:0",
    "anthropic.claude-haiku-4-5-20251001-v1:0",
    "minimax.minimax-m2.5",
    "moonshotai.kimi-k2.5",
    "zai.glm-5",
    "qwen.qwen3-coder-480b-a35b-instruct",
]


@pytest.mark.parametrize("model", MANTLE_MODELS)
async def test_bedrock_mantle_model_live(model):
    """Every catalogued Mantle model answers a minimal prompt."""
    reason = _missing_mantle_credentials()
    if reason:
        pytest.skip(reason)
    client = BedrockMantleClient()
    await _probe_ask(client, model)
