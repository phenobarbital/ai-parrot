"""Focused FEAT-626 regression and failure-path tests."""

import asyncio
import hashlib
from pathlib import Path

import pytest

from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.documents import AcquiredDocument, DocumentMetadata, DocumentRef
from parrot.knowledge.wiki.inbox.models import ResolvedClassification, VerifiedLink
from parrot.knowledge.wiki.inbox.pages import DocPageWriter, INBOX_ASSERTED_BY
from parrot.knowledge.wiki.project import WikiProjectConfig
from parrot.knowledge.wiki.review import DimensionScores, ManifestDocEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


def _classification(kind: str = "decision") -> ResolvedClassification:
    return ResolvedClassification(
        kind=kind,
        category="concept",
        title="Inbox decision",
        summary="Use a stable inbox document page.",
        tags=["inbox", "decision"],
        entities=[],
        event_date=None,
        classification_source="model",
    )


def _triage(path: Path) -> ManifestDocEntry:
    return ManifestDocEntry(
        source_uri=str(path),
        file_hash="manifest-hash",
        briefing="brief",
        scores=DimensionScores(density=1, novelty=1, durability=1),
        composite=1,
        proposed_action="admit",
        decision="admit",
        decision_source="model",
    )


async def _writer(
    tmp_path: Path, source_path: Path
) -> tuple[DocPageWriter, SQLiteWikiStore, SourceCollectionManager, str]:
    store = SQLiteWikiStore(tmp_path / "wiki.db")
    sources = SourceCollectionManager(tmp_path / "sources")
    entry = await asyncio.to_thread(sources.add_source, source_path)
    return DocPageWriter(store, sources, WikiBookkeeper(), tmp_path), store, sources, entry.source_id


@pytest.mark.asyncio
async def test_write_doc_page_edges(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert authored origin, source_id=None, provenance and source identity in frontmatter."""
    source = tmp_path / "source.md"
    source.write_text("source text\n")
    writer, store, sources, source_id = await _writer(tmp_path, source)
    await store.replace_source_slice(source_id, [WikiPageRecord(concept_id="child:1", source_id=source_id)])
    await asyncio.to_thread(sources.mark_ingested, source_id, ["child:1"])
    acquired = AcquiredDocument(
        ref=DocumentRef(uri=str(source)), text="source text", metadata=DocumentMetadata(extra={"keep": "yes"})
    )
    await writer.write_doc_page(
        "doc:1",
        source_id,
        _classification(),
        acquired,
        _triage(source),
        "v1",
        [VerifiedLink(page_id="other", rel="references", why="x", title="Other")],
        False,
    )
    page = await store.get_page("doc:1")
    assert (
        page and page["origin"] == "authored" and page["source_id"] is None and page["asserted_by"] == INBOX_ASSERTED_BY
    )
    assert (
        f"source_id: {source_id}" in page["body"]
        and "file_hash: manifest-hash" in page["body"]
        and acquired.metadata.extra == {"keep": "yes"}
    )
    assert {tuple(edge.values()) for edge in await store.dump_edges()} >= {
        ("child:1", "doc:1", "part_of"),
        ("doc:1", "other", "references"),
    }


@pytest.mark.asyncio
async def test_ensure_tags_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repeated tags create neither duplicate nodes nor edges."""
    source = tmp_path / "source.md"
    source.write_text("x")
    writer, store, _, _ = await _writer(tmp_path, source)
    await writer.ensure_tags("doc:1", ["one", "one"])
    await writer.ensure_tags("doc:1", ["one"])
    assert [page["concept_id"] for page in await store.dump_pages()].count("tag:one") == 1
    assert len([edge for edge in await store.dump_edges() if edge["dst"] == "tag:one"]) == 1


@pytest.mark.asyncio
async def test_emit_adr_candidate_only_for_decisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only enabled decision documents save valid inferred candidates."""
    source = tmp_path / "source.md"
    source.write_bytes(b"raw source\n")
    writer, store, _, _ = await _writer(tmp_path, source)
    acquired = AcquiredDocument(ref=DocumentRef(uri=str(source)), text="raw source", metadata=DocumentMetadata())
    assert await writer.emit_adr_candidate(
        "doc:1", _classification("note"), acquired, "source.md", WikiProjectConfig()
    ) == (None, False)
    decision_id, reused = await writer.emit_adr_candidate(
        "doc:1", _classification(), acquired, "source.md", WikiProjectConfig()
    )
    assert decision_id and not reused
    record_page = await store.get_page(decision_id)
    assert record_page and hashlib.sha1(b"raw source\n").hexdigest() in record_page["body"]


@pytest.mark.asyncio
async def test_emit_adr_candidate_never_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Repository failures are logged without failing the document."""
    source = tmp_path / "missing.md"
    store = SQLiteWikiStore(tmp_path / "wiki.db")
    writer = DocPageWriter(store, SourceCollectionManager(tmp_path / "sources"), WikiBookkeeper(), tmp_path)
    acquired = AcquiredDocument(ref=DocumentRef(uri=str(source)), text="x", metadata=DocumentMetadata())
    assert await writer.emit_adr_candidate("doc:1", _classification(), acquired, "missing.md", WikiProjectConfig()) == (
        None,
        False,
    )


@pytest.mark.asyncio
async def test_emit_adr_candidate_reuses_existing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preserve an existing reviewed record and report reuse."""
    source = tmp_path / "source.md"
    source.write_text("raw")
    writer, _, _, _ = await _writer(tmp_path, source)
    acquired = AcquiredDocument(ref=DocumentRef(uri=str(source)), text="raw", metadata=DocumentMetadata())
    first, _ = await writer.emit_adr_candidate("doc:1", _classification(), acquired, "source.md", WikiProjectConfig())
    second, reused = await writer.emit_adr_candidate(
        "doc:1", _classification(), acquired, "source.md", WikiProjectConfig()
    )
    assert first == second and reused


@pytest.mark.asyncio
async def test_doc_page_survives_reingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the child source slice and retain the doc page and inbound relations."""
    source = tmp_path / "source.md"
    source.write_text("raw")
    writer, store, _, source_id = await _writer(tmp_path, source)
    await store.replace_source_slice(source_id, [WikiPageRecord(concept_id="child:1", source_id=source_id)])
    await asyncio.to_thread(writer.sources.mark_ingested, source_id, ["child:1"])
    acquired = AcquiredDocument(ref=DocumentRef(uri=str(source)), text="raw", metadata=DocumentMetadata())
    await writer.write_doc_page("doc:1", source_id, _classification(), acquired, _triage(source), "v1", [], False)
    await store.add_edges([("external:1", "child:1", "references", "asserted")])
    await store.replace_source_slice(source_id, [WikiPageRecord(concept_id="child:1", source_id=source_id)])
    assert await store.get_page("doc:1") is not None
    assert any(edge["src"] == "external:1" and edge["dst"] == "child:1" for edge in await store.dump_edges())
