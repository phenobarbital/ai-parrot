"""CommandContext-based dispatcher tests (FEAT-573 TASK-3406, spec §4) — no AgentREPL involved."""
from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.cli.commands import ConversationTurn, SlashCommandDispatcher  # verified: commands.py:38, :70
from parrot.cli.events import BackendCapabilities  # provided by TASK-3403
from parrot.cli.modes import save_session_pointer  # provided by TASK-3401


class _StubCtx:
    """Minimal CommandContext (structural) for tests."""

    def __init__(self, *, resume: bool = True) -> None:
        self.bot = MagicMock(get_available_tools=MagicMock(return_value=["T"]), get_tools_count=MagicMock(return_value=1))
        self.config = SimpleNamespace(agent_name="a", session_id="s-1", user_id="u", streaming=True, server_url=None)
        self.renderer = MagicMock()
        self.dispatcher = SlashCommandDispatcher()
        self.runner = MagicMock()
        self.runner.history = []
        self.runner.capabilities = BackendCapabilities(resume=resume)
        self.runner.reset_session = MagicMock(side_effect=self._reset)
        self.runner.load_history = AsyncMock(return_value=[ConversationTurn(query="q", response=SimpleNamespace(output="o"))])
        self.suspended = 0

    def _reset(self) -> str:
        self.config.session_id = "s-2"
        self.runner.history.clear()
        return "s-2"

    @property
    def history(self):
        return self.runner.history

    @contextlib.contextmanager
    def suspend(self):
        self.suspended += 1
        yield


@pytest.mark.asyncio
async def test_dispatcher_uses_command_context():
    ctx = _StubCtx()
    for text in ("/tools", "/info", "/help"):
        assert await ctx.dispatcher.dispatch_async(text, ctx) is True
    assert await ctx.dispatcher.dispatch_async("/clear", ctx) is True
    ctx.runner.reset_session.assert_called_once()
    assert ctx.config.session_id == "s-2"


@pytest.mark.asyncio
async def test_cmd_resume_last_and_missing_capability(monkeypatch, tmp_path):
    monkeypatch.setenv("PARROT_HOME", str(tmp_path))

    # (a) backend without resume capability: explicit error, load_history never awaited.
    ctx = _StubCtx(resume=False)
    await ctx.dispatcher.dispatch_async("/resume last", ctx)
    printed = [str(call.args[0]) for call in ctx.renderer.print.call_args_list]
    assert any("cannot resume" in text for text in printed)
    ctx.runner.load_history.assert_not_awaited()

    # (b) resume=True: "last" resolves through the pointer file written for this agent.
    save_session_pointer("a", "s-9")
    ctx2 = _StubCtx(resume=True)
    ctx2.runner.load_history = AsyncMock(
        return_value=[ConversationTurn(query="q", response=SimpleNamespace(output="o"))]
    )
    await ctx2.dispatcher.dispatch_async("/resume last", ctx2)
    ctx2.runner.load_history.assert_awaited_once_with("s-9")
    ctx2.renderer.render_history.assert_called_once()
    _, kwargs = ctx2.renderer.render_history.call_args
    assert kwargs.get("session_id") == "s-9"


@pytest.mark.asyncio
async def test_cmd_export_contract_unchanged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _StubCtx()
    ctx.runner.history.append(ConversationTurn(query="hi", response=SimpleNamespace(output="yo", response="yo")))
    assert await ctx.dispatcher.dispatch_async("/export out.json", ctx) is True
    data = json.loads((tmp_path / "out.json").read_text())
    assert set(data) == {"session_id", "agent_name", "user_id", "exported_at", "turns"}


@pytest.mark.asyncio
async def test_quit_raises_system_exit():
    ctx = _StubCtx()
    with pytest.raises(SystemExit):
        await ctx.dispatcher.dispatch_async("/quit", ctx)
    with pytest.raises(SystemExit):
        await ctx.dispatcher.dispatch_async("/exit", ctx)


@pytest.mark.asyncio
async def test_create_agent_usage_runs_inside_suspend():
    ctx = _StubCtx()
    await ctx.dispatcher.dispatch_async("/create_agent", ctx)  # no description → usage message, no factory import
    assert ctx.suspended == 1
