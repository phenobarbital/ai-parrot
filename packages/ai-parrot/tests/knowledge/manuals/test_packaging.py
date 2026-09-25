"""FEAT-601 M13 — lazy CLI registration and the ``manuals`` extra (TASK-3728)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from parrot.cli import cli

REPO_ROOT = Path(__file__).resolve().parents[5]
CORE_PYPROJECT = REPO_ROOT / "packages" / "ai-parrot" / "pyproject.toml"


def test_cli_group_registered_lazily() -> None:
    """`manuals` resolves to its Click group and exposes its public commands."""
    assert cli._lazy_commands["manuals"] == "parrot_tools.procedures.cli"
    assert "ai-parrot[manuals]" in cli._lazy_extras["manuals"]

    pytest.importorskip("parrot_tools.procedures.cli")
    result = CliRunner().invoke(cli, ["manuals", "--help"])

    assert result.exit_code == 0, result.output
    for command_name in ("add", "add-video", "refresh", "verify", "queue", "relink-tips", "export", "spike"):
        assert command_name in result.output


def test_cli_missing_satellite_gives_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable tools satellite reports the manuals installation hint."""

    def raise_missing_satellite(module_path: str) -> None:
        """Simulate the absent optional ``parrot_tools`` distribution."""
        raise ImportError("No module named 'parrot_tools'", name="parrot_tools")

    monkeypatch.setattr("parrot.cli.importlib.import_module", raise_missing_satellite)

    with pytest.raises(click.ClickException, match=r"ai-parrot\[manuals\]"):
        cli.get_command(click.Context(cli), "manuals")


def test_manuals_extra_self_reference() -> None:
    """The manuals extra reuses graphindex and bookstore without duplicating rapidfuzz."""
    extras = tomllib.loads(CORE_PYPROJECT.read_text())["project"]["optional-dependencies"]
    assert extras["manuals"] == ["ai-parrot[graphindex,bookstore]"]
    holders = [name for name, items in extras.items() if any("rapidfuzz" in item for item in items)]
    assert holders == ["graphindex"], holders
