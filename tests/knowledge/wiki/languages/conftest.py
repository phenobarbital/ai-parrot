"""Shared fixtures for the wiki language-scanner test suite (FEAT-394)."""

from __future__ import annotations

import pytest
from parrot.knowledge.wiki.languages import treesitter


@pytest.fixture
def force_heuristic(monkeypatch):
    """Force every scanner onto its heuristic path for this test.

    Monkeypatches :func:`parrot.knowledge.wiki.languages.treesitter.get_parser`
    to always return ``None`` and clears its cache afterwards, so tests can
    deterministically exercise the stdlib-only fallback regardless of
    whether the optional ``ai-parrot[wiki-languages]`` extra (and its
    grammar wheels) happen to be installed in the environment running
    the suite.
    """
    monkeypatch.setattr(treesitter, "get_parser", lambda language: None)
    yield
