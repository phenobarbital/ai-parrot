"""Event-legibility tests for ClaudeCodeDispatcher (FEAT-496 TASK-2724).

Covers the exact reported bug: every published payload reduced to
``{"message_class": "SystemMessage"}`` and a ``ToolResultBlock`` reporting
its opaque ``tool_use_id`` instead of the originating tool's name.
"""

import pytest

from parrot.flows.dev_loop.dispatchers._shared import normalize_payload
from parrot.flows.dev_loop.dispatchers.claude import ClaudeCodeDispatcher


def _dispatcher() -> ClaudeCodeDispatcher:
    return ClaudeCodeDispatcher(max_concurrent=1, redis_url="redis://localhost:6379/0", stream_ttl_seconds=300)


class ToolUseBlock:
    def __init__(self, name, id_, input_):
        self.name, self.id, self.input = name, id_, input_


class ToolResultBlock:
    def __init__(self, tool_use_id, content="ok", is_error=False):
        self.tool_use_id, self.content, self.is_error = tool_use_id, content, is_error


class TextBlock:
    def __init__(self, text):
        self.text = text


class AssistantMessage:
    def __init__(self, content):
        self.content = content


class UserMessage:
    def __init__(self, content):
        self.content = content


class SystemMessage:
    subtype = "init"
    model = "claude-opus-5"
    cwd = "/wt/feat-496"
    session_id = "s1"
    tools = ["Read", "Bash"]
    mcp_servers = []
    content = None


class ResultMessage:
    subtype = "success"
    num_turns = 12
    duration_ms = 63000
    total_cost_usd = 0.42
    content = None


@pytest.fixture
def captured(monkeypatch):
    """Capture every (kind, payload) the dispatcher publishes.

    Applies ``normalize_payload`` the same way the real ``_publish_event``
    choke point does, so these tests see the actual guaranteed display
    contract (``summary`` etc.) without touching Redis/session state.
    """
    events = []

    async def fake_publish(self, stream_key, *, kind, run_id, node_id, payload):
        events.append((kind, normalize_payload(kind, payload)))

    monkeypatch.setattr(ClaudeCodeDispatcher, "_publish_event", fake_publish)
    return events


class TestClaudeEventExtraction:
    async def test_tool_use_emits_tool_name(self, captured):
        d = _dispatcher()
        await d._publish_message_event(
            "k",
            AssistantMessage([ToolUseBlock("Read", "toolu_x", {"file_path": "a/foo.py"})]),
            "run-1",
            "development.w1",
        )
        kind, p = captured[-1]
        assert kind == "dispatch.tool_use"
        assert p["tool_name"] == "Read"
        assert "foo.py" in p["tool_input"]

    async def test_tool_result_resolves_originating_name(self, captured):
        """The reported bug: toolu_01DJ... instead of a tool name."""
        d = _dispatcher()
        await d._publish_message_event(
            "k", AssistantMessage([ToolUseBlock("Read", "toolu_x", {})]), "run-1", "development.w1"
        )
        await d._publish_message_event("k", UserMessage([ToolResultBlock("toolu_x")]), "run-1", "development.w1")
        kind, p = captured[-1]
        assert kind == "dispatch.tool_result"
        assert p["tool_name"] == "Read"
        assert not str(p.get("tool_name", "")).startswith("toolu_")

    async def test_unknown_tool_use_id_degrades(self, captured):
        d = _dispatcher()
        await d._publish_message_event("k", UserMessage([ToolResultBlock("toolu_missing")]), "run-1", "n")
        _, p = captured[-1]
        assert p["summary"]

    async def test_system_message_is_enriched(self, captured):
        d = _dispatcher()
        await d._publish_message_event("k", SystemMessage(), "run-1", "n")
        _, p = captured[-1]
        assert p["model"] == "claude-opus-5"
        assert p["cwd"] == "/wt/feat-496"
        assert set(p) != {"message_class"}

    async def test_result_message_is_enriched_on_success(self, captured):
        d = _dispatcher()
        await d._publish_message_event("k", ResultMessage(), "run-1", "n")
        _, p = captured[-1]
        assert p["num_turns"] == 12
        assert p["duration_ms"] == 63000

    async def test_no_payload_is_only_a_class_name(self, captured):
        """FEAT-496 AC1, asserted over a realistic message sequence."""
        d = _dispatcher()
        for msg in [
            SystemMessage(),
            AssistantMessage([TextBlock("working")]),
            AssistantMessage([ToolUseBlock("Bash", "t1", {"command": "pytest"})]),
            UserMessage([ToolResultBlock("t1")]),
        ]:
            await d._publish_message_event("k", msg, "run-1", "n")
        for _kind, p in captured:
            assert set(p) - {"message_class"}, f"uninformative payload: {p}"

    async def test_correlation_map_is_per_dispatch(self, monkeypatch):
        """Concurrent seats on ONE dispatcher instance must not cross-resolve."""
        import asyncio

        d = _dispatcher()
        seen = {}

        async def fake_publish(self, stream_key, *, kind, run_id, node_id, payload):
            seen.setdefault(node_id, []).append((kind, payload))

        monkeypatch.setattr(ClaudeCodeDispatcher, "_publish_event", fake_publish)

        async def seat(node_id, tool_name, tool_id):
            token = None
            from parrot.flows.dev_loop.dispatchers.claude import _TOOL_NAMES_CTX

            token = _TOOL_NAMES_CTX.set({})
            try:
                await d._publish_message_event(
                    "k",
                    AssistantMessage([ToolUseBlock(tool_name, tool_id, {})]),
                    "run-1",
                    node_id,
                )
                await asyncio.sleep(0)
                await d._publish_message_event("k", UserMessage([ToolResultBlock(tool_id)]), "run-1", node_id)
            finally:
                _TOOL_NAMES_CTX.reset(token)

        await asyncio.gather(
            seat("development.w1", "Read", "toolu_shared"),
            seat("development.w2", "Bash", "toolu_shared"),
        )

        w1_result = [p for k, p in seen["development.w1"] if k == "dispatch.tool_result"][-1]
        w2_result = [p for k, p in seen["development.w2"] if k == "dispatch.tool_result"][-1]
        assert w1_result["tool_name"] == "Read"
        assert w2_result["tool_name"] == "Bash"
