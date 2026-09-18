"""End-to-end tests for the agent workspace (FEAT-573 TASK-3416, spec §4 Integration Tests)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from parrot.cli.agent_repl import agent as agent_cmd
from parrot.cli.modes import load_session_pointer


@pytest.fixture(autouse=True)
def _isolated_parrot_home(tmp_path, monkeypatch):
    """Every test in this module drives a real turn through ``TurnRunner.run_turn()``,
    which unconditionally calls ``save_session_pointer()`` (``parrot/cli/modes.py``).
    Isolating ``PARROT_HOME`` (and ``cwd``, for ``/export``'s relative-path writes)
    for every test — not just the "obvious" ones — keeps that write off the real
    developer's ``~/.parrot``.
    """
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)


def _patched_loader(bot):
    loader = AsyncMock()
    loader.load = AsyncMock(return_value=bot)
    return patch("parrot.cli.agent_repl.StandaloneAgentLoader", return_value=loader)


def test_inline_end_to_end_fake_bot(fake_streaming_bot, quiet_console):
    """Two stdin lines and /export in batch (non-TTY) mode → exported JSON has 2 turns (AC2, AC20)."""
    runner = CliRunner()
    with _patched_loader(fake_streaming_bot):
        result = runner.invoke(agent_cmd, ["test_agent", "--ui", "inline"], input="hi\nagain\n/export out.json\n")
    assert result.exit_code == 0, result.output

    with open("out.json", encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data["turns"]) == 2
    # Batch (non-TTY) mode never enters the full-screen alternate-screen buffer.
    assert "\x1b[?1049h" not in result.output


async def test_tui_end_to_end_fake_bot_with_tools(tool_emitting_bot, quiet_console):
    """Workspace shows a tool row while streaming and final tool details + usage (AC6, AC8)."""
    pytest.importorskip("textual")
    from prompt_toolkit.history import InMemoryHistory
    from parrot.cli.commands import SlashCommandDispatcher
    from parrot.cli.repl import REPLConfig
    from parrot.cli.session import TurnRunner
    from parrot.cli.tui.app import AgentWorkspaceApp
    from parrot.cli.tui.widgets import StatusBar, TranscriptView, TurnPanel

    config = REPLConfig(agent_name="test_agent", streaming=True)
    runner = TurnRunner(tool_emitting_bot, config)
    app = AgentWorkspaceApp(
        bot=tool_emitting_bot,
        config=config,
        runner=runner,
        dispatcher=SlashCommandDispatcher(),
        history=InMemoryHistory(),
    )
    async with app.run_test(size=(100, 30)) as pilot:
        await app.submit("compute 2+2")
        await pilot.pause(0.3)

        panel = app.query_one("#transcript", TranscriptView).query_one(TurnPanel)

        # One tool row for MathTool, in the "done" (✓) state (AC6).
        assert len(panel._tools._rows) == 1
        row = next(iter(panel._tools._rows.values()))
        row_text = str(row.content)
        assert "MathTool" in row_text
        assert "✓" in row_text

        # Streamed text ("Hel" + "lo") landed in the transcript (AC6).
        assert panel._assistant.source == "Hello"

        # Status bar shows the final usage, not "n/a" (AC8).
        status = app.query_one("#status", StatusBar)
        assert "tokens: prompt=10" in str(status.content)


def test_resume_roundtrip_standalone(fake_streaming_bot, quiet_console):
    """A turn persisted in InMemoryConversation is rendered again via /resume last (AC9).

    This test exercises the ``/resume <id>`` slash command entry point spec AC9 names
    explicitly; :func:`test_session_last_replays_history_in_batch_mode` below exercises the
    other one (``--session last``). Both share the same ``TurnRunner.load_history()`` /
    ``ResponseRenderer.render_history()`` code path. It reads ``quiet_console.file.getvalue()``
    directly rather than ``result.output``: the ``quiet_console`` fixture installs a
    ``Console(file=io.StringIO(), ...)``, so rendered text never reaches the process's real
    stdout that ``CliRunner`` captures.
    """
    from parrot.memory.abstract import ConversationTurn as MemoryTurn
    from parrot.memory.mem import InMemoryConversation

    memory = InMemoryConversation()
    fake_streaming_bot.conversation_memory = memory
    fake_streaming_bot.memory_key_id = "test_agent"

    async def _get_history(user_id, session_id, chatbot_id=None):
        return await memory.get_history(user_id, session_id, chatbot_id=chatbot_id or "test_agent")

    fake_streaming_bot.get_conversation_history = AsyncMock(side_effect=_get_history)

    runner = CliRunner()
    with _patched_loader(fake_streaming_bot):
        first = runner.invoke(agent_cmd, ["test_agent", "--ui", "inline"], input="remember this\n")
        assert first.exit_code == 0, first.output

        pointer = load_session_pointer("test_agent")
        assert pointer is not None
        session_id = pointer.last_session_id

        async def _seed() -> None:
            await memory.create_history("cli-user", session_id, chatbot_id="test_agent")
            turn = MemoryTurn(
                turn_id="seed-1",
                user_id="cli-user",
                user_message="remember this",
                assistant_response="ok, remembered",
            )
            await memory.add_turn("cli-user", session_id, turn, chatbot_id="test_agent")

        asyncio.run(_seed())

        second = runner.invoke(agent_cmd, ["test_agent", "--ui", "inline"], input="/resume last\n")
        assert second.exit_code == 0, second.output

    output_text = quiet_console.file.getvalue()
    assert "Resumed session" in output_text
    assert "remember this" in output_text


def test_session_last_replays_history_in_batch_mode(fake_streaming_bot, quiet_console):
    """``--session last`` (batch/non-TTY mode) replays prior history, not just ``/resume`` (AC9).

    Regression test for a gap found during review: ``AgentREPL.run_batch()`` used to never
    read ``config.resume_session_id``, so ``--session last`` under a piped/non-TTY invocation
    silently skipped the history replay that the interactive ``run()`` loop always did.
    ``run_batch()`` now mirrors ``run()``'s ``load_history``/``render_history`` call at the
    top of the loop, so this test drives ``--session last`` directly (no ``/resume`` slash
    command) and expects the exact same rendered transcript.
    """
    from parrot.memory.abstract import ConversationTurn as MemoryTurn
    from parrot.memory.mem import InMemoryConversation

    memory = InMemoryConversation()
    fake_streaming_bot.conversation_memory = memory
    fake_streaming_bot.memory_key_id = "test_agent"

    async def _get_history(user_id, session_id, chatbot_id=None):
        return await memory.get_history(user_id, session_id, chatbot_id=chatbot_id or "test_agent")

    fake_streaming_bot.get_conversation_history = AsyncMock(side_effect=_get_history)

    runner = CliRunner()
    with _patched_loader(fake_streaming_bot):
        first = runner.invoke(agent_cmd, ["test_agent", "--ui", "inline"], input="remember this\n")
        assert first.exit_code == 0, first.output

        pointer = load_session_pointer("test_agent")
        assert pointer is not None
        session_id = pointer.last_session_id

        async def _seed() -> None:
            await memory.create_history("cli-user", session_id, chatbot_id="test_agent")
            turn = MemoryTurn(
                turn_id="seed-2",
                user_id="cli-user",
                user_message="remember this",
                assistant_response="ok, remembered",
            )
            await memory.add_turn("cli-user", session_id, turn, chatbot_id="test_agent")

        asyncio.run(_seed())

        # --session last, piped input, no /resume slash command at all.
        second = runner.invoke(agent_cmd, ["test_agent", "--ui", "inline", "--session", "last"], input="ok\n")
        assert second.exit_code == 0, second.output

    output_text = quiet_console.file.getvalue()
    assert "Resumed session" in output_text
    assert "remember this" in output_text
