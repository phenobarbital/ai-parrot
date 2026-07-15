"""Tests for the ``parrot llmwiki`` CLI command (FEAT-260).

Drives the Click command end-to-end with :class:`click.testing.CliRunner`
against a real, temp-populated SQLite wiki plane — no mocks: the store is
fast enough to exercise for real, mirroring ``test_store.py``.
"""

import asyncio
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from parrot.knowledge.wiki.cli import _parse_inline_args, llmwiki
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store


@pytest.fixture
def populated_wiki(tmp_path: Path) -> Path:
    """A SQLite wiki rooted at ``tmp_path`` seeded with two pages.

    Args:
        tmp_path: Pytest-provided temporary directory.

    Returns:
        The storage root (holds ``wiki.db``).
    """
    store = create_wiki_store(tmp_path, backend="sqlite")
    pages = [
        WikiPageRecord(
            concept_id="crew",
            title="AgentCrew Orchestration",
            category="summary",
            summary="Parallel, sequential, flow and loop crew execution.",
            body="# AgentCrew\n\nOrchestrates agents in a crew.",
        ),
        WikiPageRecord(
            concept_id="memory",
            title="Redis Memory",
            category="concept",
            summary="Conversation memory backed by Redis.",
            body="# Memory\n\nRedis-backed conversation memory.",
        ),
    ]
    asyncio.run(store.upsert_pages(pages))
    return tmp_path


def test_parse_inline_args_valid():
    """Recognised ``key=value`` tokens are parsed into an override map."""
    assert _parse_inline_args(("limit=5", "category=summary")) == {
        "limit": "5",
        "category": "summary",
    }


def test_parse_inline_args_rejects_unknown_key():
    """An unknown inline key raises a Click usage error."""
    with pytest.raises(Exception) as exc:
        _parse_inline_args(("foo=1",))
    assert "Unknown inline option" in str(exc.value)


def test_parse_inline_args_rejects_non_kv():
    """A bare token (no ``=``) raises a Click usage error."""
    with pytest.raises(Exception) as exc:
        _parse_inline_args(("bareword",))
    assert "expected key=value" in str(exc.value)


def test_llmwiki_basic_search(populated_wiki: Path):
    """Query returns a rendered table containing the matching title."""
    runner = CliRunner()
    result = runner.invoke(
        llmwiki,
        ["agent crew orchestration", "--store", str(populated_wiki)],
    )
    assert result.exit_code == 0, result.output
    assert "AgentCrew Orchestration" in result.output


def test_llmwiki_inline_limit(populated_wiki: Path):
    """The ``limit=N`` shorthand is honoured alongside --store."""
    runner = CliRunner()
    result = runner.invoke(
        llmwiki,
        ["crew", "limit=1", "--store", str(populated_wiki), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload) == 1
    assert payload[0]["concept_id"] == "crew"


def test_llmwiki_category_filter(populated_wiki: Path):
    """A category filter restricts the result set."""
    runner = CliRunner()
    result = runner.invoke(
        llmwiki,
        ["memory", "--category", "concept", "--store", str(populated_wiki), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(row["category"] == "concept" for row in payload)


def test_llmwiki_body_flag_hydrates_top_hit(populated_wiki: Path):
    """The --body flag hydrates the full markdown body of the top hit."""
    runner = CliRunner()
    result = runner.invoke(
        llmwiki,
        ["crew", "--body", "--store", str(populated_wiki), "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "Orchestrates agents in a crew" in payload[0]["body"]


def test_llmwiki_missing_db_errors(tmp_path: Path):
    """A missing wiki.db yields a friendly non-zero exit."""
    runner = CliRunner()
    result = runner.invoke(
        llmwiki, ["anything", "--store", str(tmp_path / "empty")]
    )
    assert result.exit_code != 0
    assert "No wiki database found" in result.output


def test_llmwiki_no_matches(populated_wiki: Path):
    """A query with no hits exits cleanly with a friendly message."""
    runner = CliRunner()
    result = runner.invoke(
        llmwiki,
        ["zzzznomatchzzzz", "--store", str(populated_wiki)],
    )
    assert result.exit_code == 0, result.output
    assert "No wiki pages matched" in result.output
