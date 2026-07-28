"""Unit tests for the compression tee — working-memory escape hatch +
error-branch reorder (TASK-1953).
"""
import pytest

from parrot.tools.abstract import AbstractTool, ToolResult
from parrot.tools.compression import CompressorRegistry, FilterLevel
from parrot.tools.compression.config import CompressorEntry
from parrot.tools.compression.protocol import CompressionOutcome, register_codec
from parrot.tools.compression.tee import CompressionTee, attach_tee_pointer
from parrot.tools.manager import ToolManager
from parrot.tools.working_memory import WorkingMemoryToolkit

ORIGINAL_PAYLOAD = {"rows": [{"a": i} for i in range(5)], "note": "full data"}


@register_codec
class _AlwaysLossyTestCodec:
    """Stub codec — the real `columnar` codec is TASK-1954. Level-aware,
    like a real codec would be: lossy only above MINIMAL, so the G3
    level-capping behavior (TASK-1953) is actually observable in tests."""

    codec_name = "test_always_lossy"

    def compress(self, result, *, level, params):
        if level is FilterLevel.MINIMAL:
            return CompressionOutcome(
                payload=result, lossy=False, bytes_before=1000,
                bytes_after=1000, est_tokens_saved=0, codec_name="test_always_lossy",
            )
        return CompressionOutcome(
            payload={"summary": "compressed"}, lossy=True, bytes_before=1000,
            bytes_after=10, est_tokens_saved=200, codec_name="test_always_lossy",
        )


class LossyTool(AbstractTool):
    """Returns a payload that always compresses lossily (per the entry
    routing it through `test_always_lossy`)."""

    name = "lossy_tool"
    description = "Returns a payload that always compresses lossily."

    async def _execute(self, **kwargs):
        return dict(ORIGINAL_PAYLOAD)


class ErroringTool(AbstractTool):
    """Always returns an error `ToolResult` — probes the reordered branch."""

    name = "erroring_tool"
    description = "Always returns an error ToolResult."

    async def _execute(self, **kwargs):
        return ToolResult(
            status="error", success=False, error="boom",
            result=dict(ORIGINAL_PAYLOAD),
        )


def _install_lossy_registry(tm: ToolManager) -> None:
    """Point `lossy_tool`/`erroring_tool` at the stub lossy codec at NORMAL,
    bypassing TOML/CWD entirely (mirrors the pattern `clone()` uses to swap
    the registry by reference)."""
    registry = CompressorRegistry({
        "lossy_tool": CompressorEntry(codec="test_always_lossy", level=FilterLevel.NORMAL),
        "erroring_tool": CompressorEntry(codec="test_always_lossy", level=FilterLevel.NORMAL),
    })
    tm._compression_registry = registry
    tm._compression_stage._registry = registry


def _wm_keys(wm: WorkingMemoryToolkit) -> list[str]:
    return list(wm._catalog._store.keys())


@pytest.fixture
def tool_manager_with_wm():
    """ToolManager with a WorkingMemoryToolkit registered (tee-capable)."""
    tm = ToolManager(include_search_tool=False)
    tm.register_tool(LossyTool())
    tm.register_tool(ErroringTool())
    tm.register_toolkit(WorkingMemoryToolkit())
    _install_lossy_registry(tm)
    return tm


@pytest.fixture
def tool_manager_without_wm():
    """ToolManager without working memory → tee degradation path."""
    tm = ToolManager(include_search_tool=False)
    tm.register_tool(LossyTool())
    tm.register_tool(ErroringTool())
    _install_lossy_registry(tm)
    return tm


class TestCompressionTeeUnit:
    """Direct unit tests of CompressionTee, independent of ToolManager."""

    async def test_unavailable_without_wm(self):
        tee = CompressionTee(working_memory=None)
        assert tee.available is False
        assert await tee.store("t", {"a": 1}, "lossy") is None

    async def test_store_returns_key_and_persists(self):
        wm = WorkingMemoryToolkit()
        tee = CompressionTee(working_memory=wm)
        assert tee.available is True
        key = await tee.store("my_tool", {"a": 1}, "lossy")
        assert key is not None
        assert key.startswith("__tee__:my_tool:")
        assert key in _wm_keys(wm)

    async def test_key_collision_counter(self):
        wm = WorkingMemoryToolkit()
        tee = CompressionTee(working_memory=wm)
        k1 = await tee.store("same_tool", {"a": 1}, "lossy")
        k2 = await tee.store("same_tool", {"a": 2}, "lossy")
        assert k1 != k2
        assert k1 in _wm_keys(wm)
        assert k2 in _wm_keys(wm)

    async def test_store_failure_returns_none(self, monkeypatch, caplog):
        wm = WorkingMemoryToolkit()
        tee = CompressionTee(working_memory=wm)

        async def boom(**kwargs):
            raise RuntimeError("wm down")

        monkeypatch.setattr(wm, "store_result", boom)
        with caplog.at_level("WARNING"):
            key = await tee.store("t", {"a": 1}, "lossy")
        assert key is None
        assert any("wm down" in r.message or "Tee failed" in r.message
                   for r in caplog.records)

    async def test_bind_working_memory_updates_availability(self):
        tee = CompressionTee()
        assert tee.available is False
        wm = WorkingMemoryToolkit()
        tee.bind_working_memory(wm)
        assert tee.available is True
        tee.bind_working_memory(None)
        assert tee.available is False

    async def test_retention_evicts_oldest(self):
        wm = WorkingMemoryToolkit()
        tee = CompressionTee(working_memory=wm, max_retained=2)
        k1 = await tee.store("t", 1, "lossy")
        k2 = await tee.store("t", 2, "lossy")
        k3 = await tee.store("t", 3, "lossy")
        keys = _wm_keys(wm)
        assert k1 not in keys       # evicted
        assert k2 in keys and k3 in keys

    async def test_cleanup_drops_all_retained(self):
        wm = WorkingMemoryToolkit()
        tee = CompressionTee(working_memory=wm)
        await tee.store("t", 1, "lossy")
        await tee.store("t", 2, "lossy")
        assert len(_wm_keys(wm)) == 2
        await tee.cleanup()
        assert _wm_keys(wm) == []


def test_attach_tee_pointer_dict_payload():
    out = attach_tee_pointer({"summary": "x"}, "k1", "lossy")
    assert out == {
        "summary": "x",
        "_tee": {"key": "k1", "reason": "lossy",
                 "hint": "use wm_get_result for the full payload"},
    }


def test_attach_tee_pointer_non_dict_payload():
    out = attach_tee_pointer("plain string", "k1", "error")
    assert out == {
        "result": "plain string",
        "_tee": {"key": "k1", "reason": "error",
                 "hint": "use wm_get_result for the full payload"},
    }


class TestTee:
    async def test_tee_on_lossy(self, tool_manager_with_wm):
        out = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        assert "_tee" in out
        assert out["_tee"]["reason"] == "lossy"
        assert out["_tee"]["key"].startswith("__tee__:lossy_tool:")

    async def test_tee_on_error_before_raise(self, tool_manager_with_wm):
        with pytest.raises(ValueError, match="boom"):
            await tool_manager_with_wm.execute_tool("erroring_tool", {})
        wm = tool_manager_with_wm._find_working_memory_toolkit()
        # the discarded result.result was captured despite the raise
        assert any(k.startswith("__tee__:erroring_tool:") for k in _wm_keys(wm))

    async def test_tee_key_collision_counter(self, tool_manager_with_wm):
        a = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        b = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        assert a["_tee"]["key"] != b["_tee"]["key"]

    async def test_no_wm_caps_level_to_minimal(self, tool_manager_without_wm):
        out = await tool_manager_without_wm.execute_tool("lossy_tool", {})
        assert "_tee" not in out          # nothing lossy happened
        # Level was capped to MINIMAL, so json_compact-style passthrough
        # never reaches the always-lossy stub codec at all: the ORIGINAL
        # payload's structure survives untouched (no `summary` key, which
        # only the stub codec's lossy output would introduce).
        assert "summary" not in out
        assert out["note"] == "full data"

    async def test_tee_failure_returns_original(self, tool_manager_with_wm,
                                                monkeypatch, caplog):
        wm = tool_manager_with_wm._find_working_memory_toolkit()

        async def boom(**kwargs):
            raise RuntimeError("wm down")

        monkeypatch.setattr(wm, "store_result", boom)
        with caplog.at_level("WARNING"):
            out = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        assert "_tee" not in out
        # G3 (code-review fix): when the tee call fails at RUNTIME (as
        # opposed to being statically unavailable, which is what caps the
        # level up front), the stage must fall back to the UNCOMPRESSED
        # original — not silently return the lossy `{"summary": ...}`
        # output with no way to recover it. Previously this test only
        # checked for the absent `_tee` pointer, which passed either way
        # and did not actually catch the bug.
        assert "summary" not in out
        assert out == ORIGINAL_PAYLOAD
        assert any("wm down" in r.message or "Tee failed" in r.message
                   for r in caplog.records)

    async def test_roundtrip_recovers_full_payload(self, tool_manager_with_wm):
        out = await tool_manager_with_wm.execute_tool("lossy_tool", {})
        wm = tool_manager_with_wm._find_working_memory_toolkit()
        recovered = await wm.get_result(key=out["_tee"]["key"], include_raw=True)
        assert recovered["raw_data"] == ORIGINAL_PAYLOAD

    async def test_error_path_tee_failure_does_not_mask_original_error(
        self, tool_manager_with_wm, monkeypatch,
    ):
        # Code-review fix: the error-branch tee call in `execute_tool()`
        # is now wrapped in its own try/except so that a completely
        # broken tee (e.g. `CompressionTee.store()` itself raising,
        # bypassing its own internal safety net) can never replace or
        # mask the tool's ORIGINAL `ValueError(result.error)` with some
        # other exception.
        async def boom(*args, **kwargs):
            raise RuntimeError("tee catastrophically broken")

        monkeypatch.setattr(
            tool_manager_with_wm._compression_tee, "store", boom,
        )
        with pytest.raises(ValueError, match="boom"):
            await tool_manager_with_wm.execute_tool("erroring_tool", {})

    async def test_wm_registered_after_construction_still_works(self):
        """The tee is bound lazily — a WorkingMemoryToolkit registered
        AFTER ToolManager construction is still discovered."""
        tm = ToolManager(include_search_tool=False)
        tm.register_tool(LossyTool())
        _install_lossy_registry(tm)
        assert tm._compression_tee.available is False

        tm.register_toolkit(WorkingMemoryToolkit())
        out = await tm.execute_tool("lossy_tool", {})
        assert "_tee" in out
        assert tm._compression_tee.available is True
