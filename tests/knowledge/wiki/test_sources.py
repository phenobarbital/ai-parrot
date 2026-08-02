"""Unit tests for SourceCollectionManager (TASK-1629)."""

import time
from pathlib import Path

import pytest

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

    def test_is_stale_false_for_fresh_source(
        self, sources_dir: Path, sample_source: Path
    ):
        """is_stale returns False immediately after add_source."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        assert not mgr.is_stale(entry.source_id)

    def test_is_stale_true_after_content_change(
        self, sources_dir: Path, sample_source: Path
    ):
        """is_stale returns True when the file content changes."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        # Modify content (also updates mtime)
        sample_source.write_text("# Updated Content\n\nDifferent text.")
        assert mgr.is_stale(entry.source_id)

    def test_is_stale_true_for_missing_file(
        self, sources_dir: Path, sample_source: Path
    ):
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

    def test_registry_db_exists_after_add(
        self, sources_dir: Path, sample_source: Path
    ):
        """The shared wiki.db registry is created after the first add_source."""
        mgr = SourceCollectionManager(sources_dir)
        mgr.add_source(sample_source)
        assert mgr.db_path.exists()
        assert mgr.db_path == sources_dir.parent / "wiki.db"

    def test_legacy_json_manifest_migrated(
        self, sources_dir: Path, sample_source: Path
    ):
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

    def test_mark_ingested_updates_pages(
        self, sources_dir: Path, sample_source: Path
    ):
        """mark_ingested stores the pages_generated list in the manifest."""
        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.add_source(sample_source)
        updated = mgr.mark_ingested(
            entry.source_id, pages_generated=["page-1", "page-2"]
        )
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

    def test_manifest_file_exists_after_add(
        self, sources_dir: Path, sample_source: Path
    ):
        mgr = SourceCollectionManager(sources_dir, backend="json")
        mgr.add_source(sample_source)
        assert (sources_dir / ".manifest.json").exists()
        assert not mgr.db_path.exists()  # no wiki.db in json mode

    def test_persistence_across_managers(
        self, sources_dir: Path, sample_source: Path
    ):
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
        conn.execute(
            """
            CREATE TABLE sources (
                source_id       TEXT PRIMARY KEY,
                source_uri      TEXT NOT NULL UNIQUE,
                file_hash       TEXT NOT NULL,
                mtime           REAL NOT NULL,
                ingested_at     TEXT NOT NULL,
                pages_generated TEXT NOT NULL DEFAULT '[]',
                status          TEXT NOT NULL DEFAULT 'ingested'
            )
            """
        )
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

    def test_new_db_has_decision_columns_from_ddl(
        self, sources_dir: Path, sample_source: Path
    ):
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

    def test_record_decision_creates_untracked_source(
        self, sources_dir: Path, sample_source: Path
    ):
        """record_decision works even when the source was never add_source'd
        — the typical case for a rejected document (spec §2)."""
        mgr = SourceCollectionManager(sources_dir)
        assert mgr.list_sources() == []

        entry = mgr.record_decision(
            sample_source, destination="archive", decision_source="auto"
        )
        assert entry is not None
        assert len(mgr.list_sources()) == 1

    def test_record_decision_updates_existing_source(
        self, sources_dir: Path, sample_source: Path
    ):
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

    def test_record_decision_archive_defaults_to_ingested_status(
        self, sources_dir: Path, sample_source: Path
    ):
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

    def test_format_handles_missing_composite(
        self, sources_dir: Path, sample_source: Path
    ):
        from parrot.knowledge.wiki.sources import format_decision_log_details

        mgr = SourceCollectionManager(sources_dir)
        entry = mgr.record_decision(sample_source, destination="discard")
        details = format_decision_log_details(entry)
        assert "composite: n/a" in details
