"""Tests for expert wiki namespace probing and LLM-free seeding (FEAT-778 M5)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.experts.knowledge.budget import sha256_revision
from parrot.experts.knowledge.sources.wiki import WikiSource
from parrot.experts.models import (
    ExpertBundle,
    ExpertKnowledgeError,
    ExpertManifest,
    KnowledgeMode,
    KnowledgeSourceKind,
    KnowledgeSourceSpec,
)
from parrot.knowledge.wiki.file_store import InMemoryWikiStore
from parrot.knowledge.wiki.store import WikiPageRecord


class CharacterCounter:
    """Deterministic token counter for wiki source tests."""

    name = "characters"

    def count(self, text: str) -> int:
        """Return the number of characters in the supplied text."""
        return len(text)


class FakeWiki:
    """Toolkit-shaped wrapper around one shared wiki store."""

    def __init__(self, store: object) -> None:
        """Initialize the fake toolkit with a store or raised exception."""
        self._store = store
        self.ingest_source = MagicMock()

    def _store_for(self, name: str) -> object:
        """Return the shared store, or raise the configured exception."""
        if isinstance(self._store, Exception):
            raise self._store
        return self._store


class ReadOnlyStore(InMemoryWikiStore):
    """In-memory store that rejects every write."""

    def _assert_writable(self) -> None:
        """Reject writes as a read-only backend would."""
        raise PermissionError("read only")


def _source(tmp_path: Path, namespace: str = "expert-alpha") -> tuple[WikiSource, InMemoryWikiStore, FakeWiki]:
    """Build a source over a shared in-memory store."""
    store = InMemoryWikiStore(tmp_path / "wiki")
    toolkit = FakeWiki(store)
    return WikiSource(toolkit, namespace=namespace, counter=CharacterCounter()), store, toolkit


def _bundle(tmp_path: Path) -> ExpertBundle:
    """Build a minimal valid expert bundle for layer generation."""
    return ExpertBundle(
        manifest=ExpertManifest(
            name="sample-expert",
            display_name="Sample Expert",
            description="Wiki source test bundle",
            knowledge=[KnowledgeSourceSpec(source=KnowledgeSourceKind.WIKI, mode=KnowledgeMode.RETRIEVAL)],
        ),
        root=tmp_path,
        identity_dir=tmp_path / "identity",
    )


@pytest.mark.asyncio
async def test_probe_counts_only_own_prefix(tmp_path: Path) -> None:
    """Probe excludes pages belonging to another namespace in the same store."""
    source, store, toolkit = _source(tmp_path)
    await store.upsert_pages(
        [
            WikiPageRecord(concept_id="expert-alpha/one"),
            WikiPageRecord(concept_id="expert-alpha/two"),
            WikiPageRecord(concept_id="expert-beta/one"),
        ]
    )

    assert await source.probe() == 2
    toolkit.ingest_source.assert_not_called()


@pytest.mark.asyncio
async def test_seed_records_shape(tmp_path: Path) -> None:
    """Seeded records carry deterministic identity, provenance, hashes, and tokens."""
    source, store, toolkit = _source(tmp_path)
    file = tmp_path / "guide.md"
    data = b"# Incident Guide\n\nAssess the evidence before acting.\n"
    file.write_bytes(data)

    assert await source.seed([file], asserted_by="agent:sample") == 1
    page = await store.get_page("expert-alpha/guide")
    assert page is not None
    assert page["title"] == "Incident Guide"
    assert page["summary"] == "Assess the evidence before acting."
    assert page["category"] == "knowledge"
    assert page["origin"] == "bundle"
    assert page["asserted_by"] == "agent:sample"
    assert page["token_count"] == len(data.decode())
    assert page["content_hash"] == sha256_revision(data)
    toolkit.ingest_source.assert_not_called()


@pytest.mark.asyncio
async def test_seed_is_idempotent(tmp_path: Path) -> None:
    """Re-seeding unchanged files updates the same concept identifiers."""
    source, _store, toolkit = _source(tmp_path)
    files = [tmp_path / "a.md", tmp_path / "b.md"]
    for file in files:
        file.write_text(f"# {file.stem.upper()}\n\nKnowledge.\n", encoding="utf-8")

    assert await source.seed(files, asserted_by="agent:sample") == 2
    assert await source.seed(reversed(files), asserted_by="agent:sample") == 2
    assert await source.probe() == 2
    toolkit.ingest_source.assert_not_called()


@pytest.mark.asyncio
async def test_wiki_source_unresolvable_and_empty_both_raise(tmp_path: Path) -> None:
    """Both an unresolvable store and an empty namespace fail closed."""
    spec = KnowledgeSourceSpec(source=KnowledgeSourceKind.WIKI, mode=KnowledgeMode.RETRIEVAL)
    unresolvable = WikiSource(FakeWiki(RuntimeError("missing")), namespace="expert-alpha", counter=CharacterCounter())
    empty, _store, _toolkit = _source(tmp_path)

    with pytest.raises(ExpertKnowledgeError, match="cannot be resolved"):
        await unresolvable.layers(spec, _bundle(tmp_path), workspace=None, counter=CharacterCounter())
    with pytest.raises(ExpertKnowledgeError, match="empty-wiki-namespace"):
        await empty.layers(spec, _bundle(tmp_path), workspace=None, counter=CharacterCounter())


@pytest.mark.asyncio
async def test_seed_on_read_only_store_raises_not_writable(tmp_path: Path) -> None:
    """A backend write rejection is normalized to the registry's skip reason."""
    source = WikiSource(
        FakeWiki(ReadOnlyStore(tmp_path / "wiki")), namespace="expert-alpha", counter=CharacterCounter()
    )
    file = tmp_path / "guide.md"
    file.write_text("Knowledge.\n", encoding="utf-8")

    with pytest.raises(ExpertKnowledgeError, match="wiki-not-writable"):
        await source.seed([file], asserted_by="agent:sample")


@pytest.mark.asyncio
async def test_layers_handle_shape(tmp_path: Path) -> None:
    """A populated namespace produces the specified deterministic retrieval handle."""
    source, _store, toolkit = _source(tmp_path)
    file = tmp_path / "guide.md"
    file.write_text("Knowledge.\n", encoding="utf-8")
    await source.seed([file], asserted_by="agent:sample")
    spec = KnowledgeSourceSpec(
        source=KnowledgeSourceKind.WIKI,
        mode=KnowledgeMode.RETRIEVAL,
        scope={"topics": ["security"]},
    )

    layers = await source.layers(spec, _bundle(tmp_path), workspace=None, counter=CharacterCounter())

    assert len(layers) == 1
    layer = layers[0]
    assert layer.source == "wiki:expert-alpha"
    assert layer.mode is KnowledgeMode.RETRIEVAL
    assert layer.tokens == 0
    assert layer.handle == {
        "toolkit": "wiki",
        "wiki_name": "expert-alpha",
        "scope": {"topics": ["security"]},
        "documents": 1,
    }
    assert layer.revision == sha256_revision(
        b'{"documents": 1, "scope": {"topics": ["security"]}, "toolkit": "wiki", "wiki_name": "expert-alpha"}'
    )
    toolkit.ingest_source.assert_not_called()
