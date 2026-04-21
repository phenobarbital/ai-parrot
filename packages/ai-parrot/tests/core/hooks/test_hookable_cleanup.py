"""Tests for HookableAgent.cleanup() — FEAT-114 bot-cleanup-lifecycle.

Exercises the four contract points specified in TASK-815:
1. stop_hooks() is called when _hook_manager exists.
2. Safe no-op when _init_hooks() was never called.
3. super().cleanup() is chained via MRO.
4. Exceptions from stop_hooks() are swallowed; super().cleanup() still runs.
"""
import pytest
from unittest.mock import AsyncMock

from parrot.core.hooks.mixins import HookableAgent


# ---------------------------------------------------------------------------
# Test harness classes
# ---------------------------------------------------------------------------

class _BaseWithCleanup:
    """Minimal synthetic 'bot base' that records super().cleanup() calls."""

    def __init__(self) -> None:
        self.super_cleanup_called = False

    async def cleanup(self) -> None:
        self.super_cleanup_called = True


class _BaseNoCleanup:
    """Minimal synthetic base with NO cleanup() — exercises the super() guard."""

    def __init__(self) -> None:
        pass


class _HookableWithBase(HookableAgent, _BaseWithCleanup):
    """Mixin declared BEFORE the base — correct MRO ordering."""

    def __init__(self, init_hooks: bool = True) -> None:
        _BaseWithCleanup.__init__(self)
        if init_hooks:
            self._init_hooks()


class _HookableNoBase(HookableAgent, _BaseNoCleanup):
    """Mixin with a base that has no cleanup() — exercises the super() guard."""

    def __init__(self, init_hooks: bool = True) -> None:
        _BaseNoCleanup.__init__(self)
        if init_hooks:
            self._init_hooks()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hookable_cleanup_calls_stop_hooks() -> None:
    """cleanup() must call stop_hooks() exactly once when _hook_manager exists."""
    bot = _HookableWithBase(init_hooks=True)
    # Patch stop_hooks directly — cleanup() calls it; stop_all is an
    # implementation detail of HookManager that is covered by HookManager tests.
    bot.stop_hooks = AsyncMock()

    await bot.cleanup()

    bot.stop_hooks.assert_awaited_once()


@pytest.mark.asyncio
async def test_hookable_cleanup_no_hooks_initialized() -> None:
    """cleanup() must not raise when _init_hooks() was never called."""
    bot = _HookableWithBase(init_hooks=False)
    # _hook_manager does not exist; the guard should make this a no-op
    await bot.cleanup()
    # super().cleanup() still runs even without hooks
    assert bot.super_cleanup_called is True


@pytest.mark.asyncio
async def test_hookable_cleanup_chains_super() -> None:
    """cleanup() must invoke super().cleanup() (i.e. _BaseWithCleanup.cleanup)."""
    bot = _HookableWithBase(init_hooks=True)
    bot.stop_hooks = AsyncMock()

    await bot.cleanup()

    assert bot.super_cleanup_called is True


@pytest.mark.asyncio
async def test_hookable_cleanup_swallows_stop_hooks_error() -> None:
    """If stop_hooks() raises, the exception must be swallowed and
    super().cleanup() must still run."""
    bot = _HookableWithBase(init_hooks=True)
    bot.stop_hooks = AsyncMock(side_effect=RuntimeError("boom"))

    # Must not propagate
    await bot.cleanup()

    # super().cleanup() still reached despite the error
    assert bot.super_cleanup_called is True
