"""Unit tests for GenAI SemConv attribute builders.

FEAT-177 TASK-1229.
"""

from __future__ import annotations

import pytest

from parrot.core.events.lifecycle.events import (
    AfterClientCallEvent,
    BeforeClientCallEvent,
    BeforeInvokeEvent,
)
from navigator_eventbus.lifecycle.trace import TraceContext
from parrot.observability.attributes import (
    PROVIDER_TO_GEN_AI_SYSTEM,
    _reset_warned_unknown_for_tests,
    build_after_client_attrs,
    build_before_client_attrs,
    build_before_invoke_attrs,
    resolve_gen_ai_system,
)


@pytest.fixture(autouse=True)
def _reset_warned_unknown():
    """Reset the module-level _warned_unknown set before each test for isolation."""
    _reset_warned_unknown_for_tests()
    yield
    _reset_warned_unknown_for_tests()


# ---------------------------------------------------------------------------
# Provider mapping tests
# ---------------------------------------------------------------------------


def test_provider_mapping_covers_all_known_clients() -> None:
    """All providers documented in spec §2 must appear in the mapping."""
    expected = {
        "openai", "anthropic", "claude-agent", "google", "gemini-live",
        "groq", "grok", "nvidia", "huggingface", "gemma4",
        "anthropic-bedrock", "bedrock",  # FEAT-232: Claude via AWS Bedrock
    }
    assert expected.issubset(PROVIDER_TO_GEN_AI_SYSTEM.keys())


def test_resolve_gen_ai_system_known() -> None:
    """Known providers map to their documented gen_ai.system values."""
    assert resolve_gen_ai_system("openai") == "openai"
    assert resolve_gen_ai_system("anthropic") == "anthropic"
    assert resolve_gen_ai_system("claude-agent") == "anthropic"
    # FEAT-232: Bedrock-served Claude maps to OpenLIT's aws.bedrock provider.
    assert resolve_gen_ai_system("anthropic-bedrock") == "aws.bedrock"
    assert resolve_gen_ai_system("bedrock") == "aws.bedrock"
    assert resolve_gen_ai_system("google") == "gemini"
    assert resolve_gen_ai_system("gemini-live") == "gemini"
    assert resolve_gen_ai_system("groq") == "groq"
    assert resolve_gen_ai_system("grok") == "xai"
    assert resolve_gen_ai_system("nvidia") == "nvidia"
    assert resolve_gen_ai_system("huggingface") == "huggingface"
    assert resolve_gen_ai_system("gemma4") == "huggingface"


def test_resolve_gen_ai_system_unknown_falls_back_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Unknown provider falls back to raw value and warns exactly once."""
    import logging
    with caplog.at_level(logging.WARNING):
        result1 = resolve_gen_ai_system("brand-new-llm")
        result2 = resolve_gen_ai_system("brand-new-llm")

    assert result1 == "brand-new-llm"
    assert result2 == "brand-new-llm"
    # WARN emitted at most once (module-level dedup set)
    warns = [r for r in caplog.records if "brand-new-llm" in r.message]
    assert len(warns) <= 1


# ---------------------------------------------------------------------------
# BeforeClientCallEvent builder
# ---------------------------------------------------------------------------


def test_before_client_omits_none_temperature() -> None:
    """temperature=None must not appear in the attribute dict."""
    e = BeforeClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        temperature=None,
    )
    attrs = build_before_client_attrs(e)
    assert "gen_ai.request.temperature" not in attrs
    assert attrs["gen_ai.system"] == "openai"
    # New GenAI SemConv key — current OpenLIT reads the provider from this, not
    # from the legacy gen_ai.system. Both must be present and agree.
    assert attrs["gen_ai.provider.name"] == "openai"
    assert attrs["gen_ai.request.model"] == "gpt-4o"


def test_before_client_includes_temperature_when_set() -> None:
    """temperature set on the event must appear in attrs."""
    e = BeforeClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="anthropic",
        model="claude-3-5-sonnet",
        temperature=0.7,
    )
    attrs = build_before_client_attrs(e)
    assert attrs["gen_ai.request.temperature"] == 0.7


def test_before_client_excludes_pii() -> None:
    """No PII (user_id, session_id, question) in builder output."""
    e = BeforeClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
    )
    attrs = build_before_client_attrs(e)
    for key in attrs:
        assert key not in {"user_id", "session_id", "question"}


# ---------------------------------------------------------------------------
# AfterClientCallEvent builder
# ---------------------------------------------------------------------------


def test_after_client_with_cost() -> None:
    """cost_usd param must appear as parrot.cost.usd when provided."""
    e = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="anthropic",
        model="claude-3-5-sonnet",
        duration_ms=1234.5,
        input_tokens=100,
        output_tokens=50,
        finish_reason="end_turn",
    )
    attrs = build_after_client_attrs(e, cost_usd=0.00042)
    assert attrs["gen_ai.system"] == "anthropic"
    assert attrs["gen_ai.provider.name"] == "anthropic"  # new SemConv key (OpenLIT)
    assert attrs["gen_ai.usage.input_tokens"] == 100
    assert attrs["gen_ai.usage.output_tokens"] == 50
    assert attrs["gen_ai.response.finish_reason"] == "end_turn"
    assert attrs["parrot.cost.usd"] == 0.00042


def test_after_client_no_cost_when_none() -> None:
    """cost_usd=None must not add parrot.cost.usd key."""
    e = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        duration_ms=100.0,
    )
    attrs = build_after_client_attrs(e, cost_usd=None)
    assert "parrot.cost.usd" not in attrs


# ---------------------------------------------------------------------------
# BeforeInvokeEvent builder
# ---------------------------------------------------------------------------


def test_before_invoke_excludes_pii() -> None:
    """PII fields (question, user_id, session_id) must not appear in attrs."""
    e = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="bot",
        method="ask",
        question="my private question",
        user_id="u-123",
        session_id="s-456",
    )
    attrs = build_before_invoke_attrs(e)
    attrs_str = str(attrs)
    assert "question" not in attrs_str
    assert "u-123" not in attrs_str
    assert "s-456" not in attrs_str
    assert "my private question" not in attrs_str


def test_before_invoke_contains_agent_name_and_method() -> None:
    """Agent name and method must be present."""
    e = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="my-bot",
        method="ask",
    )
    attrs = build_before_invoke_attrs(e)
    assert attrs["parrot.agent.name"] == "my-bot"
    assert attrs["parrot.invoke.method"] == "ask"
