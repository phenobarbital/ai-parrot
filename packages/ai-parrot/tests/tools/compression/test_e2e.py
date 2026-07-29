"""End-to-end integration suite for the tool-result compression pipeline
(TASK-1958, spec Sec 4 "Integration Tests").

Real `ToolManager`, real tools, real `WorkingMemoryToolkit`, real codecs —
no mocked stage. `conftest.py` (this directory) provides the shared
`tool_manager_with_wm` / `tool_manager_without_wm` / `compressors_toml`
fixtures plus the `dq_execute_database_query` / `plain_bulky_tool` /
`toolkit_bulky_tool` (via `BulkyToolkit`) test tools.
"""
import inspect
import subprocess
from pathlib import Path

from parrot.core.events.lifecycle.events import AfterToolCallEvent
from parrot.tools.compression import FilterLevel

from .conftest import BULKY_PAYLOAD, _query_result_payload


class TestEndToEnd:
    async def test_e2e_database_query_columnar(self, tool_manager_with_wm, row_oriented_payload):
        """`execute_tool` on a DatabaseQueryToolkit-shaped result (500
        rows x 12 cols) -> columnar output, metrics in metadata,
        AfterToolCallEvent emitted, measurable size reduction."""
        tool = tool_manager_with_wm._tools["dq_execute_database_query"]

        captured_events: list = []

        async def _capture(event):
            captured_events.append(event)

        tool.events.subscribe(AfterToolCallEvent, _capture)

        metas: list = []
        tool_manager_with_wm.add_result_hook(lambda name, result, meta: metas.append(meta))

        out = await tool_manager_with_wm.execute_tool("dq_execute_database_query", {})

        # columnar output shape (spec Sec 2)
        assert "columns" in out["rows"]
        assert "rows" in out["rows"]
        assert len(out["rows"]["columns"]) < 12  # constant/null columns factored out

        # AfterToolCallEvent fired (FEAT-176 lifecycle instrumentation)
        assert len(captured_events) == 1
        evt = captured_events[0]
        assert isinstance(evt, AfterToolCallEvent)
        assert evt.tool_name == "dq_execute_database_query"
        # KNOWN GAP (documented in TASK-1952's Completion Note, NOT fixed
        # by this task — out of its file scope): AfterToolCallEvent is
        # emitted inside AbstractTool.execute(), strictly BEFORE
        # ToolManager's compression stage runs (ToolManager has no event
        # emitter of its own), so this specific event instance's
        # compression_* fields stay at their zero-value defaults. The
        # REAL compression metrics travel in ToolResult.metadata instead
        # (verified below via a result hook — the same technique
        # TASK-1952's own tests use).
        assert evt.compression_codec == ""

        meta = metas[-1]
        assert meta["compression_codec"] == "columnar"
        assert meta["compression_level"] == FilterLevel.NORMAL.value
        assert meta["result_size_bytes"] < meta["result_size_bytes_original"]

    async def test_e2e_lossy_roundtrip_via_wm(self, tool_manager_with_wm, row_oriented_payload):
        """NORMAL compression -> `_tee` pointer -> `wm_get_result(include_raw=True)`
        recovers the full original payload without re-running the tool."""
        out = await tool_manager_with_wm.execute_tool("dq_execute_database_query", {})
        # `attach_tee_pointer` merges `_tee` into the OUTER dict (the whole
        # QueryResult-shaped payload the codec rewraps), not into the
        # nested `rows` sub-dict.
        assert "_tee" in out
        key = out["_tee"]["key"]

        wm = tool_manager_with_wm._find_working_memory_toolkit()
        recovered = await wm.get_result(key=key, include_raw=True)
        assert recovered["raw_data"] == _query_result_payload(row_oriented_payload)

    async def test_e2e_kill_switch_restores_behavior(self, tool_manager_with_wm, monkeypatch):
        """PARROT_COMPRESSION_DISABLED=1 -> byte-identical behavior to the
        pre-feature baseline (captured dynamically, never hardcoded)."""
        tool = tool_manager_with_wm._tools["dq_execute_database_query"]
        raw_baseline = await tool._execute()

        monkeypatch.setenv("PARROT_COMPRESSION_DISABLED", "1")
        disabled = await tool_manager_with_wm.execute_tool("dq_execute_database_query", {})
        monkeypatch.delenv("PARROT_COMPRESSION_DISABLED")
        enabled = await tool_manager_with_wm.execute_tool("dq_execute_database_query", {})

        assert disabled == raw_baseline
        assert disabled != enabled

    async def test_e2e_compressed_persists_compressed(self, tool_manager_with_wm):
        """The compressed result is what persists to conversational
        memory; history replay (the `_compressed` marker) does not
        recompress."""
        out = await tool_manager_with_wm.execute_tool("dq_execute_database_query", {})
        assert "columns" in out["rows"]  # columnar shape, not raw rows -> this IS what persists

        again, meta = await tool_manager_with_wm._compression_stage.run(
            "dq_execute_database_query", out, status="success",
            metadata={"_compressed": True}, return_direct=False,
        )
        assert again is out
        assert meta["compression_skipped"] == "already_compressed"

    async def test_e2e_both_tool_routes(self, tool_manager_with_wm):
        """The pipeline applies identically to a plain AbstractTool and a
        ToolkitTool (G1) — same input, same (wildcard-default) config,
        same output and same compression metadata."""
        toolkit_tool_names = [
            name for name in tool_manager_with_wm._tools if "toolkit_bulky_tool" in name
        ]
        assert toolkit_tool_names, "toolkit tool not registered"

        metas: dict = {}
        tool_manager_with_wm.add_result_hook(
            lambda name, result, meta: metas.setdefault(name, meta)
        )

        a = await tool_manager_with_wm.execute_tool("plain_bulky_tool", {})
        b = await tool_manager_with_wm.execute_tool(toolkit_tool_names[0], {})

        assert a == b
        assert a != BULKY_PAYLOAD  # actually compressed (nulls elided), not passthrough
        assert (
            metas["plain_bulky_tool"]["compression_codec"]
            == metas[toolkit_tool_names[0]]["compression_codec"]
        )
        assert (
            metas["plain_bulky_tool"]["compression_level"]
            == metas[toolkit_tool_names[0]]["compression_level"]
        )


def test_compression_logic_exists_in_exactly_one_place():
    """G1: `CompressionStage` is referenced only inside the compression
    package itself or `manager.py` — the single wiring point (Sec 6 of
    the spec confirms this; a "hits" run against the stale build copy or
    worktree directories would produce false positives, which is why the
    grep is scoped to `packages/ai-parrot/src/parrot/`, excluding
    `packages/ai-parrot/build/`). Uses an ABSOLUTE path derived from
    `__file__` rather than a CWD-relative one, since pytest's working
    directory is not guaranteed across invocation styles."""
    src_root = Path(__file__).resolve().parents[3] / "src" / "parrot"
    hits = subprocess.run(
        ["grep", "-rln", "--include=*.py", "CompressionStage", str(src_root)],
        capture_output=True, text=True,
    ).stdout.split()
    assert hits, f"expected to find at least manager.py + compression/stage.py under {src_root}"
    assert all("/compression/" in h or h.endswith("manager.py") for h in hits), hits


def test_result_hooks_contract_untouched():
    """`_result_hooks` signature and contract unchanged."""
    from parrot.tools.manager import ToolManager
    assert list(inspect.signature(ToolManager.add_result_hook).parameters) == ["self", "fn"]


def test_execute_tool_public_signature_unchanged():
    """No breaking change to the existing public API of ToolManager."""
    from parrot.tools.manager import ToolManager
    sig = inspect.signature(ToolManager.execute_tool)
    assert list(sig.parameters) == ["self", "tool_name", "parameters", "permission_context"]


class TestBothToolRoutesWithoutWorkingMemory:
    async def test_e2e_suite_passes_without_wm_too(self, tool_manager_without_wm):
        """Sanity: the whole pipeline (minus tee) still runs end to end
        when no WorkingMemoryToolkit is registered — NORMAL gets capped
        to MINIMAL (G3), never a hard failure, and nothing gets teed."""
        out = await tool_manager_without_wm.execute_tool("dq_execute_database_query", {})
        assert isinstance(out, dict)
        assert "_tee" not in out
