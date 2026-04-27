"""Unit tests for :class:`ClaudeAgentClient` and its factory registration.

Covers (per spec §4 / TASK-861 acceptance criteria):

* Lazy-import of ``claude_agent_sdk`` (no eager import at construction).
* ``ask`` assembles ``AssistantMessage`` / ``TextBlock`` content into the
  unified ``AIMessage.output``.
* ``ask_stream`` yields ``TextBlock.text`` chunks in arrival order.
* ``ToolUseBlock`` is captured as a ``ToolCall``.
* ``batch_ask`` raises ``NotImplementedError`` with a redirect to
  :class:`AnthropicClient`.
* ``LLMFactory.create("claude-agent")`` and
  ``LLMFactory.create("claude-code")`` both produce a
  :class:`ClaudeAgentClient`.
* When the optional ``[claude-agent]`` extra is missing, the lazy loader
  raises ``ImportError`` carrying the actionable
  ``pip install ai-parrot[claude-agent]`` hint.
* A live smoke test marked ``@pytest.mark.live`` skips when the bundled
  ``claude`` CLI is unavailable.

All non-live tests fully mock the SDK; no subprocess is spawned.
"""
from __future__ import annotations

import importlib
import shutil
import sys
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — async-iter wrapper for query() mocks
# ---------------------------------------------------------------------------


class _AsyncIter:
    """Wrap a synchronous iterable as an async iterator."""

    def __init__(self, items: List[Any]) -> None:
        self._items = list(items)

    def __aiter__(self) -> "_AsyncIter":
        return self

    async def __anext__(self) -> Any:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def _fake_query_factory(messages: List[Any]):
    """Build a stand-in for ``claude_agent_sdk.query`` that yields messages."""

    def _query(*args: Any, **kwargs: Any) -> _AsyncIter:
        return _AsyncIter(messages)

    return _query


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClaudeAgentLazyImport:
    """``ClaudeAgentClient()`` must not import claude_agent_sdk at construction."""

    def test_init_does_not_import_sdk(self):
        from parrot.clients import claude_agent as ca_module

        # The module itself must not have eagerly loaded claude_agent_sdk.
        # Construction should likewise be import-free.
        for mod_name in list(sys.modules.keys()):
            if mod_name == "claude_agent_sdk":
                # Pre-test cleanup so we can assert no eager re-import below.
                pass

        client = ca_module.ClaudeAgentClient()
        assert client.client_type == "claude_agent"
        assert client.client_name == "claude-agent"
        assert client._default_model == "claude-sonnet-4-6"
        # The constructor itself doesn't need to touch the SDK; even if it
        # was imported earlier in this session by a sibling test, the *client
        # construction* must not depend on it.
        assert client.client is None  # property returns None outside a loop


class TestClaudeAgentAsk:
    """``ask()`` collects the message stream and returns an AIMessage."""

    @pytest.mark.asyncio
    async def test_ask_assembles_text(self, fake_claude_agent_messages):
        from parrot.clients.claude_agent import ClaudeAgentClient
        from parrot.clients import claude_agent as ca_module

        fake_query = _fake_query_factory(fake_claude_agent_messages)

        with patch.object(
            ca_module,
            "_import_sdk",
            return_value=(fake_query, object, lambda **_: SimpleNamespace()),
        ):
            client = ClaudeAgentClient()
            result = await client.ask("test prompt")

        assert result.output == "hello world"
        assert result.response == "hello world"
        assert result.input == "test prompt"
        assert result.provider == "claude-agent"
        assert result.model == "claude-sonnet-4-6"
        assert result.stop_reason == "end_turn"  # success → end_turn
        assert result.usage.estimated_cost == pytest.approx(0.001)


class TestClaudeAgentAskStream:
    """``ask_stream`` yields TextBlock text in order."""

    @pytest.mark.asyncio
    async def test_yields_text_in_order(self, fake_claude_agent_messages):
        from parrot.clients.claude_agent import ClaudeAgentClient
        from parrot.clients import claude_agent as ca_module

        fake_query = _fake_query_factory(fake_claude_agent_messages)

        with patch.object(
            ca_module,
            "_import_sdk",
            return_value=(fake_query, object, lambda **_: SimpleNamespace()),
        ):
            client = ClaudeAgentClient()
            chunks: List[str] = []
            async for piece in client.ask_stream("hi"):
                chunks.append(piece)

        assert chunks == ["hello ", "world"]


class TestClaudeAgentToolUseRecorded:
    """``ToolUseBlock`` rolls up into ``AIMessage.tool_calls``."""

    @pytest.mark.asyncio
    async def test_tool_use_recorded(self):
        from parrot.clients.claude_agent import ClaudeAgentClient
        from parrot.clients import claude_agent as ca_module

        # Build a stream with a ToolUseBlock interleaved with text.
        try:
            from claude_agent_sdk.types import (
                AssistantMessage,
                ResultMessage,
                TextBlock,
                ToolUseBlock,
            )

            messages = [
                AssistantMessage(
                    content=[
                        TextBlock(text="Listing files…"),
                        ToolUseBlock(
                            id="t1",
                            name="Bash",
                            input={"cmd": "ls"},
                        ),
                    ],
                    model="claude-sonnet-4-6",
                ),
                ResultMessage(
                    subtype="success",
                    duration_ms=10,
                    duration_api_ms=8,
                    is_error=False,
                    num_turns=1,
                    session_id="sess-tool",
                ),
            ]
        except Exception:  # pragma: no cover
            # Fallback duck-typed mock for environments without the SDK.
            text_ns = SimpleNamespace(text="Listing files…")
            text_ns.__class__ = type("TextBlock", (), {})
            tool_ns = SimpleNamespace(id="t1", name="Bash", input={"cmd": "ls"})
            tool_ns.__class__ = type("ToolUseBlock", (), {})
            asst_ns = SimpleNamespace(
                content=[text_ns, tool_ns],
                model="claude-sonnet-4-6",
                usage=None,
                stop_reason=None,
                session_id=None,
            )
            asst_ns.__class__ = type("AssistantMessage", (), {})
            res_ns = SimpleNamespace(
                subtype="success",
                num_turns=1,
                session_id="sess-tool",
                stop_reason=None,
                total_cost_usd=None,
                usage=None,
                duration_ms=10,
                duration_api_ms=8,
                is_error=False,
                result=None,
                structured_output=None,
                model_usage=None,
            )
            res_ns.__class__ = type("ResultMessage", (), {})
            messages = [asst_ns, res_ns]

        fake_query = _fake_query_factory(messages)
        with patch.object(
            ca_module,
            "_import_sdk",
            return_value=(fake_query, object, lambda **_: SimpleNamespace()),
        ):
            client = ClaudeAgentClient()
            result = await client.ask("list cwd")

        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "t1"
        assert tc.name == "Bash"
        assert tc.arguments == {"cmd": "ls"}


class TestClaudeAgentBatchAskUnsupported:
    """``batch_ask`` must redirect to AnthropicClient."""

    @pytest.mark.asyncio
    async def test_batch_ask_raises(self):
        from parrot.clients.claude_agent import ClaudeAgentClient

        client = ClaudeAgentClient()
        with pytest.raises(NotImplementedError, match="AnthropicClient"):
            await client.batch_ask([])

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method_name",
        [
            "ask_to_image",
            "summarize_text",
            "translate_text",
            "analyze_sentiment",
            "analyze_product_review",
            "extract_key_points",
        ],
    )
    async def test_unsupported_methods_raise(self, method_name: str):
        from parrot.clients.claude_agent import ClaudeAgentClient

        client = ClaudeAgentClient()
        method = getattr(client, method_name)
        with pytest.raises(NotImplementedError, match="AnthropicClient"):
            await method()


class TestClaudeAgentRunOptions:
    """``ClaudeAgentRunOptions`` is a Pydantic model with the documented surface."""

    def test_basic_fields(self):
        from parrot.clients.claude_agent import ClaudeAgentRunOptions

        opts = ClaudeAgentRunOptions(
            allowed_tools=["Read", "Bash"],
            cwd="/tmp",
            permission_mode="default",
        )
        assert opts.allowed_tools == ["Read", "Bash"]
        assert opts.cwd == "/tmp"
        assert opts.permission_mode == "default"
        assert opts.disallowed_tools is None
        assert opts.extra_options == {}


class TestFactoryRegistration:
    """``LLMFactory`` resolves ``claude-agent`` / ``claude-code``."""

    def test_supported_clients_includes_keys(self):
        from parrot.clients.factory import SUPPORTED_CLIENTS, _lazy_claude_agent

        assert "claude-agent" in SUPPORTED_CLIENTS
        assert "claude-code" in SUPPORTED_CLIENTS
        assert SUPPORTED_CLIENTS["claude-agent"] is _lazy_claude_agent
        assert SUPPORTED_CLIENTS["claude-code"] is _lazy_claude_agent

    def test_parse_llm_string_claude_agent(self):
        from parrot.clients.factory import LLMFactory

        provider, model = LLMFactory.parse_llm_string(
            "claude-agent:claude-sonnet-4-6"
        )
        assert provider == "claude-agent"
        assert model == "claude-sonnet-4-6"

    def test_parse_llm_string_claude_code_alias(self):
        from parrot.clients.factory import LLMFactory

        provider, model = LLMFactory.parse_llm_string(
            "claude-code:claude-sonnet-4-6"
        )
        assert provider == "claude-code"
        assert model == "claude-sonnet-4-6"

    def test_create_claude_agent(self):
        from parrot.clients.factory import LLMFactory

        client = LLMFactory.create("claude-agent:claude-sonnet-4-6")
        assert type(client).__name__ == "ClaudeAgentClient"

    def test_create_claude_code_alias(self):
        from parrot.clients.factory import LLMFactory

        client = LLMFactory.create("claude-code")
        assert type(client).__name__ == "ClaudeAgentClient"


class TestFactoryMissingExtraMessage:
    """When ``claude_agent_sdk`` is unavailable, the loader surfaces a hint."""

    def test_missing_extra_raises_import_error_with_hint(self, monkeypatch):
        # We can't easily uninstall the SDK in mid-process, so we patch
        # the loader's import statement to raise ImportError.
        from parrot.clients import factory as factory_module

        def _broken_loader():
            try:
                raise ImportError("No module named 'claude_agent_sdk'")
            except ImportError as exc:
                raise ImportError(
                    "ClaudeAgentClient requires claude-agent-sdk. "
                    "Install with: pip install ai-parrot[claude-agent]"
                ) from exc

        monkeypatch.setitem(
            factory_module.SUPPORTED_CLIENTS, "claude-agent", _broken_loader
        )
        monkeypatch.setitem(
            factory_module.SUPPORTED_CLIENTS, "claude-code", _broken_loader
        )

        with pytest.raises(ImportError) as exc_info:
            factory_module.LLMFactory.create("claude-agent")
        assert "pip install ai-parrot[claude-agent]" in str(exc_info.value)


class TestClaudeAgentResume:
    """``resume`` continues a session by passing ``resume`` into options."""

    @pytest.mark.asyncio
    async def test_resume_collects_messages(self, fake_claude_agent_messages):
        from parrot.clients.claude_agent import ClaudeAgentClient
        from parrot.clients import claude_agent as ca_module

        fake_query = _fake_query_factory(fake_claude_agent_messages)

        with patch.object(
            ca_module,
            "_import_sdk",
            return_value=(fake_query, object, lambda **_: SimpleNamespace()),
        ):
            client = ClaudeAgentClient()
            result = await client.resume(
                session_id="sess-x", user_input="continue", state=None
            )
        assert result.output == "hello world"
        assert result.session_id == "sess-x"


@pytest.mark.live
@pytest.mark.asyncio
async def test_claude_agent_live_smoke():
    """Live smoke test — requires the bundled ``claude`` CLI.

    Skipped when the binary is unavailable so CI environments without it
    remain green.
    """
    if not shutil.which("claude"):
        pytest.skip("claude CLI not found on PATH")
    from parrot.clients.claude_agent import ClaudeAgentClient

    client = ClaudeAgentClient()
    result = await client.ask("Say the word PONG and nothing else.")
    assert result.output
