"""Unit tests for parrot.cli.console (FEAT-573 TASK-3400)."""
from __future__ import annotations

import io
from unittest.mock import MagicMock

import pytest  # verified: packages/ai-parrot/tests/cli/test_integration.py:14
from rich.console import Console  # verified: parrot/cli/renderer.py:13
from rich.text import Text  # verified: parrot/cli/renderer.py:17

from parrot.cli.console import LiveRegion, get_console, reset_console, set_console


@pytest.fixture(autouse=True)
def _isolated_console():
    reset_console()
    yield
    reset_console()


def _tty_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=True, width=100)


def _pipe_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=100)


def test_get_console_singleton_and_override() -> None:
    first = get_console()
    assert get_console() is first
    override = _tty_console()
    set_console(override)
    assert get_console() is override
    reset_console()
    assert get_console() is not override


def test_live_region_non_tty_prints_sequentially() -> None:
    console = _pipe_console()
    region = LiveRegion(console)
    assert region.is_terminal is False
    region.start()
    region.update(Text("hello"))
    with region.modal():
        pass
    region.stop()
    out = console.file.getvalue()
    assert "hello" in out
    assert "\x1b[" not in out  # no cursor-control sequences on a pipe (AC2)


def test_live_region_modal_pauses_and_resumes(monkeypatch: pytest.MonkeyPatch) -> None:
    region = LiveRegion(_tty_console())
    fake_live = MagicMock()
    region._live = fake_live  # inject a started Live
    with region.modal():
        fake_live.stop.assert_called_once()
        fake_live.start.assert_not_called()
    fake_live.start.assert_called_once()
    # idempotency: stop() twice does not raise, and resume() before start() is a no-op
    region.stop()
    region.stop()
    fresh_region = LiveRegion(_tty_console())
    fresh_region.resume()  # never started — no-op, must not raise
    assert fresh_region._live is None
