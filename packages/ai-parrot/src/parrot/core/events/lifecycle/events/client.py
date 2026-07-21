"""LLM Client lifecycle events.

FEAT-176 — Lifecycle Events System.

Covers: before/after/failed LLM API calls and per-chunk streaming events.

Note: ClientStreamChunkEvent is high-frequency and NEVER dual-emits to
EventBus by default. It must be explicitly opted in via forward_to_bus=True
on the subscription.
"""
from dataclasses import dataclass
from typing import Literal, Optional

from navigator_eventbus.lifecycle.base import LifecycleEvent


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
        agent_name: ``AbstractBot.name`` of the invoking agent, or ``None``
            when called outside a bot invocation scope.  Set by the client
            from the ``current_agent_name`` ContextVar (FEAT-228).
            NEVER contains PII (user_id, session_id, prompt content).
    """

    client_name: str = ""
    model: str = ""
    temperature: Optional[float] = None
    system_prompt_hash: str = ""     # SHA-256, never the prompt itself
    has_tools: bool = False
    agent_name: Optional[str] = None   # FEAT-228: invoking agent's self.name


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
        agent_name: ``AbstractBot.name`` of the invoking agent, or ``None``
            when called outside a bot invocation scope.  Set by the client
            from the ``current_agent_name`` ContextVar (FEAT-228).
            NEVER contains PII (user_id, session_id, prompt content).
    """

    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    finish_reason: Optional[str] = None
    agent_name: Optional[str] = None   # FEAT-228: invoking agent's self.name


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
        agent_name: ``AbstractBot.name`` of the invoking agent, or ``None``
            when called outside a bot invocation scope.  Set by the client
            from the ``current_agent_name`` ContextVar (FEAT-228).
            NEVER contains PII (user_id, session_id, prompt content).
    """

    client_name: str = ""
    model: str = ""
    duration_ms: float = 0.0
    error_type: str = ""
    error_message: str = ""
    agent_name: Optional[str] = None   # FEAT-228: invoking agent's self.name


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


# ── FEAT-181: Prompt Caching Lifecycle Events ─────────────────────────────

@dataclass(frozen=True)
class PromptCacheAppliedEvent(LifecycleEvent):
    """Emitted when prompt caching is applied to an LLM call.

    FEAT-181 — Provider-Agnostic Prompt Caching.

    Attributes:
        client_name: Provider identifier (``"anthropic"``, ``"openai"``, etc.).
        model: Model name/identifier being called.
        blocks_marked: Number of ``cache_control`` blocks applied to the
            system prompt. For Anthropic: number of cacheable blocks (≤4).
            For OpenAI/Gemini: 0 (caching is implicit or resource-based).
        est_tokens: Estimated cacheable token count (rough 4-chars-per-token
            estimate). Used for observability only.
        segment_hashes: SHA-256 hashes of each cacheable segment text.
            NEVER the raw segment content — privacy-safe.
            Uses ``tuple`` for immutability; ``to_dict()`` converts to list.
    """

    client_name: str = ""
    model: str = ""
    blocks_marked: int = 0
    est_tokens: int = 0
    # tuple is immutable and JSON-serializable (to_dict converts to list)
    segment_hashes: tuple = ()


@dataclass(frozen=True)
class PromptCacheSkippedEvent(LifecycleEvent):
    """Emitted when prompt caching is skipped.

    FEAT-181 — Provider-Agnostic Prompt Caching.

    Attributes:
        client_name: Provider identifier.
        model: Model name/identifier.
        reason: Why caching was skipped. One of:

            - ``"below_threshold"`` — cacheable token count < ``_min_cache_tokens``.
            - ``"provider_unsupported"`` — provider does not support caching.
            - ``"feature_off"`` — ``prompt_caching=False`` at the bot level.
            - ``"no_segments"`` — no segments were passed to ``_apply_cache_hints``.
    """

    client_name: str = ""
    model: str = ""
    reason: Literal[
        "below_threshold", "provider_unsupported", "feature_off", "no_segments", ""
    ] = ""
