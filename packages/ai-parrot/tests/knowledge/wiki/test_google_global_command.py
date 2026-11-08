"""FEAT-838 — `_global_parrot_command` prefers the installed managed launcher (issue:e92e5f160cdd)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from parrot.knowledge.wiki.google import assets
from parrot.knowledge.wiki.google.installer import _global_parrot_command

_LOGGER = "parrot.knowledge.wiki.google.installer"


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """HOME / PARROT_HOME / PATH under tmp_path; PATH holds only this repository's venv ``parrot``."""
    home = tmp_path / "home"
    home.mkdir()
    parrot_home = tmp_path / "parrot-home"
    root = tmp_path / "repo"
    repo_parrot = _executable(root / ".venv" / "bin" / "parrot")
    other_parrot = _executable(tmp_path / "other-repo" / ".venv" / "bin" / "parrot")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PARROT_HOME", str(parrot_home))
    monkeypatch.setenv("PATH", str(repo_parrot.parent))
    return {"parrot_home": parrot_home, "root": root, "repo_parrot": repo_parrot, "other_parrot": other_parrot}


def _install_launcher(parrot_home: Path, *, venv: bool = True) -> None:
    """Fake managed install: the ``bin/`` shim and (optionally) the managed venv script."""
    _executable(parrot_home / "bin" / "parrot")
    if venv:
        _executable(parrot_home / "venv" / "bin" / "parrot")


def _entry(command: str | Path) -> dict:
    return {"command": str(command), "args": ["mcp-local", "memory"]}


def test_installed_launcher_shadowed_on_path_returns_bare_parrot(env: dict[str, Path]) -> None:
    _install_launcher(env["parrot_home"])
    existing = {"parrot-memory": _entry(env["other_parrot"])}

    assert _global_parrot_command(env["root"], existing) == "parrot"


def test_launcher_shim_without_managed_venv_is_not_installed(env: dict[str, Path]) -> None:
    _install_launcher(env["parrot_home"], venv=False)

    assert _global_parrot_command(env["root"], {}) == str(env["repo_parrot"])


def test_inherits_foreign_command_with_warning(env: dict[str, Path], caplog: pytest.LogCaptureFixture) -> None:
    existing = {"parrot-memory": _entry(env["other_parrot"])}

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        command = _global_parrot_command(env["root"], existing)

    assert command == str(env["other_parrot"])
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert str(env["other_parrot"]) in warnings[0].getMessage()
    assert "parrot-memory" in warnings[0].getMessage()


def test_inherited_command_inside_root_no_warning(env: dict[str, Path], caplog: pytest.LogCaptureFixture) -> None:
    existing = {"parrot-memory": _entry(env["repo_parrot"])}

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        command = _global_parrot_command(env["root"], existing)

    assert command == str(env["repo_parrot"])
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]


def test_falls_back_to_repo_binary(env: dict[str, Path]) -> None:
    assert _global_parrot_command(env["root"], {}) == assets.resolve_binary(env["root"], "parrot")
    assert _global_parrot_command(env["root"], {}) == str(env["repo_parrot"])
