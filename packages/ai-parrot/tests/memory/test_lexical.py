"""Shared normalization and real episodic fallback regression tests."""

from pathlib import Path

import pytest

from parrot.memory.episodic.backends.sqlite import SQLiteEpisodeBackend
from parrot.memory.episodic.models import EpisodeCategory, EpisodeOutcome, MemoryNamespace
from parrot.memory.episodic.store import EpisodicMemoryStore
from parrot.memory.lexical import query_terms


def test_query_terms_strips_punctuation_and_short_terms() -> None:
    """Spanish punctuation yields cuál, capital and australia."""
    assert query_terms("¿Cuál es la capital de Australia?") == ("cuál", "capital", "australia")
    assert query_terms("¡¿?!") == ()


def test_query_terms_blank_and_duplicates() -> None:
    """Blank input yields no terms; duplicate case variants retain first-seen order."""
    assert query_terms("") == ()
    assert query_terms("Alpha ALPHA beta? BETA gamma") == ("alpha", "beta", "gamma")


@pytest.mark.asyncio
async def test_fallback_lexical_search_ignores_punctuation(tmp_path: Path) -> None:
    """A real stored Australia episode matches australia?."""
    backend = SQLiteEpisodeBackend(tmp_path / "episodes.sqlite")
    await backend.configure()
    try:
        store = EpisodicMemoryStore(backend, default_ttl_days=0)
        namespace = MemoryNamespace(agent_id="memory-test", user_id="user-test")
        episode = await store.record_episode(
            namespace=namespace,
            situation="Find Australia's capital.",
            action_taken="Answered Canberra.",
            outcome=EpisodeOutcome.SUCCESS,
            category=EpisodeCategory.TOOL_EXECUTION,
        )

        results = await store.recall_similar("Australia?", namespace, score_threshold=0.3)

        assert [result.episode_id for result in results] == [episode.episode_id]
    finally:
        await backend.close()
