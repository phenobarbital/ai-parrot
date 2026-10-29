"""`parrot self` CLI (FEAT-633, TASK-4080)."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from click.testing import CliRunner

from parrot.cli import cli


def test_self_is_registered() -> None:
    result = CliRunner().invoke(cli, ["self", "--help"])
    assert result.exit_code == 0, result.output
    for sub in ("add", "update", "doctor", "env", "uninstall"):
        assert sub in result.output


def test_self_env_rule_report(tmp_path: Path, monkeypatch) -> None:
    """Spec §4 — `self env` prints the resolved venv and the rule."""
    monkeypatch.setattr("parrot.launcher.resolve_venv", lambda *a, **k: (tmp_path / "venv", "VIRTUAL_ENV"))
    with mock.patch("parrot.self_.doctor.installed_version", return_value="1.2.3"):
        result = CliRunner().invoke(cli, ["self", "env"])
    assert result.exit_code == 0, result.output
    assert str(tmp_path / "venv") in result.output and "VIRTUAL_ENV" in result.output and "1.2.3" in result.output


def test_add_unknown_component_lists_available() -> None:
    result = CliRunner().invoke(cli, ["self", "add", "nope"])
    assert result.exit_code == 1
    assert "available" in result.output


def test_add_passes_here_flag() -> None:
    with mock.patch("parrot.self_.components.install_component", return_value=["ok"]) as install:
        result = CliRunner().invoke(cli, ["self", "add", "scraping", "--here"])
    assert result.exit_code == 0, result.output
    assert install.call_args.kwargs["here"] is True


def test_uninstall_without_yes_prompts_and_aborts() -> None:
    with mock.patch("parrot.self_.components.uninstall_runtime") as uninstall:
        result = CliRunner().invoke(cli, ["self", "uninstall"], input="n\n")
    assert result.exit_code == 0, result.output
    uninstall.assert_not_called()


def test_self_env_init_creates_then_keeps(tmp_path: Path, monkeypatch) -> None:
    """`self env --init` creates the credentials file once and reports it; a rerun keeps it."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ENV", raising=False)
    first = CliRunner().invoke(cli, ["self", "env", "--init"])
    assert first.exit_code == 0, first.output
    target = tmp_path / "home" / "env" / ".env"
    assert f"created credentials file: {target}" in first.output and target.is_file()
    second = CliRunner().invoke(cli, ["self", "env", "--init"])
    assert second.exit_code == 0 and f"kept existing credentials file: {target}" in second.output


def test_self_env_init_reports_errors(tmp_path: Path, monkeypatch) -> None:
    """A refused ENV or an unwritable home exits non-zero with the reason, never a traceback."""
    monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("ENV", "../escape")
    result = CliRunner().invoke(cli, ["self", "env", "--init"])
    assert result.exit_code == 1 and "could not create the credentials file" in result.output
    monkeypatch.delenv("ENV")
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "env").write_text("not a directory", encoding="utf-8")
    result = CliRunner().invoke(cli, ["self", "env", "--init"])
    assert result.exit_code == 1 and "could not create the credentials file" in result.output
