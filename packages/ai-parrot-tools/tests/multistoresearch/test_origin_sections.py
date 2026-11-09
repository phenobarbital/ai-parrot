"""Request-local multi-origin section diagnostics regressions."""

import asyncio
from typing import Any, Optional

import pytest

from parrot.models import OriginHit, OriginSection, SearchOriginKind
from parrot_tools.multistoresearch import MultiStoreSearchToolkit
from parrot_tools.multistoresearch.origins.base import SearchOrigin


def _hit(origin: str, content: str) -> OriginHit:
    """Build one normalized vector-origin hit."""
    return OriginHit(
        id=content,
        content=content,
        origin=origin,
        origin_kind=SearchOriginKind.VECTOR,
        native_rank=1,
    )


class RequestLocalSectionOrigin(SearchOrigin):
    """Return query-specific section notes after two calls overlap."""

    name = "configured"
    kind = SearchOriginKind.VECTOR
    description = "configured description"

    def __init__(self) -> None:
        self._entered = 0
        self._both_entered = asyncio.Event()

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Provide the abstract legacy interface for this test origin."""
        return [_hit(self.name, query)][:k]

    async def search_section(self, query: str, k: int) -> OriginSection:
        """Return request-local diagnostics with intentionally wrong identity."""
        self._entered += 1
        if self._entered == 2:
            self._both_entered.set()
        await asyncio.wait_for(self._both_entered.wait(), timeout=1.0)
        return OriginSection(
            origin="returned",
            origin_kind=SearchOriginKind.WIKI,
            description="returned description",
            status="ok",
            note=f"note for {query}",
            hits=[_hit(self.name, query)][:k],
        )


class LegacyDuckOrigin:
    """Search-only origin that does not inherit from SearchOrigin."""

    name = "legacy-duck"
    kind = SearchOriginKind.VECTOR
    description = "legacy duck description"
    supports_fts = False
    timeout: Optional[float] = None

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Return legacy list-shaped search results."""
        return [_hit(self.name, query)][:k]


class FtsOrigin(SearchOrigin):
    """Expose a distinct FTS path that must bypass search_section."""

    name = "fts"
    kind = SearchOriginKind.WIKI
    description = "fts description"
    supports_fts = True

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Return native search hits."""
        return [_hit(self.name, f"search:{query}")][:k]

    async def search_section(self, query: str, k: int) -> OriginSection:
        """Fail if the FTS dispatcher incorrectly selects the section hook."""
        raise AssertionError("FTS must not use search_section")

    async def fts_search(self, query: str, k: int) -> list[OriginHit]:
        """Return full-text hits."""
        return [
            OriginHit(
                id=query,
                content=f"fts:{query}",
                origin=self.name,
                origin_kind=self.kind,
                native_rank=1,
            )
        ][:k]


class FailingOrigin(SearchOrigin):
    """Raise a backend error from the default section wrapper."""

    name = "failing"
    kind = SearchOriginKind.VECTOR
    description = "failing description"

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Raise a representative backend failure."""
        raise RuntimeError("backend failed")


class CancellableOrigin(SearchOrigin):
    """Record cancellation caused by the toolkit timeout."""

    name = "slow"
    kind = SearchOriginKind.VECTOR
    description = "slow description"

    def __init__(self) -> None:
        self.timeout = 0.01
        self.cancelled = asyncio.Event()

    async def search(self, query: str, k: int) -> list[OriginHit]:
        """Wait indefinitely until wait_for cancels this search."""
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return []


@pytest.mark.asyncio
async def test_concurrent_section_notes_are_isolated() -> None:
    """Two queries preserve their own notes and configured origin identity."""
    toolkit = MultiStoreSearchToolkit(origins=[RequestLocalSectionOrigin()])

    first, second = await asyncio.gather(
        toolkit.store_search("first"),
        toolkit.store_search("second"),
    )

    assert first.sections[0].note == "note for first"
    assert second.sections[0].note == "note for second"
    for response in (first, second):
        section = response.sections[0]
        assert section.origin == "configured"
        assert section.origin_kind is SearchOriginKind.VECTOR
        assert section.description == "configured description"


@pytest.mark.asyncio
async def test_legacy_fts_and_timeout_compatibility() -> None:
    """Legacy origins, FTS and cancellation retain the existing contracts."""
    slow = CancellableOrigin()
    origins: list[Any] = [LegacyDuckOrigin(), FailingOrigin(), slow]
    toolkit = MultiStoreSearchToolkit(origins=origins)

    response = await toolkit.store_search("query")
    sections = {section.origin: section for section in response.sections}

    assert sections["legacy-duck"].status == "ok"
    assert sections["legacy-duck"].note is None
    assert sections["legacy-duck"].hits[0].content == "query"
    assert sections["failing"].status == "error"
    assert "RuntimeError" in (sections["failing"].note or "")
    assert sections["slow"].status == "timeout"
    assert slow.cancelled.is_set()

    fts_origins: list[Any] = [FtsOrigin(), LegacyDuckOrigin()]
    fts_response = await MultiStoreSearchToolkit(origins=fts_origins).fts_search(
        "terms"
    )
    fts_sections = {section.origin: section for section in fts_response.sections}

    assert fts_sections["fts"].status == "ok"
    assert fts_sections["fts"].hits[0].content == "fts:terms"
    assert fts_sections["legacy-duck"].status == "skipped"

    default_section = await SearchOrigin.search_section(FtsOrigin(), "native", 1)
    assert default_section.status == "ok"
    assert default_section.note is None
    assert default_section.hits[0].content == "search:native"
