"""FormDesigner lazy command registration — FEAT-650 TASK-4204."""

from __future__ import annotations

import importlib

import click
import pytest

from parrot.cli import cli


def test_lazy_entry_registered() -> None:
    """The command and its optional-extra hint are registered."""
    assert cli._lazy_commands["formdesigner"] == "parrot_formdesigner.cli"
    assert "parrot-formdesigner" in cli._lazy_extras["formdesigner"]


def test_missing_satellite_gives_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing satellite receives the command-specific installation hint."""
    original_import = importlib.import_module

    def boom(name: str, *args, **kwargs):
        """Raise the same ImportError shape as an absent satellite."""
        if name == "parrot_formdesigner.cli":
            raise ImportError("no", name="parrot_formdesigner")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("parrot.cli.importlib.import_module", boom)
    with pytest.raises(click.ClickException, match="requires parrot-formdesigner"):
        cli.get_command(None, "formdesigner")
