"""Contract tests for the SearchOrigin ABC (FEAT-379)."""
import pytest

from parrot.models import SearchOriginKind
from parrot_tools.multistoresearch.origins import SearchOrigin


def test_search_origin_is_abstract():
    """SearchOrigin cannot be instantiated directly."""
    with pytest.raises(TypeError):
        SearchOrigin()


async def test_fts_search_default_raises_not_implemented():
    """The default fts_search raises NotImplementedError for non-FTS adapters."""

    class MinimalOrigin(SearchOrigin):
        name = "minimal"
        kind = SearchOriginKind.VECTOR
        description = "minimal test origin"
        supports_fts = False

        async def search(self, query, k):
            return []

    origin = MinimalOrigin()
    with pytest.raises(NotImplementedError):
        await origin.fts_search("q", 5)


async def test_search_must_be_implemented():
    """Subclasses must implement search()."""

    class MinimalOrigin(SearchOrigin):
        name = "minimal"
        kind = SearchOriginKind.VECTOR
        description = "minimal test origin"

        async def search(self, query, k):
            return []

    origin = MinimalOrigin()
    assert await origin.search("q", 5) == []
