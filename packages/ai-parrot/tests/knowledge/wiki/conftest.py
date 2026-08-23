"""Shared fixtures for the packaged wiki CLI/tool/MCP tests."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_parrot_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Point ``PARROT_HOME`` at a temp dir for every test (FEAT-450).

    The global namespace registry lives at ``PARROT_HOME/wikis.json``;
    a developer's real one must never federate into the test suite.

    Returns:
        The isolated parrot home (usually empty).
    """
    home = tmp_path_factory.mktemp("parrot-home")
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home
