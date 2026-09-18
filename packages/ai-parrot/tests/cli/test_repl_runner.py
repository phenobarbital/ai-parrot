"""AgentREPL-on-TurnRunner tests (FEAT-573 TASK-3407, spec §4)."""
from __future__ import annotations

import asyncio
import io
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console  # verified: renderer.py:13

from parrot.cli.repl import AgentREPL, REPLConfig  # verified: repl.py:61, :92
from parrot.cli.renderer import ResponseRenderer  # verified: repl.py:23
from parrot.cli.console import set_console  # provided by TASK-3400


@pytest.fixture
def quiet_renderer():
    console = Console(file=io.StringIO(), force_terminal=False, width=100)
    set_console(console)
    yield ResponseRenderer(console=console), console
    set_console(None)


@pytest.mark.asyncio
async def test_repl_no_logger_level_mutation(mock_agent, quiet_renderer):
    renderer, _ = quiet_renderer
    before = [(id(h), h.level) for h in logging.getLogger().handlers]
    repl = AgentREPL(mock_agent, REPLConfig(agent_name="t", streaming=True), renderer)
    await repl.send_stream("hi")
    assert [(id(h), h.level) for h in logging.getLogger().handlers] == before   # AC14


@pytest.mark.asyncio
async def test_repl_run_batch_plain_output(mock_agent, quiet_renderer):
    renderer, console = quiet_renderer
    repl = AgentREPL(mock_agent, REPLConfig(agent_name="t", streaming=True, history_enabled=False), renderer)
    code = await repl.run_batch(["hello", "", "/info", "again"])
    out = console.file.getvalue()
    assert code == 0 and "\x1b[2K" not in out and "\x1b[?1049h" not in out   # AC2
    assert len(repl.history) == 2


@pytest.mark.asyncio
async def test_repl_file_history_used_when_enabled(mock_agent, quiet_renderer, tmp_path, monkeypatch):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    renderer, _ = quiet_renderer
    with patch("parrot.cli.repl.PromptSession") as ps:
        ps.return_value.prompt_async.side_effect = EOFError
        await AgentREPL(mock_agent, REPLConfig(agent_name="my agent"), renderer).run()
    history = ps.call_args.kwargs["history"]
    assert type(history).__name__ == "FileHistory"
    assert str(tmp_path / "cli" / "history") in str(history.filename)

    with patch("parrot.cli.repl.PromptSession") as ps2:
        ps2.return_value.prompt_async.side_effect = EOFError
        await AgentREPL(
            mock_agent, REPLConfig(agent_name="my agent", history_enabled=False), renderer
        ).run()
    history2 = ps2.call_args.kwargs["history"]
    assert type(history2).__name__ == "InMemoryHistory"


@pytest.mark.asyncio
async def test_repl_ctrl_c_cancels_active_turn(quiet_renderer):
    renderer, console = quiet_renderer
    started = asyncio.Event()
    call_count = 0

    async def _slow_stream(**kwargs):  # noqa: ARG001
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield "first chunk "
            started.set()
            await asyncio.sleep(10)
            yield "never reached"
        else:
            yield "second turn output"

    bot = AsyncMock()
    bot.name = "slow_bot"
    bot.ask_stream = MagicMock(side_effect=lambda **kw: _slow_stream(**kw))
    bot.ask = AsyncMock(return_value=MagicMock(output="ok", response="ok", tool_calls=[], usage=None))

    repl = AgentREPL(bot, REPLConfig(agent_name="slow", streaming=True), renderer)

    task = asyncio.create_task(repl._turn_with_cancel("hello"))
    await asyncio.wait_for(started.wait(), timeout=5)
    repl.runner.cancel()
    await asyncio.wait_for(task, timeout=5)

    out = console.file.getvalue()
    assert "Interrupted" in out         # AC18
    assert len(repl.history) == 0       # cancelled turn is never recorded

    # A following send_stream still works.
    await repl.send_stream("again")
    assert len(repl.history) == 1


@pytest.mark.asyncio
async def test_repl_post_turn_hook_called(mock_agent, quiet_renderer):
    renderer, _ = quiet_renderer
    repl = AgentREPL(mock_agent, REPLConfig(agent_name="t", streaming=False), renderer)
    calls = []

    async def hook(ctx, turn):
        calls.append(turn.query)
        assert ctx is repl   # AC15 — hook observes the REPL's CommandContext, not the bare TurnRunner

    repl.add_post_turn_hook(hook)
    await repl.send("hello")
    assert calls == ["hello"]   # AC15
