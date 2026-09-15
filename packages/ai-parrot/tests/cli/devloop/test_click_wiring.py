"""Click wiring tests for ``parrot devloop``."""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner


def test_devloop_help_no_conf_import():
    """``parrot devloop --help`` renders without importing parrot.conf.

    Restores the original ``sys.modules["parrot.conf"]`` afterward
    (rather than leaving it popped, or letting it be re-imported fresh
    later) — an unrestored pop leaves any module that already did
    ``from parrot import conf`` before this test (e.g.
    ``parrot.flows.dev_flow.nodes.ideation``) holding a stale reference
    to the ORIGINAL module object, while a later ``monkeypatch.setattr``
    that re-imports ``parrot.conf`` fresh (after the pop) mutates a
    DIFFERENT object — the two never observe each other's changes again
    for the rest of the pytest session. Found by the FEAT-555 code
    review pass (cross-test pollution: every
    ``test_ideation_node.py::doc``-fixture test failed with a spurious
    ``conf.PROJECT_ROOT`` when collected alongside this test).
    """
    original = sys.modules.pop("parrot.conf", None)
    try:
        from parrot.cli.devloop import devloop

        runner = CliRunner()
        result = runner.invoke(devloop, ["--help"])
        assert result.exit_code == 0
        assert "Interactive CLI console" in result.output
        assert "parrot.conf" not in sys.modules
    finally:
        if original is not None:
            sys.modules["parrot.conf"] = original


def test_devloop_run_help():
    from parrot.cli.devloop import devloop

    runner = CliRunner()
    result = runner.invoke(devloop, ["run", "--help"])
    assert result.exit_code == 0
    assert "--brief" in result.output
    assert "--yes" in result.output


def test_devloop_revise_help():
    from parrot.cli.devloop import devloop

    runner = CliRunner()
    result = runner.invoke(devloop, ["revise", "--help"])
    assert result.exit_code == 0
    assert "--brief" in result.output


def test_lazygroup_resolves_devloop():
    """LazyGroup can resolve the 'devloop' command from _lazy_commands."""
    from parrot.cli import cli

    assert "devloop" in cli._lazy_commands
    ctx = MagicMock()
    cmd = cli.get_command(ctx, "devloop")
    assert cmd is not None
    assert cmd.name == "devloop"


def test_run_brief_yes_invokes_console(tmp_path):
    """``run --brief x.yaml --yes`` calls DevLoopConsole.start(brief_file=...)."""
    brief = tmp_path / "brief.yaml"
    brief.write_text("kind: bug\nsummary: test\n")

    mock_console_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.start = AsyncMock(return_value=0)
    mock_console_cls.return_value = mock_instance

    from parrot.cli.devloop import devloop

    runner = CliRunner()
    with patch("parrot.cli.devloop.console.DevLoopConsole", mock_console_cls):
        result = runner.invoke(devloop, ["run", "--brief", str(brief), "--yes"])

    assert result.exit_code == 0
    mock_instance.start.assert_called_once()
    call_kwargs = mock_instance.start.call_args
    assert call_kwargs[1].get("brief_file") == str(brief) or call_kwargs[0][0] == str(brief)


def test_revise_flag_passthrough():
    """``revise`` calls console.start(revision=True)."""
    mock_console_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.start = AsyncMock(return_value=0)
    mock_console_cls.return_value = mock_instance

    from parrot.cli.devloop import devloop

    runner = CliRunner()
    with patch("parrot.cli.devloop.console.DevLoopConsole", mock_console_cls):
        result = runner.invoke(devloop, ["revise"])

    assert result.exit_code == 0
    mock_instance.start.assert_called_once()
    call_kwargs = mock_instance.start.call_args
    assert call_kwargs[1].get("revision") is True or (
        len(call_kwargs[0]) > 1 and call_kwargs[0][1] is True
    )


def test_bare_devloop_invokes_run():
    """Bare ``parrot devloop`` (no subcommand) delegates to ``run``."""
    mock_console_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.start = AsyncMock(return_value=0)
    mock_console_cls.return_value = mock_instance

    from parrot.cli.devloop import devloop

    runner = CliRunner()
    with patch("parrot.cli.devloop.console.DevLoopConsole", mock_console_cls):
        result = runner.invoke(devloop, [])

    assert result.exit_code == 0
    mock_console_cls.assert_called_once()
