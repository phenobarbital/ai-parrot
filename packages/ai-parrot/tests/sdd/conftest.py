"""Shared fixtures for the SDD tests: keep installs out of the developer's real home directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from parrot.knowledge.wiki.google import assets as google_assets
from parrot.sdd import installer

# Captured when pytest imports this conftest, before any test changes HOME.
_REAL_HOME = Path.home()


@pytest.fixture
def real_home() -> Path:
    """The developer's home directory as it was before any test changed HOME."""
    return _REAL_HOME


@pytest.fixture(autouse=True)
def _isolate_user_level_configs(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the google host's user-level files at a throwaway home unless the test fakes HOME itself.

    A google-host install merges agy permission rules into ``~/.gemini/antigravity-cli/settings.json`` (and the
    snap copy, with an ownership record beside each) and registers MCP servers in
    ``~/.gemini/config/mcp_config.json``. Without this fixture every local run of an install test edits the
    developer's real files; CI never showed it because its runner has no agy. A test that sets HOME keeps the
    normal lookup, which then follows its fake home.
    """
    created: list[Path] = []

    def throwaway_home() -> Path:
        if not created:
            created.append(tmp_path_factory.mktemp("user-home"))
        return created[0]

    agy_candidates = installer._agy_candidates
    mcp_config_path = google_assets.default_mcp_config_path

    def isolated_agy_candidates() -> list[Path]:
        if Path.home() == _REAL_HOME:
            return [throwaway_home() / relative for relative in installer._AGY_SETTINGS]
        return agy_candidates()

    def isolated_mcp_config_path() -> Path:
        if Path.home() == _REAL_HOME:
            return throwaway_home() / ".gemini" / "config" / "mcp_config.json"
        return mcp_config_path()

    monkeypatch.setattr(installer, "_agy_candidates", isolated_agy_candidates)
    monkeypatch.setattr(google_assets, "default_mcp_config_path", isolated_mcp_config_path)
