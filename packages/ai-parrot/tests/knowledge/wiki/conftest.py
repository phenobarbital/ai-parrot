"""Shared fixtures for the packaged wiki CLI/tool/MCP tests."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_parrot_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``PARROT_HOME`` at a temp dir for every test (FEAT-450).

    The global namespace registry lives at ``PARROT_HOME/wikis.json``;
    a developer's real one must never federate into the test suite.

    Returns:
        The isolated parrot home (usually empty).
    """
    home = tmp_path_factory.mktemp("parrot-home")
    monkeypatch.setenv("PARROT_HOME", str(home))
    return home


# ---------------------------------------------------------------------------
# Shared Jira fixtures (FEAT-454) — wrap tests/fixtures/jira_payloads.py
# (introduced by TASK-2399) so this package's suites (jira_render, jira_sync)
# can reuse the same raw payload without duplicating it.
# ---------------------------------------------------------------------------


@pytest.fixture
def raw_issue() -> dict:
    from tests.fixtures.jira_payloads import raw_issue_payload

    return raw_issue_payload()


@pytest.fixture
def remote_links() -> list[dict]:
    from tests.fixtures.jira_payloads import remote_links_payload

    return remote_links_payload()


@pytest.fixture
def frozen_now():
    """Fixed timestamp so byte-comparisons in jira_render/jira_sync tests
    are stable. Reuses TASK-2401's local fixture shape (packages/ai-parrot/
    tests/knowledge/wiki/test_jira_render.py) so both suites share one
    definition."""
    from datetime import UTC, datetime

    return datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def issues_dir(tmp_path):
    """Empty corpus root for the Jira sweep suite (TASK-2403); assertions
    run against rendered bytes on disk."""
    d = tmp_path / "issues"
    d.mkdir()
    return d
