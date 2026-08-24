"""Shared fixtures for the packaged integration test suite."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_parrot_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``PARROT_HOME`` at a temp dir for every integration test.

    Mirrors ``tests/knowledge/wiki/conftest.py``'s fixture of the same
    name (FEAT-450) — critical here because ``ns add --global`` writes
    ``PARROT_HOME/wikis.json``; without this, the FEAT-454 end-to-end
    suite would mutate the developer's real global namespace registry.

    Returns:
        The isolated parrot home (usually empty).
    """
    home = tmp_path_factory.mktemp("parrot-home")
    monkeypatch.setenv("PARROT_HOME", str(home))
    monkeypatch.delenv("JIRA_WIKI_ISSUES_DIR", raising=False)
    return home
