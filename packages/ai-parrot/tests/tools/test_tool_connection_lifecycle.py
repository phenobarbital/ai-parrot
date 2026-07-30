"""Unit tests for the per-tool/toolkit connection lifecycle (FEAT-391).

Covers `_open()` / `_close()` / `_ensure_open()` semantics on both
`AbstractTool` and `AbstractToolkit`, idempotency, error handling, and
`ToolManager.cleanup_toolkits()` integration.
"""
import pytest

from parrot.tools.abstract import AbstractTool
from parrot.tools.manager import ToolManager
from parrot.tools.toolkit import AbstractToolkit

# ── Fixtures / helpers ───────────────────────────────────────────────────────


class TrackingTool(AbstractTool):
    """Tool subclass that tracks _open/_close calls."""

    auto_open = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.open_count = 0
        self.close_count = 0

    async def _open(self):
        self.open_count += 1

    async def _close(self):
        await super()._close()  # resets _opened
        self.close_count += 1

    async def _execute(self, **kwargs):
        return "ok"


class NoAutoOpenTool(AbstractTool):
    """Tool subclass with auto_open left at its default (False)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.open_count = 0

    async def _open(self):
        self.open_count += 1

    async def _execute(self, **kwargs):
        return "ok"


class FailingOpenTool(AbstractTool):
    """Tool whose _open() always raises."""

    auto_open = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.attempts = 0

    async def _open(self):
        self.attempts += 1
        raise ConnectionError("cannot connect")

    async def _execute(self, **kwargs):
        return "ok"


class RecoveringOpenTool(AbstractTool):
    """Tool whose _open() fails once, then succeeds."""

    auto_open = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.attempts = 0

    async def _open(self):
        self.attempts += 1
        if self.attempts == 1:
            raise ConnectionError("cannot connect")

    async def _execute(self, **kwargs):
        return "ok"


class BrokenCloseTool(AbstractTool):
    """Tool whose _close() always raises."""

    auto_open = True

    async def _open(self):
        pass

    async def _close(self):
        raise RuntimeError("close boom")

    async def _execute(self, **kwargs):
        return "ok"


@pytest.fixture
def tracking_tool():
    return TrackingTool(name="tracking_tool")


class TrackingToolkit(AbstractToolkit):
    """Toolkit subclass that tracks _open/_close calls."""

    auto_open = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.open_count = 0
        self.close_count = 0

    async def _open(self):
        self.open_count += 1

    async def _close(self):
        await super()._close()
        self.close_count += 1

    async def greet(self, name: str) -> str:
        """Say hello."""
        return f"Hello, {name}"


class NoAutoOpenToolkit(AbstractToolkit):
    """Toolkit subclass with auto_open left at its default (False)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.open_count = 0

    async def _open(self):
        self.open_count += 1

    async def greet(self, name: str) -> str:
        """Say hello."""
        return f"Hello, {name}"


class BrokenCloseToolkit(AbstractToolkit):
    """Toolkit whose _close() always raises."""

    auto_open = True

    async def _open(self):
        pass

    async def _close(self):
        raise RuntimeError("toolkit close boom")

    async def wave(self, name: str) -> str:
        """Wave at someone (distinct tool name from TrackingToolkit.greet)."""
        return f"Wave, {name}"


def _first_tool(toolkit: AbstractToolkit, name_substr: str):
    return next(t for t in toolkit.get_tools() if name_substr in t.name)


# ── AbstractTool lifecycle ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auto_open_false_no_call():
    """`_open()` is NOT called during execute() when auto_open=False."""
    tool = NoAutoOpenTool(name="no_auto")
    result = await tool.execute()
    assert result.status == "success"
    assert tool.open_count == 0
    assert tool._opened is False


@pytest.mark.asyncio
async def test_auto_open_true_calls_once(tracking_tool):
    """`_open()` is called exactly once across multiple execute() calls."""
    await tracking_tool.execute()
    await tracking_tool.execute()
    assert tracking_tool.open_count == 1
    assert tracking_tool._opened is True


@pytest.mark.asyncio
async def test_ensure_open_idempotent(tracking_tool):
    """Calling _ensure_open() multiple times only calls _open() once."""
    for _ in range(5):
        await tracking_tool._ensure_open()
    assert tracking_tool.open_count == 1


@pytest.mark.asyncio
async def test_close_resets_opened(tracking_tool):
    """_close() resets _opened, allowing _open() to run again."""
    await tracking_tool._ensure_open()
    assert tracking_tool._opened is True

    await tracking_tool._close()
    assert tracking_tool._opened is False
    assert tracking_tool.close_count == 1

    await tracking_tool._ensure_open()
    assert tracking_tool.open_count == 2


@pytest.mark.asyncio
async def test_close_idempotent(tracking_tool):
    """Calling _close() after already closed is a no-op (safe to repeat)."""
    await tracking_tool._ensure_open()
    await tracking_tool._close()
    await tracking_tool._close()
    assert tracking_tool.close_count == 2
    assert tracking_tool._opened is False


@pytest.mark.asyncio
async def test_open_error_propagates_and_retries():
    """If _open() raises, execute() fails and _opened stays False (retry)."""
    tool = FailingOpenTool(name="failing_open")
    result = await tool.execute()
    assert result.status != "success"
    assert tool._opened is False
    assert tool.attempts == 1

    # Next call retries _open() since _opened was never set to True.
    result = await tool.execute()
    assert result.status != "success"
    assert tool.attempts == 2


@pytest.mark.asyncio
async def test_open_error_recovers_on_retry():
    """A transient _open() failure recovers automatically on the next call."""
    tool = RecoveringOpenTool(name="recovering_open")
    result = await tool.execute()
    assert result.status != "success"
    assert tool._opened is False
    assert tool.attempts == 1

    result = await tool.execute()
    assert result.status == "success"
    assert tool._opened is True
    assert tool.attempts == 2


# ── AbstractToolkit lifecycle ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_toolkit_auto_open_on_first_tool_call():
    """First tool execution triggers toolkit._open()."""
    toolkit = TrackingToolkit()
    greet_tool = _first_tool(toolkit, "greet")

    await greet_tool.execute(name="World")
    assert toolkit.open_count == 1
    assert toolkit._opened is True

    await greet_tool.execute(name="Again")
    assert toolkit.open_count == 1


@pytest.mark.asyncio
async def test_toolkit_auto_open_false_no_call():
    """No automatic _open() call occurs when toolkit.auto_open is False."""
    toolkit = NoAutoOpenToolkit()
    greet_tool = _first_tool(toolkit, "greet")

    await greet_tool.execute(name="World")
    assert toolkit.open_count == 0


@pytest.mark.asyncio
async def test_toolkit_open_before_pre_execute(monkeypatch):
    """_ensure_open() runs before _pre_execute() for the toolkit."""
    toolkit = TrackingToolkit()
    call_order = []

    original_ensure_open = toolkit._ensure_open
    original_pre_execute = toolkit._pre_execute

    async def tracking_ensure_open():
        call_order.append("_ensure_open")
        await original_ensure_open()

    async def tracking_pre_execute(tool_name, /, **kwargs):
        call_order.append("_pre_execute")
        return await original_pre_execute(tool_name, **kwargs)

    monkeypatch.setattr(toolkit, "_ensure_open", tracking_ensure_open)
    monkeypatch.setattr(toolkit, "_pre_execute", tracking_pre_execute)

    greet_tool = _first_tool(toolkit, "greet")
    await greet_tool.execute(name="World")

    assert call_order == ["_ensure_open", "_pre_execute"]


@pytest.mark.asyncio
async def test_open_and_close_are_not_llm_tools():
    """_open/_close/_ensure_open are never generated as LLM-callable tools."""
    toolkit = TrackingToolkit()
    tool_names = [t.name for t in toolkit.get_tools()]
    assert not any(
        n.endswith(("_open", "_close", "_ensure_open")) for n in tool_names
    )
    assert any("greet" in n for n in tool_names)


# ── ToolManager.cleanup_toolkits() integration ───────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_calls_close_on_toolkit():
    """cleanup_toolkits() calls toolkit._close() for an opened toolkit."""
    toolkit = TrackingToolkit()
    manager = ToolManager()
    manager.register_toolkit(toolkit)

    greet_tool = _first_tool(toolkit, "greet")
    await greet_tool.execute(name="World")
    assert toolkit._opened is True

    await manager.cleanup_toolkits()
    assert toolkit.close_count == 1
    assert toolkit._opened is False


@pytest.mark.asyncio
async def test_cleanup_skips_close_on_unopened_toolkit():
    """cleanup_toolkits() does not call _close() on a toolkit never opened."""
    toolkit = TrackingToolkit()
    manager = ToolManager()
    manager.register_toolkit(toolkit)

    await manager.cleanup_toolkits()
    assert toolkit.close_count == 0


@pytest.mark.asyncio
async def test_cleanup_calls_close_on_standalone_tool(tracking_tool):
    """cleanup_toolkits() calls _close() on standalone (non-toolkit) tools."""
    manager = ToolManager()
    manager.add_tool(tracking_tool)

    await tracking_tool.execute()
    assert tracking_tool._opened is True

    await manager.cleanup_toolkits()
    assert tracking_tool.close_count == 1
    assert tracking_tool._opened is False


@pytest.mark.asyncio
async def test_cleanup_close_error_logged_not_raised():
    """A _close() error during cleanup is caught/logged, not raised."""
    broken = BrokenCloseTool(name="broken_close")
    manager = ToolManager()
    manager.add_tool(broken)

    await broken.execute()
    assert broken._opened is True

    # Must not raise despite _close() raising internally.
    await manager.cleanup_toolkits()


@pytest.mark.asyncio
async def test_cleanup_close_error_does_not_block_other_toolkits():
    """One broken toolkit's _close() error doesn't stop other cleanups."""
    broken_toolkit = BrokenCloseToolkit()
    good_toolkit = TrackingToolkit()

    manager = ToolManager()
    manager.register_toolkit(broken_toolkit)
    manager.register_toolkit(good_toolkit)

    broken_wave = _first_tool(broken_toolkit, "wave")
    good_greet = _first_tool(good_toolkit, "greet")
    await broken_wave.execute(name="World")
    await good_greet.execute(name="World")

    await manager.cleanup_toolkits()

    # good_toolkit's _close() must still have run despite broken_toolkit's error.
    assert good_toolkit.close_count == 1
    assert good_toolkit._opened is False
