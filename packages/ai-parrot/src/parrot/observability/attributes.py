"""GenAI SemConv attribute builders and provider mapping.

FEAT-177 TASK-1229 — pure functions that map FEAT-176 lifecycle events to
OTel attribute dicts. This is the single point of update when OTel SemConv
renames an attribute or a new provider is added.

Spec §2 (Event → Span mapping) and §2 (Provider → gen_ai.system mapping).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    AfterInvokeEvent,
    AfterToolCallEvent,
    BeforeClientCallEvent,
    BeforeInvokeEvent,
    BeforeToolCallEvent,
    ClientCallFailedEvent,
    InvokeFailedEvent,
    MessageAddedEvent,
    ToolCallFailedEvent,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider → gen_ai.system mapping (spec §2 table)
# ---------------------------------------------------------------------------

PROVIDER_TO_GEN_AI_SYSTEM: dict[str, str] = {
    "openai": "openai",
    "anthropic": "anthropic",
    "claude-agent": "anthropic",    # routes through Anthropic
    # FEAT-232: Claude served through AWS Bedrock. OpenLIT's canonical provider
    # value for Bedrock is ``aws.bedrock`` (GEN_AI_SYSTEM_AWS_BEDROCK), distinct
    # from the direct Anthropic API. The Bedrock backend must emit one of these
    # client_names (not the bare "anthropic") for the trace to be attributed to
    # Bedrock in OpenLIT. The "aws" workspace backend stays "anthropic" — it is
    # still the Anthropic API, only credentialed via an AWS workspace.
    "anthropic-bedrock": "aws.bedrock",
    "bedrock": "aws.bedrock",       # alias for the LLMFactory "bedrock:" route key
    "google": "gemini",             # default; override per route when Vertex
    "gemini-live": "gemini",
    "groq": "groq",
    "grok": "xai",                  # no OTel-standard value; custom
    "nvidia": "nvidia",             # custom — no OTel-standard
    "huggingface": "huggingface",   # custom
    "gemma4": "huggingface",        # Gemma is HF-hosted
}

# Track which unknown client_names have already been warned about (module-level).
_warned_unknown: set[str] = set()


def _reset_warned_unknown_for_tests() -> None:
    """Clear the module-level _warned_unknown deduplication set.

    NEVER call in production. For test isolation only. Allows tests to assert
    that a warning is emitted even when the same unknown provider was seen in a
    previous test.
    """
    _warned_unknown.clear()


def resolve_gen_ai_system(client_name: str) -> str:
    """Resolve a ``client_name`` emitted on ``BeforeClientCallEvent`` to the
    corresponding ``gen_ai.system`` OTel attribute value.

    Args:
        client_name: Value from ``BeforeClientCallEvent.client_name``.

    Returns:
        The ``gen_ai.system`` value; falls back to the raw ``client_name``
        and logs a one-time WARN for unknown providers.
    """
    if client_name in PROVIDER_TO_GEN_AI_SYSTEM:
        return PROVIDER_TO_GEN_AI_SYSTEM[client_name]
    if client_name not in _warned_unknown:
        _warned_unknown.add(client_name)
        logger.warning(
            "resolve_gen_ai_system: unknown client_name=%r — "
            "falling back to raw value. Add to PROVIDER_TO_GEN_AI_SYSTEM if permanent.",
            client_name,
        )
    return client_name


# ---------------------------------------------------------------------------
# Attribute builders — pure functions; return dict[str, Any]
# Never include None values; never include PII (user_id, session_id, question).
# ---------------------------------------------------------------------------


def build_before_invoke_attrs(event: BeforeInvokeEvent) -> dict[str, Any]:
    """Build OTel attributes for ``BeforeInvokeEvent`` (agent root span start).

    Args:
        event: The ``BeforeInvokeEvent`` instance.

    Returns:
        Dict of OTel attribute key-value pairs. Never contains PII.
    """
    return {
        "parrot.agent.name": event.agent_name,
        "parrot.invoke.method": event.method,
    }


def build_after_invoke_attrs(event: AfterInvokeEvent) -> dict[str, Any]:
    """Build OTel attributes for ``AfterInvokeEvent`` (agent root span end).

    Args:
        event: The ``AfterInvokeEvent`` instance.

    Returns:
        Dict of OTel attribute key-value pairs.
    """
    attrs: dict[str, Any] = {
        "parrot.agent.name": event.agent_name,
        "parrot.invoke.method": event.method,
        "parrot.invoke.duration_ms": event.duration_ms,
    }
    if event.input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = event.input_tokens
    if event.output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = event.output_tokens
    return attrs


def build_before_client_attrs(event: BeforeClientCallEvent) -> dict[str, Any]:
    """Build OTel attributes for ``BeforeClientCallEvent`` (client child span start).

    Follows GenAI SemConv. Omits any field that is None.

    Args:
        event: The ``BeforeClientCallEvent`` instance.

    Returns:
        Dict of GenAI SemConv + parrot-specific OTel attribute key-value pairs.
    """
    system = resolve_gen_ai_system(event.client_name)
    attrs: dict[str, Any] = {
        # ``gen_ai.system`` is the legacy GenAI SemConv key; the newer convention
        # (adopted by current OpenLIT, which dropped ``gen_ai.system`` entirely)
        # reads the provider from ``gen_ai.provider.name``. Emit BOTH so the
        # provider is populated regardless of which convention the collector /
        # backend follows — otherwise OpenLIT shows ``provider=''``.
        "gen_ai.system": system,
        "gen_ai.provider.name": system,
        "gen_ai.request.model": event.model,
        # Custom extension — not part of OTel GenAI SemConv stable spec (May 2025)
        "gen_ai.request.has_tools": event.has_tools,
    }
    if event.temperature is not None:
        attrs["gen_ai.request.temperature"] = event.temperature
    if event.system_prompt_hash:
        attrs["parrot.system_prompt_hash"] = event.system_prompt_hash
    if event.agent_name:  # FEAT-228: omit when None/empty
        attrs["parrot.agent.name"] = event.agent_name
    return attrs


def build_after_client_attrs(
    event: AfterClientCallEvent,
    *,
    cost_usd: Optional[float] = None,
) -> dict[str, Any]:
    """Build OTel attributes for ``AfterClientCallEvent`` (client child span end).

    Args:
        event: The ``AfterClientCallEvent`` instance.
        cost_usd: Optional computed cost in USD from ``CostCalculator``.
            Omitted from attrs when ``None``.

    Returns:
        Dict of GenAI SemConv + parrot-specific OTel attribute key-value pairs.
    """
    system = resolve_gen_ai_system(event.client_name)
    attrs: dict[str, Any] = {
        "gen_ai.system": system,
        "gen_ai.provider.name": system,  # new SemConv key — current OpenLIT reads this
        "gen_ai.response.model": event.model,
        "parrot.client.duration_ms": event.duration_ms,
    }
    if event.input_tokens is not None:
        attrs["gen_ai.usage.input_tokens"] = event.input_tokens
    if event.output_tokens is not None:
        attrs["gen_ai.usage.output_tokens"] = event.output_tokens
    if event.finish_reason is not None:
        attrs["gen_ai.response.finish_reason"] = event.finish_reason
    if cost_usd is not None:
        attrs["parrot.cost.usd"] = cost_usd
    if event.agent_name:  # FEAT-228: omit when None/empty
        attrs["parrot.agent.name"] = event.agent_name
    return attrs


def build_client_failed_attrs(event: ClientCallFailedEvent) -> dict[str, Any]:
    """Build OTel attributes for ``ClientCallFailedEvent`` (client error span end).

    Args:
        event: The ``ClientCallFailedEvent`` instance.

    Returns:
        Dict of OTel error + GenAI SemConv attribute key-value pairs.
    """
    system = resolve_gen_ai_system(event.client_name)
    attrs: dict[str, Any] = {
        "gen_ai.system": system,
        "gen_ai.provider.name": system,  # new SemConv key — current OpenLIT reads this
        "gen_ai.response.model": event.model,
        "parrot.client.duration_ms": event.duration_ms,
        "error.type": event.error_type,
        "error.message": event.error_message,
    }
    if event.agent_name:  # FEAT-228: omit when None/empty
        attrs["parrot.agent.name"] = event.agent_name
    return attrs


def build_before_tool_attrs(event: BeforeToolCallEvent) -> dict[str, Any]:
    """Build OTel attributes for ``BeforeToolCallEvent`` (tool child span start).

    Args:
        event: The ``BeforeToolCallEvent`` instance.

    Returns:
        Dict of parrot-specific OTel attribute key-value pairs.
    """
    return {
        "parrot.tool.name": event.tool_name,
        "parrot.tool.class": event.tool_class,
    }


def build_after_tool_attrs(event: AfterToolCallEvent) -> dict[str, Any]:
    """Build OTel attributes for ``AfterToolCallEvent`` (tool child span end).

    Args:
        event: The ``AfterToolCallEvent`` instance.

    Returns:
        Dict of parrot-specific OTel attribute key-value pairs.
    """
    return {
        "parrot.tool.name": event.tool_name,
        "parrot.tool.duration_ms": event.duration_ms,
        "parrot.tool.result.status": event.result_status,
        "parrot.tool.result.size_bytes": event.result_size_bytes,
    }


def build_tool_failed_attrs(event: ToolCallFailedEvent) -> dict[str, Any]:
    """Build OTel attributes for ``ToolCallFailedEvent`` (tool error span end).

    Args:
        event: The ``ToolCallFailedEvent`` instance.

    Returns:
        Dict of parrot-specific + OTel error attribute key-value pairs.
    """
    return {
        "parrot.tool.name": event.tool_name,
        "parrot.tool.duration_ms": event.duration_ms,
        "error.type": event.error_type,
        "error.message": event.error_message,
    }


def build_invoke_failed_attrs(event: InvokeFailedEvent) -> dict[str, Any]:
    """Build OTel attributes for ``InvokeFailedEvent`` (agent root span error end).

    Args:
        event: The ``InvokeFailedEvent`` instance.

    Returns:
        Dict of parrot-specific + OTel error attribute key-value pairs.
    """
    return {
        "parrot.agent.name": event.agent_name,
        "parrot.invoke.method": event.method,
        "parrot.invoke.duration_ms": event.duration_ms,
        "error.type": event.error_type,
        "error.message": event.error_message,
    }


def build_message_event_attrs(event: MessageAddedEvent) -> dict[str, Any]:
    """Build OTel span-event attributes for ``MessageAddedEvent``.

    These are attached as span *events* (not spans) to the active invoke span.

    Args:
        event: The ``MessageAddedEvent`` instance.

    Returns:
        Dict of parrot-specific OTel attribute key-value pairs.
    """
    return {
        "parrot.message.role": event.role,
        "parrot.message.content_length": event.content_length,
        "parrot.message.has_tool_calls": event.has_tool_calls,
    }
