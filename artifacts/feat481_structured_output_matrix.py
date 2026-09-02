#!/usr/bin/env python
"""FEAT-481 — LIVE cross-provider structured-output matrix.

Answers one question with real network calls (no mocks, no fixtures of model
output): **which LLMs actually satisfy a Pydantic ``output_type`` through
``AbstractClient.invoke()``, and which degenerate into unparseable text that
``_parse_structured_output`` hands back as a raw ``str``?**

The bug report (``artifacts/FEAT-481-cheap-tier-extraction-bug.md``) concluded
that the failure is *schema-level* because "every Gemini tier, including
``gemini-2.5-pro``, fails identically". This harness exists because that
conclusion rests on an untested assumption — see **The model-pinning trap**
below.

The model-pinning trap
----------------------
``AbstractClient._resolve_invoke_model()`` (``clients/base.py``) resolves the
model for an ``invoke()`` call as::

    explicit ``model=`` argument  >  ``self._lightweight_model``  >  ``self.model``

``self.model`` — the model you selected via ``LLMFactory.create("google:gemini-2.5-pro")``
— is **last**. Every client that defines a class-level ``_lightweight_model``
therefore ignores your model selection unless ``invoke()`` is given an explicit
``model=``. As of this writing that is: ``GoogleGenAIClient``
(``gemini-3.1-flash-lite``), ``AnthropicClient`` / ``BedrockConverseClient`` /
``ClaudeAgentClient`` (``claude-haiku-4-5-20251001``), ``OpenAIClient``
(``gpt-4.1``), ``GroqClient``, ``GrokClient``, ``ZaiClient``.

The predecessor probe (``feat481_extraction_model_probe.py``) never passed
``model=``, so every one of its Gemini rows — flash, flash-lite **and pro** —
almost certainly executed on the same ``gemini-3.1-flash-lite``. That is the
simplest explanation for the report's own observation that all three tiers
produced *byte-identical* ~25.3 KB degeneration failing at the same column.

This harness therefore runs **both** resolution modes and shows them
side by side:

* ``--pin-model`` (default) — passes ``model=`` explicitly, so the row's label
  is the model that actually ran.
* ``--no-pin-model``        — reproduces the predecessor's call shape, so you
  can see the collapse onto ``_lightweight_model`` directly.

Every row reports ``requested`` vs ``effective`` model (``InvokeResult.model``),
so a silent substitution is visible in the table rather than inferred.

What it measures
----------------
For each (model × schema) cell it runs the *real* FEAT-481 extraction call —
the same ``MeetingPageExtraction`` shape, the same system prompt, the same
prompt builder, ``temperature=0.0``, ``max_tokens=4096`` — and classifies the
result:

    OK            ``result.output`` is the requested Pydantic model
    STR-LEAK      ``result.output`` came back a raw ``str`` (parse failed; the
                  provider's ``invoke()`` has no recovery guard)
    INVOKE-ERROR  ``invoke()`` raised (e.g. Google's post-FEAT-481 guard, or a
                  provider-side error)
    TIMEOUT       the call exceeded ``--timeout`` seconds
    UNAVAIL       the account cannot reach this model at all (no credits, no
                  entitlement, model retired) — carries NO information about
                  the model's structured-output ability, and is deliberately
                  kept distinct from a real failure
    SKIP          provider credentials are not configured on this machine
    ERROR         anything else (unknown model, transport)

On any non-OK result it also fingerprints the raw model text captured from
``_parse_structured_output``: JSON validity, whether it is truncated
(unbalanced braces / no closing ``}``), and the maximum number of times a
single sentence repeats — the degeneration signature from the report.

Schemas (``--schemas``)
-----------------------
    page           exact replica of ``MeetingPageExtraction`` (the failing call)
    page_capped    same fields with ``max_length`` + guidance (fix hypothesis #1)
    classification replica of the small ``Classification`` schema (control —
                   the report says this one always parses)

Running two or three schemas separates "this model cannot do structured output
at all" from "this model cannot do *this* schema", which is the distinction the
bug report needs and does not have.

Usage
-----
    source .venv/bin/activate
    export PARROT_MATRIX_LIVE=1          # required: this spends real money

    # the headline run — the full provider matrix on the failing schema
    python artifacts/feat481_structured_output_matrix.py --preset all

    # the pinning A/B that tests the report's central claim
    python artifacts/feat481_structured_output_matrix.py --preset google \
        --schemas page --pin-model
    python artifacts/feat481_structured_output_matrix.py --preset google \
        --schemas page --no-pin-model

    # schema comparison on a couple of models
    python artifacts/feat481_structured_output_matrix.py \
        --models google:gemini-2.5-pro,anthropic:claude-opus-5 \
        --schemas page,page_capped,classification

    # against the real Fireflies bundle that first triggered the bug
    python artifacts/feat481_structured_output_matrix.py --preset all \
        --meeting-dir /path/to/Raw/Processed/.../<fireflies_id> --transcript

Credentials are read the same way the framework reads them (``navconfig``
picking up ``env/<ENV>/``), so a provider with no key configured reports SKIP
rather than failing the run.

Outputs: a rendered table on stdout, plus ``matrix-<ts>.json`` /
``matrix-<ts>.md`` / ``raw/*.txt`` under ``--out-dir``
(default ``artifacts/logs/feat481``).
"""
from __future__ import annotations

import uvloop

uvloop.install()

import argparse
import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO_ROOT / "artifacts" / "feat481_fixtures" / "meeting_large_summary.md"
DEFAULT_OUT_DIR = REPO_ROOT / "artifacts" / "logs" / "feat481"


# --------------------------------------------------------------------------- #
# 1. Schemas — self-contained replicas of the FEAT-481 contracts.
#
# Deliberately NOT imported from parrot.flows.wiki_ingest: that package lives
# only on the feat-481 branch, and this harness must run from `dev` (or any
# branch) so the matrix can be re-run after the fix lands.
# Source of truth: flows/wiki_ingest/models.py + nodes/meeting_page.py on
# origin/feat-481-fireflies-wiki-knowledgebase-agent.
# --------------------------------------------------------------------------- #


class ActionItem(BaseModel):
    """One row of the §17 ``## Action Items`` table."""

    action: str
    owner: str = "Unknown"
    due_date: str = "Unknown"
    status: str = "Open"
    source_confidence: Literal["High", "Medium", "Low"] = "Medium"


class MeetingExtraction(BaseModel):
    """§15.2 — the frozen Module 5 extraction contract."""

    decisions: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    potential_contradictions: list[str] = Field(default_factory=list)


class MeetingPageExtraction(MeetingExtraction):
    """§17 — the exact schema whose ``invoke()`` call fails in the report.

    Note for the record: the bug report describes this class as also carrying
    ``filename``, ``content`` and ``vault_path``. It does not — those belong to
    ``MeetingPageResult``, which is built in Python from the extraction. The
    model is never asked to emit a rendered page, so "the schema asks for a
    whole page" is not among the causes of the degeneration.
    """

    executive_summary: str
    purpose: str


class MeetingPageExtractionCapped(MeetingExtraction):
    """Fix hypothesis #1 — the same fields with explicit length budgets.

    If a model fails ``page`` but passes ``page_capped``, the degeneration is
    driven by unbounded free text and the fix belongs in the schema. If it
    fails both, the schema is not the lever.
    """

    executive_summary: str = Field(
        ...,
        max_length=1200,
        description="3-5 sentences, at most 1200 characters. Do not repeat yourself.",
    )
    purpose: str = Field(
        ...,
        max_length=400,
        description="A single sentence, at most 400 characters. Do not repeat yourself.",
    )


class Classification(BaseModel):
    """§15 — the small control schema the report says always parses."""

    primary_client: str | None = None
    primary_project: str | None = None
    additional_projects: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    products: list[str] = Field(default_factory=list)
    concepts: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"]
    transcript_fallback_reason: str | None = None


#: Verbatim from ``nodes/meeting_page.py::_SYSTEM_PROMPT``.
_PAGE_SYSTEM_PROMPT = (
    "You are extracting structured content for a canonical meeting page. "
    "Write a concise executive summary and purpose, plus decisions, "
    "requirements, action items (owner/due date/status/confidence), risks, "
    "open questions, and potential contradictions. Never invent a name, "
    "date, owner, or decision that is not supported by the source text — "
    "use 'Unknown', 'Not established', or 'Requires review' when evidence "
    "is insufficient (rule #12). Never include a direct quote here."
)

#: Verbatim from ``nodes/classify.py`` in spirit — the control call's framing.
_CLASSIFY_SYSTEM_PROMPT = (
    "You are classifying a meeting. Identify the primary client, the primary "
    "project, any additional projects, and the people, products and concepts "
    "discussed. Never invent a name that is not supported by the source text."
)

SCHEMAS: dict[str, tuple[type[BaseModel], str]] = {
    "page": (MeetingPageExtraction, _PAGE_SYSTEM_PROMPT),
    "page_capped": (MeetingPageExtractionCapped, _PAGE_SYSTEM_PROMPT),
    "classification": (Classification, _CLASSIFY_SYSTEM_PROMPT),
}


# --------------------------------------------------------------------------- #
# 2. Model matrix
# --------------------------------------------------------------------------- #

#: ``provider:model`` → the credential(s) that must resolve for it to run.
#: Providers whose credentials are absent report SKIP instead of ERROR, so a
#: partial matrix is still a usable matrix.
PROVIDER_CREDENTIALS: dict[str, tuple[str, ...]] = {
    "google": ("GOOGLE_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "claude": ("ANTHROPIC_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "nvidia": ("NVIDIA_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    # AWS-backed providers: any of a profile, static keys, or a bearer token.
    "bedrock": ("__aws__",),
    "bedrock-converse": ("__aws__",),
    "nova": ("__aws__",),
    "bedrock-mantle": ("AWS_NOVA_API_KEY", "AWS_BEARER_TOKEN_BEDROCK"),
    # Agent/CLI-backed providers: need the CLI (or its SDK) on PATH.
    "claude-agent": ("__cli:claude__",),
    "codex-agent": ("__cli:codex__",),
}

PRESETS: dict[str, list[str]] = {
    # The Gemini rows the report is built on, plus the model that
    # `_lightweight_model` silently substitutes for all of them.
    "google": [
        "google:gemini-3.1-flash-lite",   # the actual _lightweight_model
        "google:gemini-3.5-flash-lite",
        "google:gemini-2.5-flash-lite",
        "google:gemini-2.5-flash",
        "google:gemini-3.8-flash",
        "google:gemini-2.5-pro",
        "google:gemini-3.1-pro-preview",
    ],
    # Anthropic via the direct API client (schema injected into the system
    # prompt — no native structured-output enforcement).
    "anthropic": [
        "anthropic:claude-opus-5",
        "anthropic:claude-haiku-4-5-20251001",
        "anthropic:claude-fable-5.1",
    ],
    # The same Claude models over AWS Bedrock's native Converse API. This is
    # the AWS path that authenticates from parrot.conf AWS credentials; see
    # the "bedrock-sdk" preset below for the AnthropicBedrock SDK path.
    "bedrock": [
        "bedrock-converse:claude-opus-5",
        "bedrock-converse:claude-sonnet-5",
        "bedrock-converse:claude-haiku-4-5",
        "bedrock-converse:claude-fable-5",
    ],
    # AnthropicClient with backend="bedrock" (AsyncAnthropicBedrock). Kept
    # separate because it resolves AWS credentials through the anthropic SDK's
    # own chain rather than parrot.conf, and can therefore fail (403) on an
    # account where the Converse rows above succeed.
    "bedrock-sdk": [
        "bedrock:claude-opus-5",
        "bedrock:claude-haiku-4-5",
    ],
    # Open-weights models on Bedrock plus the Amazon Nova family.
    "aws-oss": [
        "bedrock-converse:qwen.qwen3-32b-v1:0",
        "bedrock-converse:qwen.qwen3-coder-30b-a3b-v1:0",
        "bedrock-converse:us.deepseek.r1-v1:0",
        "bedrock-converse:openai.gpt-oss-120b-1:0",
        "nova:nova-2-lite",
        "nova:nova-lite",
        "nova:nova-pro",
    ],
    "openai": [
        "openai:gpt-5-mini",
        "openai:gpt-4.1",
    ],
    "nvidia": [
        "nvidia:openai/gpt-oss-120b",
        "nvidia:deepseek-ai/deepseek-v4-pro-0813",
        "nvidia:nvidia/nemotron-3-super-120b-a12b",
    ],
    # Agent-SDK / CLI-backed clients — slow, serial, and worth knowing about
    # because they parse structured output through a different path.
    "agents": [
        "claude-agent:claude-opus-5",
        "codex-agent:gpt-5.6-sol",
    ],
}
PRESETS["all"] = [m for name in ("google", "anthropic", "bedrock", "aws-oss", "openai", "nvidia", "agents")
                  for m in PRESETS[name]]
#: The two rows that reproduce the reported failure fastest.
PRESETS["baseline"] = ["google:gemini-3.1-flash-lite", "google:gemini-2.5-pro"]

#: Extra constructor kwargs per provider key, merged into ``LLMFactory.create``.
#: The Codex client's SDK backend needs the optional ``openai-codex`` package;
#: its CLI backend reuses the installed ``codex`` login, which is what a
#: developer machine actually has — and structured ``invoke()`` runs through
#: ``codex exec`` in either case.
CLIENT_KWARGS: dict[str, dict[str, Any]] = {
    "codex-agent": {"backend": "cli"},
    "openai-codex": {"backend": "cli"},
    "codex-code": {"backend": "cli"},
}

#: Substrings that mark a failure as an account/provider problem rather than a
#: model failing the schema. These become UNAVAIL, so the matrix never reads a
#: billing or entitlement error as evidence about a model's JSON ability.
_UNAVAILABLE_MARKERS = (
    "credit balance",
    "no credits remaining",
    "insufficient_quota",
    "exceeded your current quota",
    "security token included in the request is invalid",
    "unrecognizedclient",
    "accessdenied",
    "is not found for api version",
    "model identifier is invalid",
    "the model returned",
    "end of life",
    "invalid_api_key",
    "authentication",
    "unauthorized",
    "requires openai-codex",
    "requires claude-agent-sdk",
    "not initialised",
    "not found for account",
    "not supported when using codex with a chatgpt account",
    # A per-model output cap below the requested budget is a request-shape
    # problem, not the model failing the schema (Nova Pro caps at 10000).
    "exceeds the model limit",
)


def is_unavailable(detail: str) -> bool:
    """True when *detail* describes a provider/account problem, not a model one.

    Args:
        detail: The error text captured for a cell.

    Returns:
        Whether the cell should be reported as UNAVAIL rather than a failure.
    """
    lowered = (detail or "").lower()
    return any(marker in lowered for marker in _UNAVAILABLE_MARKERS)


# --------------------------------------------------------------------------- #
# 3. Credential preflight
# --------------------------------------------------------------------------- #


def _conf_get(name: str) -> Any:
    """Read a setting the way the framework does (navconfig, then os.environ)."""
    try:
        from navconfig import config  # type: ignore

        value = config.get(name)
        if value:
            return value
    except Exception:  # navconfig unavailable or misconfigured — fall through
        pass
    return os.environ.get(name)


def _aws_available() -> bool:
    """True when *some* AWS credential source is resolvable on this machine."""
    if _conf_get("AWS_BEARER_TOKEN_BEDROCK") or _conf_get("AWS_NOVA_API_KEY"):
        return True
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if (Path.home() / ".aws" / "credentials").exists():
        return True
    try:
        from parrot.conf import AWS_CREDENTIALS  # type: ignore

        return bool(AWS_CREDENTIALS)
    except Exception:
        return False


def _cli_available(name: str) -> bool:
    """True when ``name`` is an executable on PATH."""
    from shutil import which

    return which(name) is not None


def missing_credential(provider: str) -> Optional[str]:
    """Return a human-readable reason this provider cannot run, or ``None``.

    Args:
        provider: The ``LLMFactory`` provider key (the part before the colon).

    Returns:
        A short reason string when credentials are absent, else ``None``.
    """
    required = PROVIDER_CREDENTIALS.get(provider)
    if not required:
        return None
    for req in required:
        if req == "__aws__":
            if _aws_available():
                return None
            continue
        if req.startswith("__cli:"):
            if _cli_available(req[6:-2]):
                return None
            continue
        if _conf_get(req):
            return None
    if required == ("__aws__",):
        return "no AWS credentials (profile/keys/bearer)"
    if len(required) == 1 and required[0].startswith("__cli:"):
        return f"{required[0][6:-2]} CLI not on PATH"
    return f"missing {'/'.join(required)}"


# --------------------------------------------------------------------------- #
# 4. Raw-output capture
# --------------------------------------------------------------------------- #


def install_parse_capture() -> None:
    """Tee ``AbstractClient._parse_structured_output`` onto the client instance.

    The parse step is the only place the raw provider text is still available
    once ``invoke()`` has either swallowed it (returning the ``str``) or a
    provider guard has converted it into an ``InvokeError``. Recording it on
    ``self`` — rather than in a module-global — keeps attribution correct when
    several cells run concurrently, because each cell owns its own client.
    """
    from parrot.clients.base import AbstractClient

    if getattr(AbstractClient, "_feat481_capture_installed", False):
        return

    original = AbstractClient._parse_structured_output

    async def _capturing(self, response_text, structured_output):  # type: ignore[no-untyped-def]
        result = await original(self, response_text, structured_output)
        self._feat481_last_parse = {  # type: ignore[attr-defined]
            "raw_text": response_text,
            "returned_str": isinstance(result, str),
        }
        return result

    AbstractClient._parse_structured_output = _capturing  # type: ignore[method-assign]
    AbstractClient._feat481_capture_installed = True  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# 5. Failure fingerprinting
# --------------------------------------------------------------------------- #

_SENTENCE_RE = re.compile(r"[^.!?]{25,}[.!?]")


def fingerprint(raw: str) -> dict[str, Any]:
    """Characterise a raw model response that failed to parse.

    Args:
        raw: The provider's response text as seen by ``_parse_structured_output``.

    Returns:
        A dict with ``chars``, ``json_valid``, ``truncated``, ``max_repeat``
        (how many times the most-repeated sentence occurs) and ``mode`` — a
        one-word classification of the failure.
    """
    text = (raw or "").strip()
    info: dict[str, Any] = {"chars": len(text)}

    stripped = text
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    try:
        json.loads(stripped)
        info["json_valid"] = True
    except Exception:
        info["json_valid"] = False

    opens, closes = stripped.count("{"), stripped.count("}")
    info["truncated"] = (not info["json_valid"]) and (opens > closes or not stripped.endswith(("}", "]")))

    counts: dict[str, int] = {}
    for sentence in _SENTENCE_RE.findall(text):
        key = " ".join(sentence.split()).lower()
        counts[key] = counts.get(key, 0) + 1
    info["max_repeat"] = max(counts.values(), default=0)

    if info["json_valid"]:
        info["mode"] = "valid-json-wrong-shape"
    elif info["max_repeat"] >= 5 and info["truncated"]:
        info["mode"] = "repetition-loop→truncated"
    elif info["max_repeat"] >= 5:
        info["mode"] = "repetition-loop"
    elif info["truncated"]:
        info["mode"] = "truncated-json"
    elif not text:
        info["mode"] = "empty"
    elif not stripped.lstrip().startswith(("{", "[")):
        info["mode"] = "prose-not-json"
    else:
        info["mode"] = "malformed-json"
    return info


# --------------------------------------------------------------------------- #
# 6. The probe
# --------------------------------------------------------------------------- #


def build_prompt(meeting: dict[str, Any], *, transcript: bool) -> str:
    """Replica of ``nodes/meeting_page.py::_build_prompt``.

    Args:
        meeting: The loaded meeting dict.
        transcript: Whether to append the full transcript, as the node does
            when the transcript-fallback fired.

    Returns:
        The prompt text sent to every model in the matrix.
    """
    parts = [
        f"Meeting title: {meeting['title']}",
        f"Meeting date: {meeting['meeting_date']}",
        "",
        "Fireflies summary:",
        meeting["summary_text"] or "(no summary available)",
    ]
    if transcript:
        parts += ["", "Full transcript:", meeting["transcript_text"] or "(no transcript available)"]
    return "\n".join(parts)


def _usage_out_tokens(usage: Any) -> Optional[int]:
    """Best-effort output-token count across the providers' usage shapes."""
    for attr in ("completion_tokens", "output_tokens", "candidates_token_count"):
        value = getattr(usage, attr, None)
        if value:
            return int(value)
    return None


def _finish_reason(raw_response: Any) -> str:
    """Best-effort stop reason from a provider's raw response.

    This is the field that settles *why* a structured call failed, and it is
    the one ``invoke()`` never inspects: a response cut off at the output-token
    cap (``MAX_TOKENS`` / ``max_tokens`` / ``length``) is truncated by the
    budget, whereas a completed response (``STOP``) that still fails to parse
    means the model emitted something that is not the schema. Without it the
    two are indistinguishable from the outside, which is exactly how the bug
    report ended up attributing a budget truncation to the schema.

    Args:
        raw_response: The provider-native response object on ``InvokeResult``.

    Returns:
        A short reason string, or ``""`` when the provider does not expose one.
    """
    if raw_response is None:
        return ""
    # Google: response.candidates[0].finish_reason
    try:
        candidates = getattr(raw_response, "candidates", None)
        if candidates:
            reason = getattr(candidates[0], "finish_reason", None)
            if reason is not None:
                return str(getattr(reason, "name", reason))
    except Exception:
        pass
    # Anthropic: response.stop_reason · OpenAI: choices[0].finish_reason
    for attr in ("stop_reason", "stopReason", "finish_reason"):
        value = getattr(raw_response, attr, None)
        if value:
            return str(value)
    try:
        choices = getattr(raw_response, "choices", None)
        if choices:
            value = getattr(choices[0], "finish_reason", None)
            if value:
                return str(value)
    except Exception:
        pass
    # Bedrock Converse returns a plain dict.
    if isinstance(raw_response, dict):
        for key in ("stopReason", "stop_reason", "finish_reason"):
            if raw_response.get(key):
                return str(raw_response[key])
    return ""


def _thinking_tokens(raw_response: Any) -> Optional[int]:
    """Reasoning tokens billed against the output budget, when reported.

    Gemini 3.x and other thinking models spend part of ``max_output_tokens``
    on reasoning before emitting a single character of JSON, so a nominally
    generous 4096-token budget can leave too little room for the schema.
    """
    try:
        usage = getattr(raw_response, "usage_metadata", None)
        value = getattr(usage, "thoughts_token_count", None)
        if value:
            return int(value)
    except Exception:
        pass
    try:
        details = getattr(getattr(raw_response, "usage", None), "completion_tokens_details", None)
        value = getattr(details, "reasoning_tokens", None)
        if value:
            return int(value)
    except Exception:
        pass
    return None


async def probe_cell(
    spec: str,
    schema_name: str,
    prompt: str,
    *,
    pin_model: bool,
    max_tokens: int,
    timeout: float,
) -> dict[str, Any]:
    """Run one (model × schema) cell of the matrix against the live provider.

    Args:
        spec: ``provider:model`` string for :meth:`LLMFactory.create`.
        schema_name: A key of :data:`SCHEMAS`.
        prompt: The extraction prompt (identical for every cell).
        pin_model: When ``True``, pass ``model=`` to ``invoke()`` so the
            requested model is the one that runs. When ``False``, omit it and
            let ``_resolve_invoke_model`` fall back to ``_lightweight_model`` —
            the predecessor probe's call shape.
        max_tokens: ``max_tokens`` for the call (``invoke()``'s default is 4096).
        timeout: Per-cell wall-clock budget in seconds.

    Returns:
        A row dict: verdict, requested/effective model, timings, token usage
        and — on failure — the raw-output fingerprint and captured text.
    """
    from parrot.clients.factory import LLMFactory
    from parrot.exceptions import InvokeError

    output_type, system_prompt = SCHEMAS[schema_name]
    provider, _, model_name = spec.partition(":")
    row: dict[str, Any] = {
        "spec": spec,
        "provider": provider,
        "requested_model": model_name or "(provider default)",
        "schema": schema_name,
        "verdict": "",
        "effective_model": "",
        "default_invoke_model": "",
        "pinned": pin_model,
        "seconds": None,
        "out_tokens": None,
        "finish_reason": "",
        "thinking_tokens": None,
        "detail": "",
        "full_error": "",
        "raw": None,
        "fingerprint": None,
    }

    reason = missing_credential(provider)
    if reason:
        row["verdict"] = "SKIP"
        row["detail"] = reason
        return row

    try:
        client = LLMFactory.create(spec, **CLIENT_KWARGS.get(provider, {}))
    except Exception as exc:
        detail = f"create: {type(exc).__name__}: {exc}"[:200]
        row["verdict"] = "UNAVAIL" if is_unavailable(detail) else "ERROR"
        row["detail"] = detail
        return row

    # What this client WOULD run if invoke() were called without model= —
    # this is the value that silently replaced the caller's choice in the
    # predecessor probe, so it belongs in the record whether or not we pin.
    try:
        row["default_invoke_model"] = client._resolve_invoke_model(None)
    except Exception:
        row["default_invoke_model"] = "?"

    kwargs: dict[str, Any] = {
        "output_type": output_type,
        "system_prompt": system_prompt,
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    if pin_model and model_name:
        kwargs["model"] = model_name

    started = time.monotonic()
    try:
        async with client:
            result = await asyncio.wait_for(client.invoke(prompt, **kwargs), timeout=timeout)
        row["seconds"] = round(time.monotonic() - started, 1)
        row["effective_model"] = getattr(result, "model", "") or ""
        row["out_tokens"] = _usage_out_tokens(getattr(result, "usage", None))
        raw_response = getattr(result, "raw_response", None)
        row["finish_reason"] = _finish_reason(raw_response)
        row["thinking_tokens"] = _thinking_tokens(raw_response)

        output = result.output
        if isinstance(output, output_type):
            row["verdict"] = "OK"
            row["detail"] = f"{len(output.model_dump_json())} B of valid JSON"
        elif isinstance(output, str):
            row["verdict"] = "STR-LEAK"
            row["detail"] = f"raw str, {len(output)} chars"
            row["raw"] = output
        else:
            row["verdict"] = "ERROR"
            row["detail"] = f"unexpected output type {type(output).__name__}"
    except TimeoutError:
        row["seconds"] = round(time.monotonic() - started, 1)
        row["verdict"] = "TIMEOUT"
        row["detail"] = f"exceeded {timeout:.0f}s"
    except InvokeError as exc:
        row["seconds"] = round(time.monotonic() - started, 1)
        row["verdict"] = "INVOKE-ERROR"
        # Classify on the full provider message; a provider that streams JSON
        # events (Codex) buries the real cause hundreds of characters in, so
        # truncating before classification would misfile it as a model failure.
        row["full_error"] = str(exc)
        row["detail"] = str(exc)[:200]
    except Exception as exc:
        row["seconds"] = round(time.monotonic() - started, 1)
        row["verdict"] = "ERROR"
        row["full_error"] = f"{type(exc).__name__}: {exc}"
        row["detail"] = f"{type(exc).__name__}: {str(exc)[:180]}"

    # A billing/entitlement/EOL error says nothing about the model's ability to
    # emit the schema — demote it so it cannot be misread as evidence.
    if row["verdict"] in ("INVOKE-ERROR", "ERROR") and is_unavailable(
        row.get("full_error") or row["detail"]
    ):
        row["verdict"] = "UNAVAIL"

    # Recover the raw provider text even when invoke() raised or recovered.
    captured = getattr(client, "_feat481_last_parse", None)
    if row["raw"] is None and captured:
        row["raw"] = captured.get("raw_text")
    if row["verdict"] not in ("OK", "SKIP", "UNAVAIL") and row["raw"]:
        row["fingerprint"] = fingerprint(row["raw"])
    return row


# --------------------------------------------------------------------------- #
# 7. Rendering
# --------------------------------------------------------------------------- #

_COLORS = {
    "OK": "\033[32m",
    "STR-LEAK": "\033[31m",
    "INVOKE-ERROR": "\033[31m",
    "TIMEOUT": "\033[33m",
    "ERROR": "\033[35m",
    "UNAVAIL": "\033[90m",
    "SKIP": "\033[90m",
}
_RESET = "\033[0m"

_SYMBOLS = {
    "OK": "PASS",
    "STR-LEAK": "FAIL",
    "INVOKE-ERROR": "FAIL",
    "TIMEOUT": "TIME",
    "ERROR": "ERR",
    "UNAVAIL": "n/a",
    "SKIP": "skip",
}

#: Verdicts that carry no information about a model's structured-output ability.
_NON_EVIDENCE = ("SKIP", "UNAVAIL")


def _color(text: str, verdict: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{_COLORS.get(verdict, '')}{text}{_RESET}"


def render_table(rows: list[dict[str, Any]], schemas: list[str], *, color: bool) -> str:
    """Render the matrix as an aligned terminal table.

    One row per model, one verdict column per schema, so "fails everything"
    and "fails only this schema" are distinguishable at a glance.

    Args:
        rows: All result rows.
        schemas: Schema names, in column order.
        color: Whether to emit ANSI colour.

    Returns:
        The rendered table.
    """
    by_model: dict[str, dict[str, list[dict[str, Any]]]] = {}
    order: list[str] = []
    for row in rows:
        if row["spec"] not in by_model:
            by_model[row["spec"]] = {}
            order.append(row["spec"])
        by_model[row["spec"]].setdefault(row["schema"], []).append(row)

    model_w = max([len(s) for s in order] + [len("MODEL")])
    eff_w = max([len(r.get("effective_model") or "-") for r in rows] + [len("EFFECTIVE MODEL")])
    cell_w = max(10, *(len(s) for s in schemas))

    head = f"  {'MODEL':<{model_w}}  {'EFFECTIVE MODEL':<{eff_w}}  "
    head += "  ".join(f"{s:<{cell_w}}" for s in schemas)
    lines = [head, "  " + "─" * (len(head) - 2)]

    for spec in order:
        cells = by_model[spec]
        first = next(iter(cells.values()))[0]
        effective = first.get("effective_model") or "-"
        # Flag a silent substitution: what ran is not what was asked for.
        requested = first.get("requested_model", "")
        if effective != "-" and requested not in ("(provider default)", "") and requested not in effective:
            effective = f"{effective} ⚠"
        line = f"  {spec:<{model_w}}  {effective:<{eff_w}}  "
        parts = []
        for schema in schemas:
            runs = cells.get(schema)
            if not runs:
                parts.append(f"{'-':<{cell_w}}")
                continue
            passes = sum(1 for r in runs if r["verdict"] == "OK")
            # The worst verdict wins the cell: one failure out of N is a failure
            # you have to explain, not an average you get to round away.
            verdict = "OK" if passes == len(runs) else next(
                r["verdict"] for r in runs if r["verdict"] != "OK"
            )
            label = _SYMBOLS.get(verdict, verdict)
            if len(runs) > 1:
                text = f"{label} {passes}/{len(runs)}"
            else:
                secs = f" {runs[0]['seconds']:.0f}s" if runs[0].get("seconds") else ""
                text = f"{label}{secs}"
            parts.append(_color(f"{text:<{cell_w}}", verdict, color))
        lines.append(line + "  ".join(parts))
    return "\n".join(lines)


def render_details(rows: list[dict[str, Any]]) -> str:
    """Render the per-cell detail block for every non-OK result."""
    failures = [r for r in rows if r["verdict"] not in ("OK",) + _NON_EVIDENCE]
    if not failures:
        return "  (no failures)"
    lines = []
    for row in failures:
        lines.append(f"  {row['spec']} [{row['schema']}] → {row['verdict']}")
        lines.append(f"      {row['detail']}")
        if row.get("finish_reason"):
            budget = f"      finish_reason={row['finish_reason']}"
            if row.get("out_tokens"):
                budget += f" · output_tokens={row['out_tokens']}"
            if row.get("thinking_tokens"):
                budget += f" · thinking_tokens={row['thinking_tokens']}"
            lines.append(budget)
        fp = row.get("fingerprint")
        if fp:
            lines.append(
                f"      raw: {fp['chars']} chars · json_valid={fp['json_valid']} "
                f"· truncated={fp['truncated']} · max_sentence_repeat={fp['max_repeat']} "
                f"· mode={fp['mode']}"
            )
    return "\n".join(lines)


def render_markdown(rows: list[dict[str, Any]], schemas: list[str], meta: dict[str, Any]) -> str:
    """Render the full report as Markdown for ``artifacts/logs/``."""
    out = [
        "# FEAT-481 — live structured-output matrix",
        "",
        f"- **Run:** {meta['timestamp']}",
        (f"- **Meeting fixture:** `{meta['fixture']}` ({meta['summary_chars']} chars,"
         f" transcript={'yes' if meta['transcript'] else 'no'})"),
        (f"- **max_tokens:** {meta['max_tokens']} · **temperature:** 0.0"
         f" · **model pinned:** {meta['pin_model']}"),
        "",
        "| Model (requested) | Effective model | " + " | ".join(schemas) + " | Notes |",
        "|---|---|" + "---|" * len(schemas) + "---|",
    ]
    by_model: dict[str, dict[str, list[dict[str, Any]]]] = {}
    order: list[str] = []
    for row in rows:
        by_model.setdefault(row["spec"], {})
        if row["spec"] not in order:
            order.append(row["spec"])
        by_model[row["spec"]].setdefault(row["schema"], []).append(row)

    for spec in order:
        cells = by_model[spec]
        first = next(iter(cells.values()))[0]
        effective = first.get("effective_model") or "—"
        requested = first.get("requested_model", "")
        note = ""
        if effective != "—" and requested not in ("(provider default)", "") and requested not in effective:
            note = f"⚠️ ran on `{effective}`, not the requested model"
        verdicts = []
        for schema in schemas:
            runs = cells.get(schema)
            if not runs:
                verdicts.append("—")
                continue
            passes = sum(1 for r in runs if r["verdict"] == "OK")
            verdict = "OK" if passes == len(runs) else next(
                r["verdict"] for r in runs if r["verdict"] != "OK"
            )
            suffix = f" {passes}/{len(runs)}" if len(runs) > 1 else ""
            verdicts.append(f"`{verdict}`{suffix}")
        out.append(f"| `{spec}` | `{effective}` | " + " | ".join(verdicts) + f" | {note} |")

    out += ["", "## Failure detail", ""]
    for row in rows:
        if row["verdict"] in ("OK",) + _NON_EVIDENCE:
            continue
        out.append(f"### `{row['spec']}` — {row['schema']} → **{row['verdict']}**")
        out.append("")
        out.append(f"- {row['detail']}")
        if row.get("finish_reason"):
            out.append(
                f"- `finish_reason={row['finish_reason']}`"
                + (f" · output tokens: {row['out_tokens']}" if row.get("out_tokens") else "")
                + (f" · thinking tokens: {row['thinking_tokens']}" if row.get("thinking_tokens") else "")
            )
        fp = row.get("fingerprint")
        if fp:
            out.append(
                f"- raw output: {fp['chars']} chars · json_valid={fp['json_valid']} ·"
                f" truncated={fp['truncated']} · max sentence repeat={fp['max_repeat']} ·"
                f" **mode={fp['mode']}**"
            )
        out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# 8. Entry point
# --------------------------------------------------------------------------- #


def load_meeting(meeting_dir: Optional[str], fixture: Path) -> dict[str, Any]:
    """Load the meeting under test.

    Args:
        meeting_dir: A real Fireflies bundle directory (``summary.md`` required,
            ``transcript.md`` / ``metadata.json`` optional). ``None`` uses the
            committed fixture.
        fixture: Path to the committed large-summary fixture.

    Returns:
        A meeting dict with title, date, summary and optional transcript.
    """
    if not meeting_dir:
        return {
            "fireflies_id": "fixture-large-0001",
            "title": "FieldSync / Verizon Launch — Weekly Project Sync",
            "meeting_date": "2026-08-27",
            "summary_text": fixture.read_text(encoding="utf-8"),
            "transcript_text": None,
            "source": str(fixture),
        }
    directory = Path(meeting_dir)
    meta_file = directory / "metadata.json"
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
    summary = directory / "summary.md"
    transcript = directory / "transcript.md"
    return {
        "fireflies_id": meta.get("fireflies_id") or meta.get("id") or directory.name,
        "title": meta.get("title") or directory.name,
        "meeting_date": str(meta.get("meeting_date") or meta.get("date") or "1970-01-01"),
        "summary_text": summary.read_text(encoding="utf-8") if summary.exists() else "",
        "transcript_text": transcript.read_text(encoding="utf-8") if transcript.exists() else None,
        "source": str(directory),
    }


def resolve_models(args: argparse.Namespace) -> list[str]:
    """Resolve ``--models`` / ``--preset`` into a de-duplicated spec list."""
    specs: list[str] = []
    if args.preset:
        for name in args.preset.split(","):
            key = name.strip()
            if key not in PRESETS:
                raise SystemExit(f"unknown preset '{key}'. Available: {', '.join(sorted(PRESETS))}")
            specs += PRESETS[key]
    if args.models:
        specs += [s.strip() for s in args.models.split(",") if s.strip()]
    if not specs:
        specs = PRESETS["baseline"]
    seen: set[str] = set()
    return [s for s in specs if not (s in seen or seen.add(s))]


async def main() -> int:
    """Run the matrix and write the report."""
    parser = argparse.ArgumentParser(
        description="FEAT-481 live structured-output matrix across ai-parrot LLM clients.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--models", default="", help="comma-separated provider:model specs")
    parser.add_argument("--preset", default="", help=f"comma-separated presets: {', '.join(sorted(PRESETS))}")
    parser.add_argument("--schemas", default="page",
                        help=f"comma-separated schemas: {', '.join(SCHEMAS)} (default: page)")
    parser.add_argument("--meeting-dir", default=None, help="a real Fireflies bundle directory")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE), help="large-summary fixture path")
    parser.add_argument("--transcript", action="store_true", help="include the transcript in the prompt")
    parser.add_argument("--max-tokens", type=int, default=4096, help="max output tokens (invoke default: 4096)")
    parser.add_argument("--timeout", type=float, default=300.0, help="per-cell timeout in seconds")
    parser.add_argument("--concurrency", type=int, default=4, help="cells in flight at once")
    parser.add_argument("--repeat", type=int, default=1,
                        help="run each cell N times; the table then shows passes/N. "
                             "temperature=0 is not a determinism guarantee — several models "
                             "flip between PASS and FAIL across identical calls, and a "
                             "single-shot matrix cannot tell a hard failure from a flaky one")
    parser.add_argument("--pin-model", dest="pin_model", action="store_true", default=True,
                        help="pass model= to invoke() so the requested model runs (default)")
    parser.add_argument("--no-pin-model", dest="pin_model", action="store_false",
                        help="omit model=, reproducing the _lightweight_model fallback")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="where to write the report")
    parser.add_argument("--save-raw", action="store_true", help="save each failing raw response to out-dir/raw/")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument("--list-models", action="store_true", help="print the resolved matrix and exit")
    args = parser.parse_args()

    specs = resolve_models(args)
    schemas = [s.strip() for s in args.schemas.split(",") if s.strip()]
    for schema in schemas:
        if schema not in SCHEMAS:
            raise SystemExit(f"unknown schema '{schema}'. Available: {', '.join(SCHEMAS)}")

    if args.list_models:
        for spec in specs:
            reason = missing_credential(spec.split(":", 1)[0])
            print(f"  {spec:<44} {'SKIP — ' + reason if reason else 'ready'}")
        return 0

    if not os.environ.get("PARROT_MATRIX_LIVE"):
        print(
            "This harness makes real, billable LLM calls against "
            f"{len(specs)} model(s) × {len(schemas)} schema(s) × {args.repeat} run(s) = "
            f"{len(specs) * len(schemas) * args.repeat} calls.\n"
            "Set PARROT_MATRIX_LIVE=1 to run it.",
            file=sys.stderr,
        )
        return 2

    install_parse_capture()

    meeting = load_meeting(args.meeting_dir, Path(args.fixture))
    transcript = args.transcript and bool(meeting["transcript_text"])
    prompt = build_prompt(meeting, transcript=transcript)

    print("\nFEAT-481 live structured-output matrix")
    print(f"  meeting  : {meeting['title']}")
    print(f"  source   : {meeting['source']}")
    print(f"  summary  : {len(meeting['summary_text'] or '')} chars"
          f" · transcript: {'included' if transcript else 'omitted'}")
    print(f"  settings : max_tokens={args.max_tokens} temperature=0.0"
          f" model_pinned={args.pin_model} concurrency={args.concurrency}")
    print(f"  matrix   : {len(specs)} model(s) × {len(schemas)} schema(s)"
          f" × {args.repeat} run(s) = {len(specs) * len(schemas) * args.repeat} live call(s)\n")

    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    rows: list[dict[str, Any]] = []

    async def run_cell(spec: str, schema: str, attempt: int) -> None:
        async with semaphore:
            row = await probe_cell(
                spec, schema, prompt,
                pin_model=args.pin_model,
                max_tokens=args.max_tokens,
                timeout=args.timeout,
            )
        row["attempt"] = attempt
        rows.append(row)
        label = _SYMBOLS.get(row["verdict"], row["verdict"])
        run_tag = f" #{attempt}" if args.repeat > 1 else ""
        print(f"  {_color(label, row['verdict'], not args.no_color)}  "
              f"{spec} [{schema}]{run_tag} → {row['effective_model'] or '-'}  {row['detail'][:90]}")

    await asyncio.gather(*(
        run_cell(spec, schema, attempt)
        for spec in specs for schema in schemas for attempt in range(1, args.repeat + 1)
    ))

    # Stable ordering for the table: matrix order, not completion order.
    index = {(spec, schema): i for i, (spec, schema) in
             enumerate((s, sc) for s in specs for sc in schemas)}
    rows.sort(key=lambda r: (index[(r["spec"], r["schema"])], r.get("attempt", 1)))

    print("\n==== MATRIX ====\n")
    print(render_table(rows, schemas, color=not args.no_color))
    print("\n==== FAILURE DETAIL ====\n")
    print(render_details(rows))

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    print("\n==== TOTALS ====")
    print("  " + " · ".join(f"{v}={n}" for v, n in sorted(counts.items())))

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta = {
        "timestamp": stamp,
        "repeat": args.repeat,
        "fixture": meeting["source"],
        "summary_chars": len(meeting["summary_text"] or ""),
        "transcript": transcript,
        "max_tokens": args.max_tokens,
        "pin_model": args.pin_model,
    }

    json_path = out_dir / f"matrix-{stamp}.json"
    json_path.write_text(json.dumps(
        {"meta": meta, "rows": [{k: v for k, v in r.items() if k != "raw"} for r in rows]},
        indent=2,
    ))
    md_path = out_dir / f"matrix-{stamp}.md"
    md_path.write_text(render_markdown(rows, schemas, meta))
    print(f"\n  report: {md_path}")
    print(f"  data  : {json_path}")

    if args.save_raw:
        raw_dir = out_dir / "raw"
        raw_dir.mkdir(exist_ok=True)
        for row in rows:
            if row["verdict"] in ("OK",) + _NON_EVIDENCE or not row.get("raw"):
                continue
            attempt = f"__run{row.get('attempt', 1)}" if args.repeat > 1 else ""
            name = (f"{row['spec'].replace(':', '_').replace('/', '_')}"
                    f"__{row['schema']}{attempt}__{stamp}.txt")
            (raw_dir / name).write_text(row["raw"])
        print(f"  raw   : {raw_dir}")

    # Non-zero when something actually failed (SKIP is not a failure).
    return 1 if any(r["verdict"] in ("STR-LEAK", "INVOKE-ERROR", "ERROR", "TIMEOUT") for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
