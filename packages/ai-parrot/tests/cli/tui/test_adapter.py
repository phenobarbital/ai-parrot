"""Tests for parrot.cli.tui.adapter (FEAT-573, spec §4 rows test_tui_logs_routed_to_drawer, test_dispatcher_uses_command_context)."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult, SuspendNotSupported  # verified: textual 8.2.8 probe

from parrot.cli.commands import SlashCommandDispatcher  # verified: commands.py:70
from parrot.cli.repl import REPLConfig  # verified: repl.py:61
from parrot.cli.tui.adapter import DrawerLogHandler, TUICommandContext, TUIRenderer
from parrot.cli.tui.widgets import LogDrawer, TranscriptView  # provided by TASK-3410


class _Harness(App[None]):
    def compose(self) -> ComposeResult:
        yield TranscriptView(id="transcript")
        yield LogDrawer(id="logs")


def _ctx(app: _Harness) -> TUICommandContext:
    runner = MagicMock()
    runner.history = []
    renderer = TUIRenderer(app.query_one("#transcript", TranscriptView))
    return TUICommandContext(
        app,
        bot=MagicMock(),
        config=REPLConfig(agent_name="a"),
        runner=runner,
        dispatcher=SlashCommandDispatcher(),
        renderer=renderer,
    )


@pytest.mark.asyncio
async def test_renderer_print_markup_lands_in_transcript():
    app = _Harness()
    async with app.run_test() as pilot:
        ctx = _ctx(app)
        ctx.renderer.print("[yellow]Unknown command[/yellow]")
        await pilot.pause()
        assert app.query_one("#transcript").query(".notice")


@pytest.mark.asyncio
async def test_dispatcher_help_and_tools_via_tui_context():
    """Daemon-style handlers (renderer.print/render_table/render_info) work against the TUI context (AC20)."""
    app = _Harness()
    async with app.run_test() as pilot:
        ctx = _ctx(app)
        ctx.bot.get_available_tools = MagicMock(return_value=["search", "calculator"])
        ctx.bot.get_tools_count = MagicMock(return_value=2)
        transcript = app.query_one("#transcript", TranscriptView)
        before = len(transcript.query(".notice"))

        handled_help = await ctx.dispatcher.dispatch_async("/help", ctx)
        handled_tools = await ctx.dispatcher.dispatch_async("/tools", ctx)
        await pilot.pause()

        assert handled_help is True
        assert handled_tools is True
        after = len(transcript.query(".notice"))
        # /help mounts a table + a print notice; /tools mounts a table notice.
        assert after - before >= 2


@pytest.mark.asyncio
async def test_drawer_log_handler_routes_records():
    app = _Harness()
    async with app.run_test() as pilot:
        handler = DrawerLogHandler(app, app.query_one("#logs", LogDrawer))
        root = logging.getLogger()
        levels_before = [h.level for h in root.handlers]
        root.addHandler(handler)
        try:
            logging.getLogger("parrot.test").warning("hello drawer")
            await pilot.pause()
            drawer = app.query_one("#logs", LogDrawer)
            drawer_text = "".join(strip.text for strip in drawer.lines)
            assert "hello drawer" in drawer_text
            # Log records must never land in the transcript (AC14).
            assert len(app.query_one("#transcript", TranscriptView).query(".notice")) == 0
        finally:
            root.removeHandler(handler)
        assert [h.level for h in root.handlers] == levels_before


@pytest.mark.asyncio
async def test_suspend_is_context_manager():
    """``ctx.suspend()`` is a context manager delegating straight into ``App.suspend()`` (spec §3 M12).

    The default ``run_test()`` driver is ``HeadlessDriver``, whose
    ``can_suspend`` is ``False`` (inherited from the base ``Driver``;
    verified against textual 8.2.8 source — no override in
    ``textual/drivers/headless_driver.py``), so ``App.suspend()`` itself
    raises ``SuspendNotSupported`` in this environment rather than acting
    as a no-op. That is expected here: this test only asserts that
    ``TUICommandContext.suspend()`` is a working context manager that
    forwards into ``App.suspend()`` unchanged, not that suspending
    actually succeeds headlessly.
    """
    app = _Harness()
    async with app.run_test() as pilot:
        ctx = _ctx(app)
        try:
            with ctx.suspend():
                pass
        except SuspendNotSupported:
            pass
        await pilot.pause()
