"""LLM Client lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: before/after/failed LLM API calls and per-chunk streaming events.

Note: ClientStreamChunkEvent is high-frequency and NEVER dual-emits to
EventBus by default. It must be explicitly opted in via forward_to_bus=True
on the subscription.
"""
from dataclasses import dataclass
from typing import Optional

from parrot.core.events.lifecycle.base import LifecycleEvent


@dataclass(frozen=True)
class BeforeClientCallEvent(LifecycleEvent):
    """Emitted just before an LLM API call is made.

    Attributes:
        client_name: Provider identifier (``"anthropic"``, ``"openai"``, etc.).
        model: Model name/identifier being called.
        temperature: Sampling temperature (None if not configured).
        system_prompt_hash: SHA-256 hex of the system prompt. NEVER the prompt
            itself — this preserves privacy while enabling correlation.
        has_tools: True if tool definitions were included in the request.
    """

    client_name: str = ""
    model: str = ""
    temperature: Optional[float] = None
    system_prompt_hash: str = ""     # SHA-256, never the prompt itself
    has_tools: bool = False


@dataclass(frozen=True)
class AfterClientCallEvent(LifecycleEvent):
    """Emitted after a successful LLM API call completes.

    NOT emitted when the call fails (ClientCallFailedEvent is used instead).

    Attributes:
        client_name: Provider identifier.
        model: Model name/identifier.
        duration_ms: Wall-clock time in milliseconds.
        input_tokens: Input token count (provider-dependent; may be None).
        output_tokens: Output token count (provider-dependent; may be None).
        finish_reason: Stop reason returned by the provider (e.g., ``"stop"``,
            ``"max_tokens"``). May be None.
    """

    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None


@dataclass(frozen=True)
class ClientCallFailedEvent(LifecycleEvent):
    """Emitted when an LLM API call raises an exception.

    AfterClientCallEvent is NOT emitted when this fires.

    Attributes:
        client_name: Provider identifier.
        model: Model name/identifier.
        duration_ms: Wall-clock time in milliseconds until failure.
        error_type: ``type(exc).__name__`` of the exception.
        error_message: String representation of the exception.
    """

    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""


@dataclass(frozen=True)
class ClientStreamChunkEvent(LifecycleEvent):
    """Emitted for each chunk received during a streaming response.

    HIGH-FREQUENCY event. This event NEVER dual-emits to EventBus by default,
    even if a subscription has forward_to_bus=True — subscribers must
    explicitly request bus forwarding.

    Contains chunk metadata only (index + size), NEVER the chunk text,
    to avoid PII leakage and keep per-chunk overhead minimal.

    Attributes:
        client_name: Provider identifier.
        model: Model name/identifier.
        chunk_index: Zero-based index of this chunk in the stream.
        chunk_size_bytes: UTF-8 encoded byte length of this chunk.
    """

    client_name: str = ""
    model: str = ""
    chunk_index: int = 0
    chunk_size_bytes: int = 0
