"""Unit tests for GenAI SemConv attribute builders.

FEAT-177 TASK-1229.
"""

from __future__ import annotations

from pathlib import Path

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
        "openai",
        "anthropic",
        "claude-agent",
        "google",
        "gemini-live",
        "groq",
        "grok",
        "nvidia",
        "huggingface",
        "gemma4",
        "anthropic-bedrock",
        "bedrock",  # FEAT-232: Claude via AWS Bedrock
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


def test_resolve_gen_ai_system_dispatched_coding_agents() -> None:
    """dev-loop/dev-flow dispatchers emit their BACKEND id, not a client_name.

    ``ClaudeCodeDispatcher._emit_usage_event`` emits ``client_name="claude-code"``
    (and the Codex dispatcher ``"openai-codex"``) for out-of-process seats, which
    warned as unknown providers and attributed their traces to a non-SemConv
    value.
    """
    assert resolve_gen_ai_system("claude-code") == "anthropic"
    assert resolve_gen_ai_system("openai-codex") == "openai"


def test_resolve_gen_ai_system_bedrock_routes() -> None:
    """Every Bedrock-hosted route shares Bedrock's canonical system value."""
    assert resolve_gen_ai_system("nova") == "aws.bedrock"
    assert resolve_gen_ai_system("bedrock-mantle") == "aws.bedrock"
    assert resolve_gen_ai_system("bedrock-converse") == "aws.bedrock"


def test_every_shipped_client_name_is_mapped() -> None:
    """No first-party client may emit an unmapped ``client_name``.

    The provider map drifted behind the clients package (13 shipped
    ``client_name`` values were missing, so each one logged an unknown-provider
    WARN on its first call). This walks the class attribute rather than a
    hand-kept list, so a new client that forgets the mapping fails here.
    """
    import importlib
    import pkgutil

    import parrot.clients as clients_pkg

    seen: set[str] = set()
    for mod in pkgutil.iter_modules(clients_pkg.__path__):
        try:
            module = importlib.import_module(f"parrot.clients.{mod.name}")
        except Exception:  # noqa: BLE001, S112 - optional provider SDK absent
            continue
        for obj in vars(module).values():
            name = getattr(obj, "client_name", None)
            if isinstance(name, str) and name and isinstance(obj, type):
                seen.add(name)
    unmapped = sorted(n for n in seen if n not in PROVIDER_TO_GEN_AI_SYSTEM)
    assert not unmapped, f"client_name values missing from PROVIDER_TO_GEN_AI_SYSTEM: {unmapped}"


def test_every_emitted_client_name_literal_is_mapped() -> None:
    """Catch the dispatcher case the class-attribute walk cannot see.

    ``ClaudeCodeDispatcher`` passes ``client_name="claude-code"`` as a literal
    on the event it emits — no client class involved — which is exactly how
    ``claude-code`` reached the provider map's blind spot. Scanning the source
    for emitted literals covers both shapes.
    """
    import re

    root = Path(__file__).resolve().parents[4]
    pattern = re.compile(r'client_name=["\']([A-Za-z0-9._-]+)["\']')
    literals: set[str] = set()
    for path in root.glob("packages/*/src/parrot/**/*.py"):
        literals.update(pattern.findall(path.read_text(encoding="utf-8")))
    unmapped = sorted(n for n in literals if n not in PROVIDER_TO_GEN_AI_SYSTEM)
    assert not unmapped, f"emitted client_name literals missing from PROVIDER_TO_GEN_AI_SYSTEM: {unmapped}"


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


def test_before_client_excludes_raw_pii_keys() -> None:
    """Raw PII field names never leak as attribute keys; user_id/session_id
    are exposed under OTel-standard keys (enduser.id, session.id) when set."""
    e = BeforeClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        user_id="u-42",
        session_id="s-99",
    )
    attrs = build_before_client_attrs(e)
    for key in attrs:
        assert key not in {"user_id", "session_id", "question"}
    # user_id/session_id present under OTel-standard attribute names
    assert attrs["enduser.id"] == "u-42"
    assert attrs["session.id"] == "s-99"


def test_before_client_omits_user_when_none() -> None:
    """enduser.id and session.id omitted when user_id/session_id are None."""
    e = BeforeClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
    )
    attrs = build_before_client_attrs(e)
    assert "enduser.id" not in attrs
    assert "session.id" not in attrs


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


def test_before_invoke_excludes_prompt_content() -> None:
    """Prompt content (question) must not appear in attrs; user_id/session_id
    ARE included as span attributes for per-user usage tracking (OpenLIT)."""
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
    # Prompt content is never included (PII)
    assert "question" not in attrs_str
    assert "my private question" not in attrs_str
    # user_id and session_id ARE included for per-user usage tracking
    assert attrs["enduser.id"] == "u-123"
    assert attrs["session.id"] == "s-456"


def test_before_invoke_omits_user_when_none() -> None:
    """user_id and session_id omitted when None (no empty-string pollution)."""
    e = BeforeInvokeEvent(
        trace_context=TraceContext.new_root(),
        agent_name="bot",
        method="ask",
    )
    attrs = build_before_invoke_attrs(e)
    assert "enduser.id" not in attrs
    assert "session.id" not in attrs


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


# ---------------------------------------------------------------------------
# AfterClientCallEvent / ClientCallFailedEvent — user_id in spans
# ---------------------------------------------------------------------------


def test_after_client_includes_user_when_set() -> None:
    """enduser.id and session.id appear on after-client span attrs."""
    e = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="anthropic",
        model="claude-sonnet-4-20250514",
        duration_ms=120.0,
        input_tokens=100,
        output_tokens=50,
        user_id="u-77",
        session_id="s-88",
    )
    attrs = build_after_client_attrs(e)
    assert attrs["enduser.id"] == "u-77"
    assert attrs["session.id"] == "s-88"


def test_after_client_omits_user_when_none() -> None:
    """enduser.id and session.id absent when not provided."""
    e = AfterClientCallEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        duration_ms=50.0,
    )
    attrs = build_after_client_attrs(e)
    assert "enduser.id" not in attrs
    assert "session.id" not in attrs


def test_client_failed_includes_user_when_set() -> None:
    """enduser.id and session.id on error span attrs."""
    from parrot.core.events.lifecycle.events import ClientCallFailedEvent
    from parrot.observability.attributes import build_client_failed_attrs

    e = ClientCallFailedEvent(
        trace_context=TraceContext.new_root(),
        client_name="openai",
        model="gpt-4o",
        duration_ms=10.0,
        error_type="Timeout",
        error_message="timed out",
        user_id="u-fail",
        session_id="s-fail",
    )
    attrs = build_client_failed_attrs(e)
    assert attrs["enduser.id"] == "u-fail"
    assert attrs["session.id"] == "s-fail"


# ---------------------------------------------------------------------------
# invocation_context — ContextVar helper
# ---------------------------------------------------------------------------


def test_invocation_context_sets_and_restores() -> None:
    """invocation_context binds all three ContextVars and restores on exit."""
    from parrot.observability.context import (
        current_agent_name,
        current_session_id,
        current_user_id,
        invocation_context,
    )

    # Precondition: all None
    assert current_agent_name.get() is None
    assert current_user_id.get() is None
    assert current_session_id.get() is None

    with invocation_context("bot-x", user_id="u-1", session_id="s-2"):
        assert current_agent_name.get() == "bot-x"
        assert current_user_id.get() == "u-1"
        assert current_session_id.get() == "s-2"

        # Nested invocation overrides and restores
        with invocation_context("inner", user_id="u-inner"):
            assert current_agent_name.get() == "inner"
            assert current_user_id.get() == "u-inner"
            assert current_session_id.get() is None  # not set in inner

        # Outer values restored
        assert current_agent_name.get() == "bot-x"
        assert current_user_id.get() == "u-1"
        assert current_session_id.get() == "s-2"

    # All restored to None
    assert current_agent_name.get() is None
    assert current_user_id.get() is None
    assert current_session_id.get() is None
