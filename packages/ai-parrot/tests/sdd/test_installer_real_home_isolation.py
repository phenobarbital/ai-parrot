"""A google-host install run by the test suite must never edit the developer's real home directory.

Guards the autouse fixture in ``conftest.py``: before it, local runs of the install tests merged agy rules and
``/tmp/pytest-of-*`` repositories into the developer's agy settings and wrote ``~/.gemini/config/mcp_config.json``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from parrot.knowledge.wiki.google import assets as google_assets
from parrot.sdd import installer
from parrot.sdd.installer import install_sdd_integration


def _user_level_files(home: Path) -> list[Path]:
    settings = [home / relative for relative in installer._AGY_SETTINGS]
    ownership = [path.with_name(installer.AGY_OWNERSHIP_NAME) for path in settings]
    return [*settings, *ownership, home / ".gemini" / "config" / "mcp_config.json"]


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    return {path: path.read_bytes() if path.is_file() else None for path in paths}


def test_google_install_leaves_the_real_home_untouched(tmp_path: Path, real_home: Path) -> None:
    """The install writes its user-level MCP config, but into the throwaway home, never the real one."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    before = _snapshot(_user_level_files(real_home))

    install_sdd_integration(repo, hosts=("google",))

    assert _snapshot(_user_level_files(real_home)) == before
    redirected = google_assets.default_mcp_config_path()
    assert not redirected.is_relative_to(real_home)
    assert redirected.is_file(), "the google install should have written its MCP config to the throwaway home"
    assert all(not path.is_relative_to(real_home) for path in installer._agy_candidates())


def test_a_faked_home_keeps_the_normal_lookup(tmp_path: Path, monkeypatch) -> None:
    """A test that sets HOME itself still gets paths under that HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    assert installer._agy_candidates() == [tmp_path / relative for relative in installer._AGY_SETTINGS]
    assert google_assets.default_mcp_config_path() == tmp_path / ".gemini" / "config" / "mcp_config.json"
