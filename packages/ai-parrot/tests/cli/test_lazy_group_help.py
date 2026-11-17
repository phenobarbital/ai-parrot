"""`parrot --help` survives uninstalled optional subcommands (FEAT-633 R1)."""

from __future__ import annotations

import sys
import types

import click
import pytest
from click.testing import CliRunner

from parrot.cli import LazyGroup


@pytest.fixture
def group(monkeypatch: pytest.MonkeyPatch) -> click.Group:
    """A lazy group with one importable command and two whose modules are absent."""

    @click.command()
    def ok() -> None:
        """Present command."""

    present = types.ModuleType("parrot_test_present_cli")
    present.ok = ok  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "parrot_test_present_cli", present)

    @click.group(cls=LazyGroup)
    def root() -> None:
        """Root group."""

    root._lazy_commands = {
        "ok": "parrot_test_present_cli",
        "ghost": "parrot_nonexistent_satellite.cli",
        "broken": "parrot_nonexistent_other.cli",
    }
    root._lazy_extras = {"ghost": "ghost-dist: pip install ghost-dist"}
    return root


def test_help_lists_uninstalled_commands_and_exits_zero(group: click.Group) -> None:
    """--help renders every command; an absent one carries its availability message."""
    result = CliRunner().invoke(group, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Present command." in result.output
    assert "ghost" in result.output and "requires ghost-dist" in result.output
    assert "broken" in result.output and "unavailable" in result.output


def test_invoking_uninstalled_command_still_fails_with_hint(group: click.Group) -> None:
    """Direct invocation of an absent command keeps failing with the install hint."""
    result = CliRunner().invoke(group, ["ghost"])
    assert result.exit_code == 1
    assert "requires ghost-dist: pip install ghost-dist" in result.output


def test_real_cli_help_exits_zero() -> None:
    """The real top-level `parrot --help` never exits non-zero, whatever is installed."""
    from parrot.cli import cli

    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0, result.output
    assert "sdd" in result.output and "self" in result.output


def test_completion_offers_uninstalled_commands_without_failing(group: click.Group) -> None:
    """`parrot <TAB>` lists every command; an absent one is marked unavailable instead of aborting completion."""
    ctx = click.Context(group, info_name="root")
    items = {item.value: item.help for item in group.shell_complete(ctx, "")}
    assert items["ok"] == "Present command."
    assert items["ghost"] == "(unavailable)" and items["broken"] == "(unavailable)"
    assert "--help" in {item.value for item in group.shell_complete(ctx, "--")}  # options still complete
