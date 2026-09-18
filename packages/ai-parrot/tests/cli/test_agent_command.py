"""CliRunner tests for the `parrot agent` entry point (FEAT-573 AC1/AC2/AC22/AC27)."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner  # verified: test_integration.py:15

from parrot.cli.agent_repl import agent as agent_cmd  # verified: test_integration.py:17
from parrot.cli.modes import SessionPointer  # verified: parrot/cli/modes.py:33


def _loader_returning(bot):
    loader = AsyncMock()
    loader.load = AsyncMock(return_value=bot)
    loader.list_agents = AsyncMock(return_value=[])
    return loader


def _bot():
    bot = MagicMock()
    bot.name = "a"
    bot.get_tools_count.return_value = 0
    bot.has_tools.return_value = False
    bot.cleanup = AsyncMock()
    # A plain MagicMock() would auto-vivify `_credentials` as a non-iterable
    # MagicMock, so `bot_declares_o365_device_code` (identity.py:123) blows up
    # iterating it. Pin it to an empty list — this bot declares no o365
    # device-code credential (feedback: unisolated-real-home-in-tests — none
    # of these tests reach `cli_state_dir()`/PARROT_HOME, so no isolation is
    # needed here; verified by tracing each test's guard order below).
    bot._credentials = []
    return bot


def test_user_with_server_refused_exit_2():
    # Refused before any loader/network call (Q8 check happens before the picker/load).
    result = CliRunner().invoke(agent_cmd, ["a", "--server", "http://x", "--user", "bob"])
    assert result.exit_code == 2 and "PARROT_SERVER_TOKEN" in result.output  # AC27


def test_non_tty_without_name_exit_2():
    # CliRunner stdin/stdout are never TTYs; the picker must never open (AC2).
    with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as cls:
        cls.return_value = _loader_returning(_bot())
        result = CliRunner().invoke(agent_cmd, [])
    assert result.exit_code == 2 and "agent name required" in result.output  # AC2


def test_ui_tui_on_non_tty_exit_2():
    with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as cls:
        cls.return_value = _loader_returning(_bot())
        result = CliRunner().invoke(agent_cmd, ["a", "--ui", "tui"])
    assert result.exit_code == 2


def test_inline_batch_does_not_import_tui():
    sys.modules.pop("parrot.cli.tui", None)
    sys.modules.pop("parrot.cli.tui.app", None)
    with (
        patch("parrot.cli.agent_repl.StandaloneAgentLoader") as cls,
        patch("parrot.cli.agent_repl.AgentREPL") as repl_cls,
    ):
        cls.return_value = _loader_returning(_bot())
        repl_cls.return_value.run_batch = AsyncMock(return_value=0)
        result = CliRunner().invoke(agent_cmd, ["a", "--ui", "inline"], input="hi\n")
    assert result.exit_code == 0 and "parrot.cli.tui" not in sys.modules  # AC22


def test_session_last_resolves_pointer():
    pointer = SessionPointer(agent_name="a", last_session_id="s-1")
    with (
        patch("parrot.cli.agent_repl.StandaloneAgentLoader") as cls,
        patch("parrot.cli.agent_repl.AgentREPL") as repl_cls,
        patch("parrot.cli.agent_repl.load_session_pointer", return_value=pointer),
    ):
        cls.return_value = _loader_returning(_bot())
        repl_cls.return_value.run_batch = AsyncMock(return_value=0)
        result = CliRunner().invoke(agent_cmd, ["a", "--session", "last"], input="hi\n")
    assert result.exit_code == 0
    _, kwargs = repl_cls.call_args
    config = kwargs["config"]
    assert config.session_id == "s-1"  # AC9
    assert config.resume_session_id == "s-1"  # AC9


def test_list_unchanged_exit_zero():
    with patch("parrot.cli.agent_repl.StandaloneAgentLoader") as cls:
        cls.return_value = _loader_returning(_bot())
        assert CliRunner().invoke(agent_cmd, ["--list"]).exit_code == 0
