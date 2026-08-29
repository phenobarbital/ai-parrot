"""Unit tests for SourceCollectionManager (TASK-1629)."""

from pathlib import Path

import pytest
from parrot.knowledge.wiki.models import SourceManifestEntry
from parrot.knowledge.wiki.sources import SourceCollectionManager


@pytest.fixture
def sources_dir(tmp_path: Path) -> Path:
    """Create a temporary sources directory."""
    d = tmp_path / "sources"
    d.mkdir()
    return d


@pytest.fixture
def sample_source(sources_dir: Path) -> Path:
    """Create a sample markdown source file."""
    f = sources_dir / "article.md"
    f.write_text("# Test Article\n\nContent here.")
    return f


class TestSourceCollectionManager:
    """Tests for SourceCollectionManager."""

    def test_add_source_returns_entry(self, sources_dir: Path, sample_source: Path):
        """add_source returns a SourceManifestEntry with the correct URI."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert entry.source_uri == str(sample_source.resolve())
        assert entry.source_id.startswith("src-")
        assert len(entry.file_hash) == 40  # SHA-1 hex

    def test_add_source_hash_is_sha1(self, sources_dir: Path, sample_source: Path):
        """file_hash is a valid 40-character SHA-1 hex string."""
        import hashlib

        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        # Verify by recomputing manually
        h = hashlib.sha1()
        h.update(sample_source.read_bytes())
        assert entry.file_hash == h.hexdigest()

    def test_add_source_mtime_recorded(self, sources_dir: Path, sample_source: Path):
        """mtime is recorded as a float from the file's st_mtime."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        expected_mtime = sample_source.stat().st_mtime
        assert entry.mtime == pytest.approx(expected_mtime)

    def test_list_sources_empty_initially(self, sources_dir: Path):
        """list_sources returns an empty list for a fresh manager."""
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.list_sources() == []

    def test_list_sources_after_add(self, sources_dir: Path, sample_source: Path):
        """list_sources returns one entry after adding a source."""
        mgr = SourceCollectionManager(sources_dir)
        mgr.add_source(sample_source)
        assert len(mgr.list_sources()) == 1

    def test_get_source_found(self, sources_dir: Path, sample_source: Path):
        """get_source returns the correct entry for a known source_id."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        fetched = mgr.get_source(entry.source_id)
        assert fetched is not None
        assert fetched.source_id == entry.source_id

    def test_get_source_not_found(self, sources_dir: Path):
        """get_source returns None for an unknown source_id."""
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.get_source("nonexistent-id") is None

    def test_is_stale_false_for_fresh_source(self, sources_dir: Path, sample_source: Path):
        """is_stale returns False immediately after add_source."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert not mgr.is_stale(entry.source_id)

    def test_is_stale_true_after_content_change(self, sources_dir: Path, sample_source: Path):
        """is_stale returns True when the file content changes."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        # Modify content (also updates mtime)
        sample_source.write_text("# Updated Content\n\nDifferent text.")
        assert mgr.is_stale(entry.source_id)

    def test_is_stale_true_for_missing_file(self, sources_dir: Path, sample_source: Path):
        """is_stale returns True when the source file is deleted."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        sample_source.unlink()
        assert mgr.is_stale(entry.source_id)

    def test_is_stale_true_for_unknown_id(self, sources_dir: Path):
        """is_stale returns True for a source_id not in the manifest."""
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.is_stale("unknown-src-id")

    def test_manifest_persistence(self, sources_dir: Path, sample_source: Path):
        """Manifest is persisted to disk and loaded by a new manager instance."""
        mgr = SourceCollectionManager(sources_dir)
        mgr.add_source(sample_source)

        # Create a second manager that reads from the same directory
        mgr2 = SourceCollectionManager(sources_dir)
        sources = mgr2.list_sources()
        assert len(sources) == 1
        assert sources[0].source_uri == str(sample_source.resolve())

    def test_registry_db_exists_after_add(self, sources_dir: Path, sample_source: Path):
        """The shared wiki.db registry is created after the first add_source."""
        mgr = SourceCollectionManager(sources_dir)
        mgr.add_source(sample_source)
        assert mgr.db_path.exists()
        assert mgr.db_path == sources_dir.parent / "wiki.db"

    def test_legacy_json_manifest_migrated(self, sources_dir: Path, sample_source: Path):
        """A legacy .manifest.json is imported into SQLite and renamed."""
        import json

        sources_dir.mkdir(parents=True, exist_ok=True)
        legacy_entry = {
            "src-legacy000001": {
                "source_id": "src-legacy000001",
                "source_uri": str(sample_source),
                "file_hash": "deadbeef" * 5,
                "mtime": 1.0,
                "ingested_at": "2026-01-01T00:00:00Z",
                "pages_generated": ["0001"],
                "status": "ingested",
            }
        }
        (sources_dir / ".manifest.json").write_text(json.dumps(legacy_entry))
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.get_source("src-legacy000001")
        assert entry is not None
        assert entry.pages_generated == ["0001"]
        assert not (sources_dir / ".manifest.json").exists()
        assert (sources_dir / ".manifest.json.bak").exists()

    def test_mark_ingested_updates_pages(self, sources_dir: Path, sample_source: Path):
        """mark_ingested stores the pages_generated list in the manifest."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        updated = mgr.mark_ingested(entry.source_id, pages_generated=["page-1", "page-2"])
        assert updated is not None
        assert updated.pages_generated == ["page-1", "page-2"]

    def test_mark_ingested_unknown_id(self, sources_dir: Path):
        """mark_ingested returns None for an unknown source_id."""
        mgr = SourceCollectionManager(sources_dir)
        result = mgr.mark_ingested("nonexistent", pages_generated=[])
        assert result is None

    def test_remove_source(self, sources_dir: Path, sample_source: Path):
        """remove_source deletes the entry from the manifest."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        removed = mgr.remove_source(entry.source_id)
        assert removed is True
        assert mgr.get_source(entry.source_id) is None
        assert len(mgr.list_sources()) == 0

    def test_remove_source_unknown(self, sources_dir: Path):
        """remove_source returns False for an unknown source_id."""
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.remove_source("does-not-exist") is False

    def test_deterministic_source_id(self, sources_dir: Path, sample_source: Path):
        """Adding the same file twice yields the same source_id."""
        mgr = SourceCollectionManager(sources_dir)
        e1 = mgr.add_source(sample_source)
        e2 = mgr.add_source(sample_source)
        assert e1.source_id == e2.source_id

    def test_add_source_file_not_found(self, sources_dir: Path):
        """add_source raises FileNotFoundError for a non-existent file."""
        mgr = SourceCollectionManager(sources_dir)
        with pytest.raises(FileNotFoundError):
            mgr.add_source(sources_dir / "ghost.md")

    def test_sources_dir_created_automatically(self, tmp_path: Path):
        """SourceCollectionManager creates sources_dir if it does not exist."""
        new_dir = tmp_path / "auto_created"
        assert not new_dir.exists()
        SourceCollectionManager(new_dir)
        assert new_dir.exists()


class TestJsonBackend:
    """SourceCollectionManager with backend='json' (memory-backend wikis)."""

    def test_manifest_file_exists_after_add(self, sources_dir: Path, sample_source: Path):
        mgr = SourceCollectionManager(sources_dir, backend="json")
        mgr.add_source(sample_source)
        assert (sources_dir / ".manifest.json").exists()
        assert not mgr.db_path.exists()  # no wiki.db in json mode

    def test_persistence_across_managers(self, sources_dir: Path, sample_source: Path):
        first = SourceCollectionManager(sources_dir, backend="json")
        entry = first.add_source(sample_source)
        first.mark_ingested(entry.source_id, pages_generated=["0001"])

        second = SourceCollectionManager(sources_dir, backend="json")
        reloaded = second.get_source(entry.source_id)
        assert reloaded is not None
        assert reloaded.pages_generated == ["0001"]
        assert second.find_by_uri(entry.source_uri) == entry.source_id

    def test_remove_source(self, sources_dir: Path, sample_source: Path):
        mgr = SourceCollectionManager(sources_dir, backend="json")
        entry = mgr.add_source(sample_source)
        assert mgr.remove_source(entry.source_id) is True
        assert mgr.get_source(entry.source_id) is None
        assert mgr.remove_source("nope") is False

    def test_is_stale_json_mode(self, sources_dir: Path, sample_source: Path):
        mgr = SourceCollectionManager(sources_dir, backend="json")
        entry = mgr.add_source(sample_source)
        assert mgr.is_stale(entry.source_id) is False
        sample_source.write_text("changed content")
        assert mgr.is_stale(entry.source_id) is True

    def test_unknown_backend_rejected(self, sources_dir: Path):
        with pytest.raises(ValueError, match="Unknown sources backend"):
            SourceCollectionManager(sources_dir, backend="parquet")


class TestDecisionColumnsMigration:
    """FEAT-402 (TASK-2073): additive `sources` migration for decision columns."""

    def test_sources_migration_old_db(self, tmp_path: Path):
        """A pre-FEAT-402 (7-column) sources table opens cleanly and gains
        the new decision columns with safe (NULL) defaults; existing rows
        are preserved unchanged."""
        import sqlite3

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        db_path = sources_dir.parent / "wiki.db"

        # Manually create an OLD 7-column sources table (pre-FEAT-402 DDL)
        # with one pre-existing row, simulating a database created before
        # this migration existed.
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE sources (
                source_id       TEXT PRIMARY KEY,
                source_uri      TEXT NOT NULL UNIQUE,
                file_hash       TEXT NOT NULL,
                mtime           REAL NOT NULL,
                ingested_at     TEXT NOT NULL,
                pages_generated TEXT NOT NULL DEFAULT '[]',
                status          TEXT NOT NULL DEFAULT 'ingested'
            )
            """)
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "src-old000001",
                "/docs/legacy.md",
                "deadbeef" * 5,
                1.0,
                "2025-01-01T00:00:00Z",
                "[]",
                "ingested",
            ),
        )
        conn.commit()
        conn.close()

        # Opening a manager against this pre-existing DB must not raise,
        # and must additively migrate the schema (new columns only).
        mgr = SourceCollectionManager(sources_dir, db_path=db_path)

        raw_conn = sqlite3.connect(str(db_path))
        columns = {row[1] for row in raw_conn.execute("PRAGMA table_info(sources)")}
        raw_conn.close()
        assert {
            "destination",
            "decision_source",
            "charter_version",
            "composite_score",
        } <= columns

        entry = mgr.get_source("src-old000001")
        assert entry is not None
        assert entry.status == "ingested"  # pre-existing row untouched
        assert entry.destination is None
        assert entry.decision_source is None
        assert entry.charter_version is None
        assert entry.composite_score is None

    def test_sources_migration_idempotent(self, tmp_path: Path):
        """Opening the same DB twice does not error or duplicate columns."""
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        SourceCollectionManager(sources_dir)
        # Second open must not raise (idempotent ALTER TABLE guard).
        SourceCollectionManager(sources_dir)

    def test_new_db_has_decision_columns_from_ddl(self, sources_dir: Path, sample_source: Path):
        """A brand-new database already has the decision columns via the DDL."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert entry.destination is None
        assert entry.decision_source is None
        assert entry.charter_version is None
        assert entry.composite_score is None


class TestRecordDecision:
    """FEAT-402 (TASK-2073): SourceCollectionManager.record_decision."""

    def test_sources_persist_decision(self, sources_dir: Path, sample_source: Path):
        """destination/decision_source/charter_version/composite persist
        and round-trip through SourceManifestEntry."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.record_decision(
            sample_source,
            destination="wiki",
            decision_source="model",
            charter_version="1",
            composite_score=0.82,
            pages_generated=["page-1"],
        )
        assert entry.destination == "wiki"
        assert entry.decision_source == "model"
        assert entry.charter_version == "1"
        assert entry.composite_score == pytest.approx(0.82)
        assert entry.status == "ingested"
        assert entry.pages_generated == ["page-1"]

        fetched = mgr.get_source(entry.source_id)
        assert fetched is not None
        assert fetched.destination == "wiki"
        assert fetched.decision_source == "model"
        assert fetched.charter_version == "1"
        assert fetched.composite_score == pytest.approx(0.82)

    def test_sources_rejected_no_pages(self, sources_dir: Path, sample_source: Path):
        """A discard decision is recorded with status='rejected' and no pages."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.record_decision(
            sample_source,
            destination="discard",
            decision_source="heuristic",
        )
        assert entry.status == "rejected"
        assert entry.pages_generated == []
        assert entry.destination == "discard"

        fetched = mgr.get_source(entry.source_id)
        assert fetched is not None
        assert fetched.status == "rejected"
        assert fetched.pages_generated == []

    def test_record_decision_creates_untracked_source(self, sources_dir: Path, sample_source: Path):
        """record_decision works even when the source was never add_source'd
        — the typical case for a rejected document (spec §2)."""
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.list_sources() == []

        entry = mgr.record_decision(sample_source, destination="archive", decision_source="auto")
        assert entry is not None
        assert len(mgr.list_sources()) == 1

    def test_record_decision_updates_existing_source(self, sources_dir: Path, sample_source: Path):
        """record_decision updates an already-tracked source in place
        rather than creating a duplicate row."""
        mgr = SourceCollectionManager(sources_dir)
        added = mgr.add_source(sample_source)

        updated = mgr.record_decision(
            sample_source,
            destination="wiki",
            decision_source="model",
            pages_generated=["p1"],
        )
        assert updated.source_id == added.source_id
        assert len(mgr.list_sources()) == 1

    def test_record_decision_archive_defaults_to_ingested_status(self, sources_dir: Path, sample_source: Path):
        """An 'archive' destination defaults to status='ingested' (it does
        become a wiki page, just excluded from default ranking)."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.record_decision(sample_source, destination="archive")
        assert entry.status == "ingested"


class TestFormatDecisionLogDetails:
    """FEAT-402 (TASK-2073): format_decision_log_details bookkeeper helper."""

    def test_format_includes_key_fields(self, sources_dir: Path, sample_source: Path):
        from parrot.knowledge.wiki.sources import format_decision_log_details

        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.record_decision(
            sample_source,
            destination="wiki",
            decision_source="model",
            charter_version="2",
            composite_score=0.913,
        )
        details = format_decision_log_details(entry)
        assert entry.source_uri in details
        assert "0.9130" in details
        assert "decision_source: model" in details
        assert "charter_version: 2" in details

    def test_format_handles_missing_composite(self, sources_dir: Path, sample_source: Path):
        from parrot.knowledge.wiki.sources import format_decision_log_details

        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.record_decision(sample_source, destination="discard")
        details = format_decision_log_details(entry)
        assert "composite: n/a" in details


class TestDocumentMetadataColumns:
    """FEAT-451 (TASK-2355): additive `sources` migration for document metadata."""

    def test_sources_migration_old_db(self, tmp_path: Path):
        """A pre-FEAT-451 (11-column, post-FEAT-402) sources table opens
        cleanly and gains the new document-metadata columns with safe
        (NULL) defaults; existing rows are preserved unchanged."""
        import sqlite3

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        db_path = sources_dir.parent / "wiki.db"

        # Manually create a pre-FEAT-451 (post-FEAT-402, 11-column) sources
        # table with one pre-existing row, simulating a database created
        # before this feature's migration existed.
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE sources (
                source_id        TEXT PRIMARY KEY,
                source_uri       TEXT NOT NULL UNIQUE,
                file_hash        TEXT NOT NULL,
                mtime            REAL NOT NULL,
                ingested_at      TEXT NOT NULL,
                pages_generated  TEXT NOT NULL DEFAULT '[]',
                status           TEXT NOT NULL DEFAULT 'ingested',
                destination      TEXT,
                decision_source  TEXT,
                charter_version  TEXT,
                composite_score  REAL
            )
            """)
        conn.execute(
            "INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "src-old000002",
                "/docs/legacy2.md",
                "cafebabe" * 5,
                1.0,
                "2025-06-01T00:00:00Z",
                "[]",
                "ingested",
                None,
                None,
                None,
                None,
            ),
        )
        conn.commit()
        conn.close()

        # Opening a manager against this pre-existing DB must not raise,
        # and must additively migrate the schema (new columns only).
        mgr = SourceCollectionManager(sources_dir, db_path=db_path)

        raw_conn = sqlite3.connect(str(db_path))
        columns = {row[1] for row in raw_conn.execute("PRAGMA table_info(sources)")}
        raw_conn.close()
        assert {"doc_metadata", "content_type", "loader"} <= columns

        rows = mgr.list_sources()
        assert rows and all(r.doc_metadata is None for r in rows)

        entry = mgr.get_source("src-old000002")
        assert entry is not None
        assert entry.status == "ingested"  # pre-existing row untouched
        assert entry.doc_metadata is None
        assert entry.content_type is None
        assert entry.loader is None

    def test_sources_migration_idempotent(self, tmp_path: Path):
        """Opening the same DB twice does not error or duplicate columns."""
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        mgr = SourceCollectionManager(sources_dir)
        # Second call must not raise (idempotent ALTER TABLE guard).
        mgr._migrate_sources_columns()

    def test_new_db_has_document_columns_from_migration(self, sources_dir: Path, sample_source: Path):
        """A brand-new database already has the document metadata columns
        (added by the additive migration that always runs at __init__)."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert entry.doc_metadata is None
        assert entry.content_type is None
        assert entry.loader is None

    def test_doc_metadata_roundtrip(self, sources_dir: Path, sample_source: Path):
        """doc_metadata round-trips as an equal dict through _upsert/get_source."""
        mgr = SourceCollectionManager(sources_dir)
        added = mgr.add_source(sample_source)
        entry = SourceManifestEntry(
            **{
                **added.model_dump(),
                "doc_metadata": {"author": "Legal", "page_count": 42},
                "content_type": "application/pdf",
                "loader": "MarkdownLoader",
            }
        )
        mgr._upsert(entry)

        got = mgr.get_source(entry.source_id)
        assert got is not None
        assert got.doc_metadata == {"author": "Legal", "page_count": 42}
        assert got.content_type == "application/pdf"
        assert got.loader == "MarkdownLoader"

    def test_corrupt_doc_metadata_degrades_to_none(self, sources_dir: Path, sample_source: Path):
        """A bad JSON cell must not break list_sources()/get_source()."""
        import sqlite3

        mgr = SourceCollectionManager(sources_dir)
        added = mgr.add_source(sample_source)

        with sqlite3.connect(str(mgr.db_path)) as conn:
            conn.execute(
                "UPDATE sources SET doc_metadata = ? WHERE source_id = ?",
                ("{not valid json", added.source_id),
            )

        entry = mgr.get_source(added.source_id)
        assert entry is not None
        assert entry.doc_metadata is None

        rows = mgr.list_sources()
        assert any(r.source_id == added.source_id for r in rows)

    def test_arango_doc_metadata_roundtrip(self, tmp_path: Path):
        """The same doc_metadata/content_type/loader round-trip holds on
        the Arango backend (_doc_to_entry / _async_upsert)."""
        from unittest.mock import AsyncMock, MagicMock

        mock_arango_db = MagicMock()
        mock_arango_db.query = AsyncMock(return_value=([], None))
        mock_arango_db.execute = AsyncMock(return_value=([], None))
        mgr = SourceCollectionManager(tmp_path / "sources", backend="arangodb", arango_db=mock_arango_db)

        entry = SourceManifestEntry(
            source_id="src-arango1",
            source_uri="/docs/a.pdf",
            file_hash="deadbeef",
            mtime=1.0,
            ingested_at="2026-08-23T00:00:00Z",
            doc_metadata={"author": "Legal", "page_count": 3},
            content_type="application/pdf",
            loader="MarkdownLoader",
        )
        mgr._upsert(entry)
        bind_vars = mock_arango_db.execute.call_args.kwargs["bind_vars"]
        assert bind_vars["doc"]["doc_metadata"] == {"author": "Legal", "page_count": 3}
        assert bind_vars["doc"]["content_type"] == "application/pdf"
        assert bind_vars["doc"]["loader"] == "MarkdownLoader"

        # Round-trip back through _doc_to_entry.
        mock_arango_db.query = AsyncMock(return_value=([bind_vars["doc"]], None))
        fetched = mgr.get_source("src-arango1")
        assert fetched is not None
        assert fetched.doc_metadata == {"author": "Legal", "page_count": 3}
        assert fetched.content_type == "application/pdf"
        assert fetched.loader == "MarkdownLoader"


class TestRecordDocumentMetadata:
    """FEAT-451 (TASK-2355): SourceCollectionManager.record_document_metadata."""

    def test_persists_all_three_fields(self, sources_dir: Path, sample_source: Path):
        mgr = SourceCollectionManager(sources_dir)
        added = mgr.add_source(sample_source)

        mgr.record_document_metadata(
            added.source_id,
            doc_metadata={"author": "Legal", "page_count": 42},
            content_type="application/pdf",
            loader="MarkdownLoader",
        )

        fetched = mgr.get_source(added.source_id)
        assert fetched is not None
        assert fetched.doc_metadata == {"author": "Legal", "page_count": 42}
        assert fetched.content_type == "application/pdf"
        assert fetched.loader == "MarkdownLoader"
        # Untouched fields survive the update.
        assert fetched.source_uri == added.source_uri
        assert fetched.file_hash == added.file_hash

    def test_no_op_for_unknown_source_id(self, sources_dir: Path, caplog):
        mgr = SourceCollectionManager(sources_dir)
        mgr.record_document_metadata(
            "src-does-not-exist",
            doc_metadata={"author": "X"},
            content_type="application/pdf",
            loader="MarkdownLoader",
        )
        assert mgr.list_sources() == []


class TestBulkManifestOperations:
    """The batch API behind the build pipeline's manifest phase.

    Each of these has a per-file twin above; the contract is that the
    batch version produces the SAME rows in one statement, because on a
    server-hosted manifest the per-file version costs a round trip each.
    """

    @pytest.fixture
    def files(self, sources_dir: Path) -> list[Path]:
        made = []
        for i in range(5):
            f = sources_dir / f"doc{i}.md"
            f.write_text(f"# Doc {i}\n\nbody {i}")
            made.append(f)
        return made

    def test_add_sources_matches_add_source_row_for_row(self, sources_dir, files):
        batch_mgr = SourceCollectionManager(sources_dir / "batch")
        single_mgr = SourceCollectionManager(sources_dir / "single")

        batched = batch_mgr.add_sources(files)
        singles = [single_mgr.add_source(f) for f in files]

        assert [e.source_uri for e in batched] == [e.source_uri for e in singles]
        assert [e.file_hash for e in batched] == [e.file_hash for e in singles]
        assert [e.mtime for e in batched] == [e.mtime for e in singles]
        assert [e.status for e in batched] == [e.status for e in singles]
        # Ids are derived from the URI, so they must agree too.
        assert [e.source_id for e in batched] == [e.source_id for e in singles]

    def test_add_sources_persists_every_row(self, sources_dir, files):
        mgr = SourceCollectionManager(sources_dir / "m")
        mgr.add_sources(files)
        assert len(mgr.list_sources()) == len(files)

    def test_add_sources_reuses_ids_and_keeps_ingested_at(self, sources_dir, files):
        """Re-registering a changed file must not re-date it or drop its
        page list — the build pipeline registers stale files through here."""
        mgr = SourceCollectionManager(sources_dir / "m")
        first = mgr.add_sources(files)
        mgr.mark_ingested_many({e.source_id: [f"page-{i}"] for i, e in enumerate(first)})
        files[0].write_text("# Doc 0\n\nCHANGED")

        second = mgr.add_sources(files)

        assert [e.source_id for e in second] == [e.source_id for e in first]
        assert second[0].ingested_at == first[0].ingested_at
        assert second[0].pages_generated == ["page-0"]
        assert second[0].file_hash != first[0].file_hash

    def test_add_sources_preserves_external_id_and_doc_metadata(self, sources_dir, files):
        """FEAT-472 regression: re-registering an already-tracked, CHANGED
        file through the batch path must not wipe external_id/doc_metadata
        — the same class of bug fixed on mark_ingested/mark_ingested_many,
        surfaced by ObsidianVaultLoader's own use of this batch method."""
        mgr = SourceCollectionManager(sources_dir / "m")
        first = mgr.add_sources(files)
        mgr._upsert(first[0].model_copy(update={"external_id": "fireflies:abc", "doc_metadata": {"fireflies": {}}}))
        files[0].write_text("# Doc 0\n\nCHANGED")

        second = mgr.add_sources(files)

        assert second[0].external_id == "fireflies:abc"
        assert second[0].doc_metadata == {"fireflies": {}}
        assert second[0].file_hash != first[0].file_hash  # hash still refreshed

    def test_add_sources_raises_on_a_missing_path(self, sources_dir, files):
        mgr = SourceCollectionManager(sources_dir / "m")
        with pytest.raises(FileNotFoundError, match="ghost.md"):
            mgr.add_sources([*files, sources_dir / "ghost.md"])

    def test_add_sources_empty_is_a_noop(self, sources_dir):
        mgr = SourceCollectionManager(sources_dir / "m")
        assert mgr.add_sources([]) == []
        assert mgr.list_sources() == []

    def test_find_entries_by_uris_returns_only_tracked(self, sources_dir, files):
        mgr = SourceCollectionManager(sources_dir / "m")
        mgr.add_sources(files[:3])

        found = mgr.find_entries_by_uris([str(f.resolve()) for f in files])

        assert set(found) == {str(f.resolve()) for f in files[:3]}
        assert all(e.source_uri in found for e in found.values())

    def test_find_entries_by_uris_chunks_past_the_sqlite_limit(self, sources_dir):
        """More URIs than sqlite's bind-parameter ceiling must not raise."""
        from parrot.knowledge.wiki.sources import _SQLITE_IN_CHUNK

        mgr = SourceCollectionManager(sources_dir / "m")
        many = []
        for i in range(_SQLITE_IN_CHUNK + 7):
            f = sources_dir / f"bulk{i}.md"
            f.write_text(str(i))
            many.append(f)
        mgr.add_sources(many)

        found = mgr.find_entries_by_uris([str(f.resolve()) for f in many])

        assert len(found) == len(many)

    def test_find_entries_by_ids_round_trips(self, sources_dir, files):
        mgr = SourceCollectionManager(sources_dir / "m")
        entries = mgr.add_sources(files)

        found = mgr.find_entries_by_ids([e.source_id for e in entries] + ["nope"])

        assert set(found) == {e.source_id for e in entries}

    def test_mark_ingested_many_matches_mark_ingested(self, sources_dir, files):
        batch_mgr = SourceCollectionManager(sources_dir / "batch")
        single_mgr = SourceCollectionManager(sources_dir / "single")
        batched = batch_mgr.add_sources(files)
        for f in files:
            single_mgr.add_source(f)

        batch_mgr.mark_ingested_many({e.source_id: [f"p{i}"] for i, e in enumerate(batched)})
        for i, e in enumerate(batched):
            single_mgr.mark_ingested(e.source_id, [f"p{i}"])

        for e in batched:
            a = batch_mgr.get_source(e.source_id)
            b = single_mgr.get_source(e.source_id)
            assert a.pages_generated == b.pages_generated
            assert a.status == b.status
            assert a.file_hash == b.file_hash

    def test_mark_ingested_many_skips_unknown_ids(self, sources_dir, files):
        mgr = SourceCollectionManager(sources_dir / "m")
        entries = mgr.add_sources(files[:1])

        mgr.mark_ingested_many({entries[0].source_id: ["p0"], "ghost-id": ["p1"]})

        assert mgr.get_source(entries[0].source_id).pages_generated == ["p0"]
        assert mgr.get_source("ghost-id") is None

    def test_entry_is_stale_agrees_with_is_stale(self, sources_dir, files):
        mgr = SourceCollectionManager(sources_dir / "m")
        entries = mgr.add_sources(files)
        fresh = entries[0]
        files[1].write_text("# changed")
        changed_id = entries[1].source_id
        files[2].unlink()

        assert mgr.entry_is_stale(fresh) is mgr.is_stale(fresh.source_id) is False
        assert mgr.entry_is_stale(mgr.get_source(changed_id)) is mgr.is_stale(changed_id) is True
        assert mgr.entry_is_stale(entries[2]) is True, "a deleted file is stale"


class TestExternalIdMigration:
    """FEAT-472: additive `sources.external_id` column + index migration."""

    def test_migration_adds_external_id_column(self, tmp_path):
        """A pre-FEAT-472 (14-column) sources table opens cleanly and gains
        the new external_id column + index; existing rows are preserved."""
        import sqlite3

        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        db_path = sources_dir.parent / "wiki.db"

        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE sources (
                source_id        TEXT PRIMARY KEY,
                source_uri       TEXT NOT NULL UNIQUE,
                file_hash        TEXT NOT NULL,
                mtime            REAL NOT NULL,
                ingested_at      TEXT NOT NULL,
                pages_generated  TEXT NOT NULL DEFAULT '[]',
                status           TEXT NOT NULL DEFAULT 'ingested',
                destination      TEXT,
                decision_source  TEXT,
                charter_version  TEXT,
                composite_score  REAL,
                doc_metadata     TEXT,
                content_type     TEXT,
                loader           TEXT
            )
            """)
        conn.execute(
            "INSERT INTO sources"
            " (source_id, source_uri, file_hash, mtime, ingested_at,"
            "  pages_generated, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "src-old000003",
                "/docs/legacy3.md",
                "feedface" * 5,
                1.0,
                "2025-09-01T00:00:00Z",
                "[]",
                "ingested",
            ),
        )
        conn.commit()
        conn.close()

        mgr = SourceCollectionManager(sources_dir, db_path=db_path)

        raw_conn = sqlite3.connect(str(db_path))
        columns = {row[1] for row in raw_conn.execute("PRAGMA table_info(sources)")}
        indexes = {row[1] for row in raw_conn.execute("PRAGMA index_list(sources)")}
        raw_conn.close()
        assert "external_id" in columns
        assert "idx_sources_external_id" in indexes

        entry = mgr.get_source("src-old000003")
        assert entry is not None
        assert entry.external_id is None  # pre-existing row untouched

        # Opening it again must be a no-op (idempotent).
        SourceCollectionManager(sources_dir, db_path=db_path)

    def test_new_db_has_external_id_column_from_ddl(self, sources_dir, sample_source):
        """A brand-new database already has external_id (None by default)."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert entry.external_id is None


class TestExternalIdReadersWriters:
    """FEAT-472: add_source(external_id=...), find_by_external_id, etc."""

    @pytest.mark.parametrize("backend", ["sqlite", "json"])
    def test_add_source_with_external_id_roundtrip(self, tmp_path, backend):
        sources_dir = tmp_path / "sources"
        sources_dir.mkdir()
        f = sources_dir / "meeting.md"
        f.write_text("# Meeting\n")

        mgr = SourceCollectionManager(sources_dir, backend=backend)
        entry = mgr.add_source(f, external_id="fireflies:abc")

        found = mgr.find_by_external_id("fireflies:abc")
        assert found is not None
        assert found.source_id == entry.source_id
        assert mgr.find_by_external_id("fireflies:unknown") is None

    def test_external_id_survives_mark_ingested(self, sources_dir, sample_source):
        """mark_ingested must not drop FEAT-402/451/472 fields (bugfix)."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source, external_id="fireflies:xyz")
        mgr.record_document_metadata(
            entry.source_id,
            doc_metadata={"author": "A"},
            content_type="text/markdown",
            loader="MarkdownLoader",
        )

        updated = mgr.mark_ingested(entry.source_id, pages_generated=["page-1"])

        assert updated is not None
        assert updated.external_id == "fireflies:xyz"
        assert updated.doc_metadata == {"author": "A"}
        assert updated.content_type == "text/markdown"
        assert updated.loader == "MarkdownLoader"

        fetched = mgr.get_source(entry.source_id)
        assert fetched.external_id == "fireflies:xyz"
        assert fetched.doc_metadata == {"author": "A"}

    def test_external_id_survives_mark_ingested_many(self, sources_dir):
        mgr = SourceCollectionManager(sources_dir)
        files = []
        for i in range(3):
            f = sources_dir / f"m{i}.md"
            f.write_text(f"# m{i}")
            files.append(f)
        entries = [mgr.add_source(f, external_id=f"fireflies:{i}") for i, f in enumerate(files)]

        mgr.mark_ingested_many({e.source_id: [f"page-{i}"] for i, e in enumerate(entries)})

        for i, e in enumerate(entries):
            fetched = mgr.get_source(e.source_id)
            assert fetched.external_id == f"fireflies:{i}"
            assert fetched.pages_generated == [f"page-{i}"]

    def test_list_by_external_prefix(self, sources_dir):
        mgr = SourceCollectionManager(sources_dir)
        f1 = sources_dir / "a.md"
        f1.write_text("a")
        f2 = sources_dir / "b.md"
        f2.write_text("b")
        f3 = sources_dir / "c.md"
        f3.write_text("c")
        mgr.add_source(f1, external_id="fireflies:1")
        mgr.add_source(f2, external_id="fireflies:2")
        mgr.add_source(f3, external_id="jira:1")

        found = mgr.list_by_external_prefix("fireflies:")

        assert {e.external_id for e in found} == {"fireflies:1", "fireflies:2"}

    def test_find_entries_by_external_ids_chunked(self, sources_dir):
        from parrot.knowledge.wiki.sources import _SQLITE_IN_CHUNK

        mgr = SourceCollectionManager(sources_dir)
        ids = []
        for i in range(_SQLITE_IN_CHUNK + 7):
            f = sources_dir / f"bulk{i}.md"
            f.write_text(str(i))
            ext_id = f"fireflies:{i}"
            mgr.add_source(f, external_id=ext_id)
            ids.append(ext_id)

        found = mgr.find_entries_by_external_ids(ids)

        assert len(found) == len(ids)

    def test_set_external_id(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert entry.external_id is None

        updated = mgr.set_external_id(entry.source_id, "fireflies:new")
        assert updated is not None
        assert updated.external_id == "fireflies:new"
        assert mgr.get_source(entry.source_id).external_id == "fireflies:new"

        cleared = mgr.set_external_id(entry.source_id, None)
        assert cleared.external_id is None

    def test_set_external_id_unknown_source_id(self, sources_dir):
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.set_external_id("nonexistent", "fireflies:x") is None


class TestUpdateSourceUri:
    """FEAT-472: SourceCollectionManager.update_source_uri."""

    def test_update_source_uri_keeps_source_id(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source, external_id="fireflies:abc")

        new_path = sources_dir / "renamed.md"
        sample_source.rename(new_path)

        updated = mgr.update_source_uri(entry.source_id, new_path)

        assert updated is not None
        assert updated.source_id == entry.source_id
        assert updated.source_uri == str(new_path.resolve())
        assert updated.external_id == "fireflies:abc"
        assert mgr.find_by_uri(str(new_path.resolve())) == entry.source_id

    def test_update_source_uri_missing_file_raises(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)

        with pytest.raises(FileNotFoundError):
            mgr.update_source_uri(entry.source_id, sources_dir / "ghost.md")

    def test_update_source_uri_conflict_raises(self, sources_dir):
        mgr = SourceCollectionManager(sources_dir)
        f1 = sources_dir / "one.md"
        f1.write_text("one")
        f2 = sources_dir / "two.md"
        f2.write_text("two")
        e1 = mgr.add_source(f1)
        mgr.add_source(f2)

        with pytest.raises(ValueError, match="already tracked"):
            mgr.update_source_uri(e1.source_id, f2)

    def test_update_source_uri_unknown_source_id_returns_none(self, sources_dir, sample_source):
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.update_source_uri("nonexistent", sample_source) is None
