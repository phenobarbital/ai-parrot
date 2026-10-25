"""Extractor with a plain loader and GraphDocument shapes (FEAT-540 M6)."""

from __future__ import annotations

import pytest

from parrot.knowledge.graphindex.extractors.loader import LoaderExtractor
from parrot.knowledge.graphindex.models import DocumentLoader, GraphDocument
from .._support.import_probe import run_import_probe


class _Loader:
    """Plain loader double: no framework Document, no stores import."""

    async def load(self) -> list[GraphDocument]:
        return await self._load("x.md")

    async def _load(self, source: str, **kwargs: object) -> list[GraphDocument]:
        return [GraphDocument(page_content="# Title\nbody", metadata={"source": source})]


def test_plain_loader_satisfies_protocol() -> None:
    """A loader with an async load() conforms to DocumentLoader structurally."""
    assert isinstance(_Loader(), DocumentLoader)


def test_graph_document_defaults() -> None:
    """Metadata is optional and independent per instance."""
    a, b = GraphDocument(page_content="a"), GraphDocument(page_content="b")
    a.metadata["k"] = 1
    assert b.metadata == {}


@pytest.mark.asyncio
async def test_extract_with_plain_loader() -> None:
    """The extractor produces nodes from GraphDocuments returned by a plain loader."""
    nodes, _edges = await LoaderExtractor().extract(_Loader(), "x.md")
    assert nodes


def test_extractor_module_does_not_import_stores_models() -> None:
    """Importing the extractor no longer loads parrot.stores.models."""
    result = run_import_probe("parrot.knowledge.graphindex.extractors.loader")
    assert result.error is None, result.error
    assert not result.has("parrot.stores.models")
