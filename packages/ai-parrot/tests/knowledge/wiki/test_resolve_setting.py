"""resolve_setting precedence (FEAT-540 M4)."""

from __future__ import annotations

import builtins
import logging

import pytest
from click.testing import CliRunner

from parrot.knowledge.graphindex.protocols import ProviderNotAvailable
from parrot.knowledge.wiki import cli
from parrot.knowledge.wiki.project import WikiProjectConfig, resolve_arango_params, resolve_setting


def test_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit value wins over every ambient configuration source."""
    monkeypatch.setenv("X_KEY", "env")
    assert resolve_setting("X_KEY", explicit="arg") == "arg"


@pytest.mark.parametrize("value", [False, 0, ""])
def test_falsey_explicit_preserved(value: object) -> None:
    """Falsey explicit values are settings, rather than missing values."""
    assert resolve_setting("X_KEY", explicit=value) == value


def test_empty_environment_value_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment membership preserves an explicitly empty value."""
    monkeypatch.setenv("X_KEY", "")
    assert resolve_setting("X_KEY", default="fallback") == ""


def test_precedence_and_project_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolver uses environment, navconfig, project, then default."""
    monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: {"X_KEY": "nav"})
    monkeypatch.setenv("X_KEY", "env")
    assert resolve_setting("X_KEY", project_defaults={"X_KEY": "project"}, default="default") == "env"
    monkeypatch.delenv("X_KEY")
    assert resolve_setting("X_KEY", project_defaults={"X_KEY": "project"}, default="default") == "nav"
    monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: None)
    assert resolve_setting("X_KEY", project_defaults={"X_KEY": "project"}, default="default") == "project"
    assert resolve_setting("X_KEY", default="default") == "default"


def test_broken_navconfig_falls_through_without_values_in_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken optional navconfig import is debug-only and falls through."""
    original_import = builtins.__import__

    def broken_navconfig_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "navconfig":
            raise RuntimeError("credential-value-must-not-be-logged")
        return original_import(name, *args, **kwargs)

    monkeypatch.delenv("X_KEY", raising=False)
    monkeypatch.setattr(builtins, "__import__", broken_navconfig_import)
    caplog.set_level(logging.DEBUG, logger="parrot.knowledge.wiki.project")

    assert resolve_setting("X_KEY", default="fallback") == "fallback"
    assert "navconfig unavailable" in caplog.text
    assert "credential-value-must-not-be-logged" not in caplog.text


def test_arango_requires_explicit_host_without_echoing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Arango configuration refuses the implicit loopback host."""
    monkeypatch.setattr("parrot.knowledge.wiki.project._navconfig", lambda: None)
    monkeypatch.delenv("ARANGODB_HOST", raising=False)
    monkeypatch.setenv("ARANGODB_PASSWORD", "top-secret")

    with pytest.raises(ValueError, match="ARANGODB_HOST") as exc_info:
        resolve_arango_params(WikiProjectConfig(wiki_name="test"))

    assert "127.0.0.1" not in str(exc_info.value)
    assert "top-secret" not in str(exc_info.value)


def test_main_maps_provider_not_available_to_exit_two(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The console entry point reports unavailable providers as a usage failure."""
    runner = CliRunner()

    def unavailable_provider() -> None:
        raise ProviderNotAvailable("test", "ai-parrot", "test")

    monkeypatch.setattr(cli, "wiki", unavailable_provider)
    with runner.isolation() as (_, stderr, _):
        with pytest.raises(SystemExit) as exc_info:
            cli.main()

    assert exc_info.value.code == 2
    assert "No test provider is configured" in stderr.getvalue().decode()
