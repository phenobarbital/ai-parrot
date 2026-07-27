"""Unit tests for wiring `CompressionStage` into `ToolManager.execute_tool()`
and the `AfterToolCallEvent` field extension (TASK-1952).
"""
import inspect

import pytest

from navigator_eventbus.lifecycle.base import TraceContext

from parrot.core.events.lifecycle.events import AfterToolCallEvent
from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit


def test_after_tool_call_event_new_fields_have_defaults():
    """Frozen dataclass: existing construction sites must keep working.

    `trace_context` has no default on the `LifecycleEvent` base (verified
    at test-write time; the task's own scaffold omitted it — corrected
    here per the anti-hallucination protocol) so it must be supplied, same
    as every other `AfterToolCallEvent(...)` call site in this codebase
    (e.g. `abstract.py:738`, `test_registry.py`, `test_opentelemetry_subscriber.py`).
    """
    evt = AfterToolCallEvent(trace_context=TraceContext.new_root(),
                             tool_name="t", duration_ms=1.0,
                             result_status="success", result_size_bytes=10)
    assert evt.compression_codec == ""
    assert evt.compression_level == ""
    assert evt.result_size_bytes_original == 0
    assert evt.compression_duration_ms == 0.0
    assert evt.compression_teed is False
    # existing field unaffected
    assert evt.result_size_bytes == 10


# A payload with nulls (elided) and 5 identical rows-once-nulls-dropped
# (collapsed by exact dedup) — enough for MINIMAL-level json_compact to
# visibly transform the output, so tests can assert on the difference.
BULKY_PAYLOAD = {
    "a": 1,
    "b": None,
    "rows": [{"x": 1, "y": None} for _ in range(5)],
}


class BulkyTool(AbstractTool):
    """Plain `AbstractTool` route: returns a bulky payload with nulls."""

    name = "bulky_tool"
    description = "Returns a bulky payload for compression tests."

    async def _execute(self, **kwargs):
        return dict(BULKY_PAYLOAD)


class BulkyToolkit(AbstractToolkit):
    """`ToolkitTool` route: same bulky payload, via a toolkit method."""

    async def bulky_toolkit_tool(self) -> dict:
        """Return a bulky payload."""
        return dict(BULKY_PAYLOAD)


@pytest.fixture
def tool_manager_with_compression():
    tm = ToolManager(include_search_tool=False)
    tm.register_tool(BulkyTool())
    tm.register_toolkit(BulkyToolkit())
    return tm


class TestStagePlacement:
    async def test_extraction_sees_original(self, tool_manager_with_compression):
        """Q1: hooks observe the ORIGINAL; the return value is compressed."""
        seen = []
        tool_manager_with_compression.add_result_hook(
            lambda name, result, meta: seen.append(result)
        )
        out = await tool_manager_with_compression.execute_tool("bulky_tool", {})
        assert seen and seen[0] is not out          # hook saw the pre-compression object
        assert out != seen[0]                        # and the caller got the compressed one
        assert seen[0] == BULKY_PAYLOAD               # hook's view is untouched
        assert "b" not in out                         # null key elided (MINIMAL default)

    async def test_both_tool_routes(self, tool_manager_with_compression):
        """G1: identical treatment for AbstractTool and ToolkitTool."""
        toolkit_names = [
            name for name in tool_manager_with_compression._tools
            if "bulky_toolkit_tool" in name
        ]
        assert toolkit_names, "toolkit tool not registered"

        out_abstract = await tool_manager_with_compression.execute_tool("bulky_tool", {})
        out_toolkit = await tool_manager_with_compression.execute_tool(toolkit_names[0], {})

        for out in (out_abstract, out_toolkit):
            assert "b" not in out
            assert out != BULKY_PAYLOAD

    async def test_kill_switch_restores_behavior(self, tool_manager_with_compression,
                                                 monkeypatch):
        monkeypatch.setenv("PARROT_COMPRESSION_DISABLED", "1")
        out = await tool_manager_with_compression.execute_tool("bulky_tool", {})
        assert out == BULKY_PAYLOAD

    async def test_after_tool_call_event_fields(self, tool_manager_with_compression):
        """Compression metadata (codec/level/sizes/duration/teed) is merged
        into the same metadata dict result hooks observe (by reference), so
        it travels with the result. `result_size_bytes` is the
        post-compression size; the original is in
        `result_size_bytes_original`."""
        captured_meta = []
        tool_manager_with_compression.add_result_hook(
            lambda name, result, meta: captured_meta.append(meta)
        )
        await tool_manager_with_compression.execute_tool("bulky_tool", {})

        meta = captured_meta[0]
        for key in ("_compressed", "compression_codec", "compression_level",
                    "result_size_bytes_original", "result_size_bytes",
                    "compression_duration_ms", "compression_teed"):
            assert key in meta
        assert meta["compression_codec"] == "json_compact"
        assert meta["result_size_bytes"] <= meta["result_size_bytes_original"]


class TestClone:
    def test_clone_does_not_share_metrics(self, tool_manager_with_compression):
        clone = tool_manager_with_compression.clone()
        assert clone._compression_stage._registry is \
            tool_manager_with_compression._compression_stage._registry
        assert clone._compression_stage._router is not \
            tool_manager_with_compression._compression_stage._router

    def test_clone_docstring_mentions_compression_state(self):
        assert "compression" in ToolManager.clone.__doc__.lower()


def test_result_hooks_contract_untouched():
    sig = inspect.signature(ToolManager.add_result_hook)
    assert list(sig.parameters) == ["self", "fn"]


def test_no_second_compression_call_site():
    """G1: compression logic exists in exactly ONE place (this stage's
    call site in `manager.py`). Non-Google clients must not grow their own
    tool-result truncation/compression logic."""
    import parrot.clients.claude as claude_mod
    import parrot.clients.groq as groq_mod
    import parrot.clients.grok as grok_mod
    for mod in (claude_mod, groq_mod, grok_mod):
        src = inspect.getsource(mod)
        assert "compression" not in src.lower()
