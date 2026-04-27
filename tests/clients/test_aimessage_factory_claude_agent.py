"""Unit tests for ``AIMessageFactory.from_claude_agent``.

Covers:

* Text concatenation across multiple ``AssistantMessage``/``TextBlock`` pairs.
* ``ToolUseBlock`` mapping to ``ToolCall``.
* ``ResultMessage`` metadata extraction (``stop_reason``, usage,
  ``estimated_cost``, ``num_turns``).
* Empty-message edge case.
* Provider tagging (``"claude-agent"``, distinct from ``"claude"``).
* ``CompletionUsage.from_claude_agent`` zero-defaults and edge cases.

The tests deliberately rely on the real ``claude_agent_sdk.types`` dataclasses
when available (they ship as part of the installed extra in the dev
environment) but are written so they can also operate against simple
namespace stand-ins via duck typing.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List

import pytest


# ---------------------------------------------------------------------------
# Helpers — build SDK-shape dataclasses or namespaces deterministically
# ---------------------------------------------------------------------------

def _sdk_types_or_none():
    """Return the real ``claude_agent_sdk.types`` namespace, or ``None``.

    When the optional ``[claude-agent]`` extra is not installed, fall back to
    ``SimpleNamespace`` stand-ins so duck-typing branches in
    ``from_claude_agent`` are exercised.
    """
    try:
        from claude_agent_sdk import types as sdk_types
        return sdk_types
    except Exception:  # pragma: no cover
        return None


def _make_text_block(text: str):
    """Build a ``TextBlock`` (real SDK if available, namespace otherwise)."""
    sdk = _sdk_types_or_none()
    if sdk is not None:
        return sdk.TextBlock(text=text)
    ns = SimpleNamespace(text=text)
    ns.__class__ = type("TextBlock", (), {})
    return ns


def _make_tool_use_block(tool_id: str, name: str, tool_input: dict):
    """Build a ``ToolUseBlock``."""
    sdk = _sdk_types_or_none()
    if sdk is not None:
        return sdk.ToolUseBlock(id=tool_id, name=name, input=tool_input)
    ns = SimpleNamespace(id=tool_id, name=name, input=tool_input)
    ns.__class__ = type("ToolUseBlock", (), {})
    return ns


def _make_assistant_message(content: List[Any], model: str = "claude-sonnet-4-6", **kwargs):
    """Build an ``AssistantMessage``."""
    sdk = _sdk_types_or_none()
    if sdk is not None:
        return sdk.AssistantMessage(content=content, model=model, **kwargs)
    ns = SimpleNamespace(content=content, model=model, usage=None,
                          stop_reason=None, session_id=None, **kwargs)
    ns.__class__ = type("AssistantMessage", (), {})
    return ns


def _make_result_message(
    *,
    subtype: str = "success",
    duration_ms: int = 1000,
    duration_api_ms: int = 800,
    is_error: bool = False,
    num_turns: int = 1,
    session_id: str = "sess-1",
    stop_reason: str | None = None,
    total_cost_usd: float | None = None,
    usage: dict | None = None,
    result: str | None = None,
    structured_output: Any = None,
    model_usage: dict | None = None,
):
    """Build a ``ResultMessage``."""
    sdk = _sdk_types_or_none()
    if sdk is not None:
        return sdk.ResultMessage(
            subtype=subtype,
            duration_ms=duration_ms,
            duration_api_ms=duration_api_ms,
            is_error=is_error,
            num_turns=num_turns,
            session_id=session_id,
            stop_reason=stop_reason,
            total_cost_usd=total_cost_usd,
            usage=usage,
            result=result,
            structured_output=structured_output,
            model_usage=model_usage,
        )
    ns = SimpleNamespace(
        subtype=subtype,
        duration_ms=duration_ms,
        duration_api_ms=duration_api_ms,
        is_error=is_error,
        num_turns=num_turns,
        session_id=session_id,
        stop_reason=stop_reason,
        total_cost_usd=total_cost_usd,
        usage=usage,
        result=result,
        structured_output=structured_output,
        model_usage=model_usage,
    )
    ns.__class__ = type("ResultMessage", (), {})
    return ns


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAIMessageFactoryFromClaudeAgent:
    """Covers the primary spec test cases."""

    def test_basic_text_assembly(self):
        """Text from multiple ``AssistantMessage`` / ``TextBlock`` is concatenated."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(content=[_make_text_block("hello ")]),
            _make_assistant_message(content=[_make_text_block("world")]),
            _make_result_message(subtype="success", num_turns=1, total_cost_usd=0.001),
        ]

        result = AIMessageFactory.from_claude_agent(
            messages=messages,
            input_text="say hello world",
        )

        assert result.output == "hello world"
        assert result.response == "hello world"
        assert result.input == "say hello world"

    def test_tool_use_mapped_to_tool_call(self):
        """``ToolUseBlock`` produces a ``ToolCall`` in ``AIMessage.tool_calls``."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(
                content=[
                    _make_text_block("Listing files…"),
                    _make_tool_use_block(
                        tool_id="t1",
                        name="Bash",
                        tool_input={"command": "ls"},
                    ),
                ]
            ),
            _make_result_message(subtype="success"),
        ]

        result = AIMessageFactory.from_claude_agent(
            messages=messages,
            input_text="list files",
        )

        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "t1"
        assert tc.name == "Bash"
        assert tc.arguments == {"command": "ls"}
        assert result.has_tools is True

    def test_result_metadata_extracted(self):
        """``ResultMessage`` populates ``usage``, ``stop_reason``, ``estimated_cost``."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(
                content=[_make_text_block("done")],
                model="claude-sonnet-4-6",
            ),
            _make_result_message(
                subtype="success",
                num_turns=3,
                total_cost_usd=0.0042,
                usage={"input_tokens": 100, "output_tokens": 25},
                model_usage={"claude-sonnet-4-6": {"input_tokens": 100}},
            ),
        ]

        result = AIMessageFactory.from_claude_agent(
            messages=messages,
            input_text="anything",
        )

        # subtype="success" maps to "end_turn" via _CLAUDE_AGENT_STOP_REASON_MAP.
        assert result.stop_reason == "end_turn"
        assert result.finish_reason == "end_turn"
        assert result.usage.estimated_cost == pytest.approx(0.0042)
        assert result.usage.prompt_tokens == 100
        assert result.usage.completion_tokens == 25
        assert result.usage.total_tokens == 125
        assert result.usage.extra_usage.get("num_turns") == 3
        assert "model_usage" in result.usage.extra_usage

    def test_error_max_turns_subtype_mapped(self):
        """``error_max_turns`` subtype maps to ``stop_reason="max_turns"``."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(content=[_make_text_block("partial")]),
            _make_result_message(
                subtype="error_max_turns",
                num_turns=10,
                is_error=True,
            ),
        ]

        result = AIMessageFactory.from_claude_agent(
            messages=messages, input_text="loop"
        )
        assert result.stop_reason == "max_turns"

    def test_empty_message_list(self):
        """Empty ``messages`` produces a graceful empty-output ``AIMessage``."""
        from parrot.models.responses import AIMessageFactory

        result = AIMessageFactory.from_claude_agent(
            messages=[], input_text="ping"
        )
        assert result.output == ""
        assert result.response == ""
        assert result.tool_calls == []
        assert result.usage.prompt_tokens == 0
        assert result.usage.completion_tokens == 0
        # No model in stream -> fallback sentinel
        assert result.model == "claude-agent"

    def test_provider_is_claude_agent(self):
        """Provider field must be ``"claude-agent"``, not ``"claude"``."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(content=[_make_text_block("x")]),
            _make_result_message(subtype="success"),
        ]
        result = AIMessageFactory.from_claude_agent(
            messages=messages, input_text="hi"
        )
        assert result.provider == "claude-agent"
        assert result.provider != "claude"

    def test_model_inferred_from_assistant_message(self):
        """When ``model`` arg is not passed, infer from last ``AssistantMessage.model``."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(
                content=[_make_text_block("a")],
                model="claude-haiku-4-5-20251001",
            ),
            _make_result_message(subtype="success"),
        ]
        result = AIMessageFactory.from_claude_agent(
            messages=messages, input_text="hi"
        )
        assert result.model == "claude-haiku-4-5-20251001"

    def test_explicit_model_argument_wins(self):
        """An explicit ``model=`` argument overrides the AssistantMessage hint."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(
                content=[_make_text_block("a")],
                model="claude-sonnet-4-6",
            ),
            _make_result_message(subtype="success"),
        ]
        result = AIMessageFactory.from_claude_agent(
            messages=messages, input_text="hi", model="override-model"
        )
        assert result.model == "override-model"

    def test_session_id_from_result_message_used_when_caller_omits(self):
        """``ResultMessage.session_id`` flows through when caller didn't pass one."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(content=[_make_text_block("a")]),
            _make_result_message(subtype="success", session_id="sess-from-sdk"),
        ]
        result = AIMessageFactory.from_claude_agent(
            messages=messages, input_text="hi"
        )
        assert result.session_id == "sess-from-sdk"

    def test_caller_session_id_overrides_result_message(self):
        """A caller-supplied ``session_id`` wins over the ResultMessage one."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(content=[_make_text_block("a")]),
            _make_result_message(subtype="success", session_id="sess-from-sdk"),
        ]
        result = AIMessageFactory.from_claude_agent(
            messages=messages, input_text="hi", session_id="caller-sess"
        )
        assert result.session_id == "caller-sess"

    def test_per_turn_usage_aggregated_when_no_result_usage(self):
        """When ``ResultMessage.usage`` is missing, per-turn usages are aggregated."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(
                content=[_make_text_block("a")],
                usage={"input_tokens": 10, "output_tokens": 5},
            ),
            _make_assistant_message(
                content=[_make_text_block("b")],
                usage={"input_tokens": 20, "output_tokens": 7},
            ),
            _make_result_message(subtype="success", usage=None),
        ]
        result = AIMessageFactory.from_claude_agent(
            messages=messages, input_text="hi"
        )
        assert result.usage.prompt_tokens == 30
        assert result.usage.completion_tokens == 12
        assert result.usage.total_tokens == 42

    def test_structured_output_replaces_text(self):
        """A non-None ``structured_output`` replaces ``output`` but ``response`` keeps text."""
        from parrot.models.responses import AIMessageFactory

        messages = [
            _make_assistant_message(content=[_make_text_block("raw")]),
            _make_result_message(subtype="success"),
        ]
        payload = {"answer": 42}
        result = AIMessageFactory.from_claude_agent(
            messages=messages,
            input_text="x",
            structured_output=payload,
        )
        assert result.output == payload
        assert result.is_structured is True
        # ``response`` field still echoes the text we accumulated.
        assert result.response == "raw"


class TestCompletionUsageFromClaudeAgent:
    """Covers the companion ``CompletionUsage.from_claude_agent`` classmethod."""

    def test_zero_defaults(self):
        from parrot.models.basic import CompletionUsage
        usage = CompletionUsage.from_claude_agent()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0
        assert usage.estimated_cost is None

    def test_populated(self):
        from parrot.models.basic import CompletionUsage
        usage = CompletionUsage.from_claude_agent(
            result_usage={"input_tokens": 11, "output_tokens": 22},
            total_cost_usd=0.5,
            num_turns=4,
            model_usage={"claude-sonnet-4-6": {"input_tokens": 11}},
        )
        assert usage.prompt_tokens == 11
        assert usage.completion_tokens == 22
        assert usage.total_tokens == 33
        assert usage.estimated_cost == pytest.approx(0.5)
        assert usage.extra_usage["num_turns"] == 4
        assert "model_usage" in usage.extra_usage
        assert "raw_usage" in usage.extra_usage
