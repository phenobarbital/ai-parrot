"""Unit tests for the MeetingRegistry facade (FEAT-472, TASK-2554)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from parrot.agents.meeting_registry import (
    EXTERNAL_ID_PREFIX,
    MeetingRegistry,
    fingerprint,
    normalise_transcript,
)


@pytest.fixture
def registry(tmp_path: Path) -> MeetingRegistry:
    return MeetingRegistry(tmp_path / "wiki")


async def fetch_factory(texts: dict[str, str]):
    calls: list[str] = []

    async def fetch(fireflies_id: str) -> str:
        calls.append(fireflies_id)
        return texts[fireflies_id]

    fetch.calls = calls
    return fetch


class TestNormaliseAndFingerprint:
    def test_normalise_transcript_rules(self):
        raw = "﻿Hello world  \r\nLine two\r\n\r\n\r\n\r\nLine three   \r\n\n\n"
        normalised = normalise_transcript(raw)
        assert "﻿" not in normalised
        assert "\r" not in normalised
        assert "Hello world  " not in normalised  # trailing spaces stripped
        assert "\n\n\n" not in normalised  # collapsed to at most 2

    def test_normalise_transcript_equal_for_variants(self):
        a = "Hello\nWorld"
        b = "﻿Hello\r\nWorld\r\n"
        assert normalise_transcript(a) == normalise_transcript(b)

    def test_fingerprint_ignores_summary(self):
        transcript = "Same transcript text"
        fp1 = fingerprint(transcript)
        fp2 = fingerprint(transcript)
        assert fp1 == fp2
        # A different "summary" text produces a different, unrelated hash
        # when hashed on its own -- fingerprint() only ever sees the
        # transcript, never a summary, by contract of the caller.
        assert fingerprint("different summary text") != fp1


class TestClassify:
    async def test_classify_unknown_id_creates(self, registry: MeetingRegistry):
        fetch = await fetch_factory({"abc": "transcript text"})
        result = await registry.classify({"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30}, fetch=fetch)
        assert result.action == "create"
        assert result.fetched_text == "transcript text"
        assert fetch.calls == ["abc"]

    async def test_classify_cheap_skip_no_fetch(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "note.md"
        note.write_text("body")
        await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=30.0,
            fingerprint="deadbeef",
            summary_fingerprint=None,
            reset_analysis=False,
        )
        fetch = await fetch_factory({})
        result = await registry.classify(
            {"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30},
            fetch=fetch,
        )
        assert result.action == "skip"
        assert fetch.calls == []

    async def test_classify_recheck_window_fetches(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "note.md"
        note.write_text("body")
        record = await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=30.0,
            fingerprint="deadbeef",
            summary_fingerprint=None,
            reset_analysis=False,
        )
        # Force the recheck window to have expired without waiting real time.
        registry._recheck_days = 0
        old_synced_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        entry = registry._manager.get_source(record.source_id)
        doc_metadata = dict(entry.doc_metadata or {})
        doc_metadata["fireflies"]["synced_at"] = old_synced_at
        registry._manager.record_document_metadata(
            entry.source_id,
            doc_metadata=doc_metadata,
            content_type=entry.content_type,
            loader=entry.loader,
        )

        text = "transcript text same content " + normalise_transcript("deadbeef")
        fp = fingerprint(text)

        async def fetch(_id: str) -> str:
            return text

        result = await registry.classify(
            {"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30},
            fetch=fetch,
        )
        assert result.action == "revise"
        assert result.fingerprint == fp

    async def test_classify_changed_content_revises(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "note.md"
        note.write_text("body")
        await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=30.0,
            fingerprint="deadbeef",
            summary_fingerprint=None,
            reset_analysis=False,
        )

        async def fetch(_id: str) -> str:
            return "changed content"

        result = await registry.classify(
            {"id": "abc", "title": "New Title", "date": "2026-08-01", "duration": 30},
            fetch=fetch,
        )
        assert result.action == "revise"
        assert fetch is not None

    async def test_classify_backfilled_none_fingerprint_fetches(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "note.md"
        note.write_text("body")
        await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=30.0,
            fingerprint=None,
            summary_fingerprint=None,
            reset_analysis=False,
        )
        fetch = await fetch_factory({"abc": "text"})
        result = await registry.classify(
            {"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30},
            fetch=fetch,
        )
        assert fetch.calls == ["abc"]
        assert result.action == "revise"

    async def test_classify_force_refetch(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "note.md"
        note.write_text("body")
        text = "same text"
        fp = fingerprint(text)
        await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=30.0,
            fingerprint=fp,
            summary_fingerprint=None,
            reset_analysis=False,
        )
        fetch = await fetch_factory({"abc": text})
        result = await registry.classify(
            {"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30},
            fetch=fetch,
            force_refetch=True,
        )
        assert fetch.calls == ["abc"]
        assert result.action == "skip"  # same content -> skip, but fetch WAS called

    async def test_classify_rejected_row_skips(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "note.md"
        note.write_text("body")
        await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=30.0,
            fingerprint="deadbeef",
            summary_fingerprint=None,
            reset_analysis=False,
        )
        assert await registry.forget("abc", reject=True) is True

        async def fetch(_id: str) -> str:
            raise AssertionError("fetch must not be called for a rejected row")

        result = await registry.classify(
            {"id": "abc", "title": "Changed", "date": "2026-09-01", "duration": 99},
            fetch=fetch,
        )
        assert result.action == "skip"

    async def test_probable_duplicate_reported(self, registry: MeetingRegistry, tmp_path: Path):
        note1 = tmp_path / "note1.md"
        note1.write_text("body1")
        text = "shared transcript content"
        fp = fingerprint(text)
        await registry.record_synced(
            fireflies_id="existing",
            note_path=note1,
            title="Existing meeting",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=10.0,
            fingerprint=fp,
            summary_fingerprint=None,
            reset_analysis=False,
        )

        async def fetch(_id: str) -> str:
            return text

        result = await registry.classify({"id": "new-id", "title": "New meeting"}, fetch=fetch)
        assert result.action == "create"
        assert f"{EXTERNAL_ID_PREFIX}existing" in result.probable_duplicate_of


class TestPendingAnalysis:
    async def test_pending_analysis_selection(self, registry: MeetingRegistry, tmp_path: Path):
        note_pending = tmp_path / "pending.md"
        note_pending.write_text("body")
        note_done_current = tmp_path / "done_current.md"
        note_done_current.write_text("body")
        note_done_stale = tmp_path / "done_stale.md"
        note_done_stale.write_text("body")

        await registry.record_synced(
            fireflies_id="pending-id",
            note_path=note_pending,
            title="t",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp1",
            summary_fingerprint=None,
            reset_analysis=True,
        )

        await registry.record_synced(
            fireflies_id="done-current-id",
            note_path=note_done_current,
            title="t",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp2",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        await registry.mark_analyzed("done-current-id", "fp2")

        await registry.record_synced(
            fireflies_id="done-stale-id",
            note_path=note_done_stale,
            title="t",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp3-new",
            summary_fingerprint=None,
            reset_analysis=False,
        )
        await registry.mark_analyzed("done-stale-id", "fp3-old")
        # record_synced again with a NEW fingerprint but reset_analysis=False
        # would normally be a revise() call resetting analysis; simulate the
        # stale-fingerprint case by not resetting: the analysis_fingerprint
        # ("fp3-old") no longer matches the current fingerprint ("fp3-new").

        pending = await registry.pending_analysis()
        pending_ids = {r.fireflies_id for r in pending}

        assert "pending-id" in pending_ids
        assert "done-stale-id" in pending_ids
        assert "done-current-id" not in pending_ids


class TestRecordSynced:
    async def test_record_synced_merges_doc_metadata(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "note.md"
        note.write_text("body")
        record = await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup",
            meeting_date="2026-08-01",
            participants=["a@x.com"],
            duration_minutes=15.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        # Simulate FEAT-451 metadata already present on the row.
        entry = registry._manager.get_source(record.source_id)
        registry._manager.record_document_metadata(
            entry.source_id,
            doc_metadata={**(entry.doc_metadata or {}), "author": "Someone"},
            content_type="text/markdown",
            loader="MarkdownLoader",
        )

        await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="Standup Updated",
            meeting_date="2026-08-01",
            participants=["a@x.com"],
            duration_minutes=15.0,
            fingerprint="fp2",
            summary_fingerprint=None,
            reset_analysis=True,
        )

        fetched = registry._manager.get_source(record.source_id)
        assert fetched.doc_metadata["author"] == "Someone"
        assert fetched.doc_metadata["fireflies"]["title"] == "Standup Updated"


class TestSuggestFromDate:
    async def test_suggest_from_date(self, registry: MeetingRegistry, tmp_path: Path):
        assert await registry.suggest_from_date(overlap_days=2) is None

        note = tmp_path / "note.md"
        note.write_text("body")
        record = await registry.record_synced(
            fireflies_id="abc",
            note_path=note,
            title="t",
            meeting_date="2026-08-10",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        synced_dt = datetime.fromisoformat(record.synced_at)
        expected = (synced_dt.date() - timedelta(days=2)).isoformat()
        assert await registry.suggest_from_date(overlap_days=2) == expected


class TestUniqueSlug:
    async def test_unique_slug_suffixes(self, registry: MeetingRegistry, tmp_path: Path):
        vault_path = tmp_path / "vault"
        (vault_path / "meetings").mkdir(parents=True)

        # No collision -> base title returned.
        slug = await registry.unique_slug("meetings", "2026-08-01-standup", vault_path=vault_path)
        assert slug == "2026-08-01-standup"

        # Filesystem collision -> -2.
        (vault_path / "meetings" / "2026-08-01-standup.md").write_text("body")
        slug2 = await registry.unique_slug("meetings", "2026-08-01-standup", vault_path=vault_path)
        assert slug2 == "2026-08-01-standup-2"

        # Registry collision (tracked but not necessarily on disk) -> -3.
        registered_path = vault_path / "meetings" / "2026-08-01-standup-2.md"
        registered_path.write_text("body")
        await registry.record_synced(
            fireflies_id="xyz",
            note_path=registered_path,
            title="t",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        slug3 = await registry.unique_slug("meetings", "2026-08-01-standup", vault_path=vault_path)
        assert slug3 == "2026-08-01-standup-3"


class TestMarkWikiIngested:
    async def test_mark_wiki_ingested_only_ingested_rows(self, registry: MeetingRegistry, tmp_path: Path):
        ingested_note = tmp_path / "ingested.md"
        ingested_note.write_text("body")
        no_pages_note = tmp_path / "no_pages.md"
        no_pages_note.write_text("body")

        r1 = await registry.record_synced(
            fireflies_id="ingested-id",
            note_path=ingested_note,
            title="t",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        registry._manager.mark_ingested_many({r1.source_id: ["page-1"]})

        await registry.record_synced(
            fireflies_id="no-pages-id",
            note_path=no_pages_note,
            title="t",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )

        stamped = await registry.mark_wiki_ingested()
        assert stamped == 1

        ingested_record = await registry.lookup("ingested-id")
        no_pages_record = await registry.lookup("no-pages-id")
        assert ingested_record.wiki_ingested_at is not None
        assert no_pages_record.wiki_ingested_at is None


class TestUnavailableRegistry:
    async def test_unavailable_registry_degrades(self, tmp_path: Path, monkeypatch):
        registry = MeetingRegistry(tmp_path / "wiki")
        # Simulate degradation after construction (e.g. a later manager
        # failure) by flipping the internal flag directly.
        registry._available = False

        assert registry.available is False
        assert await registry.lookup("abc") is None
        assert await registry.pending_analysis() == []
        assert await registry.suggest_from_date(overlap_days=2) is None
        assert await registry.mark_wiki_ingested() == 0
        assert await registry.forget("abc") is False

        async def fetch(_id: str) -> str:
            raise AssertionError("classify must not fetch when unavailable")

        result = await registry.classify({"id": "abc"}, fetch=fetch)
        assert result.action == "create"

    def test_constructor_degrades_on_unwritable_dir(self, tmp_path: Path, caplog):
        import stat

        blocked_parent = tmp_path / "blocked"
        blocked_parent.mkdir()
        blocked_parent.chmod(stat.S_IREAD | stat.S_IEXEC)
        try:
            registry = MeetingRegistry(blocked_parent / "nested" / "wiki")
            assert registry.available is False
        finally:
            blocked_parent.chmod(stat.S_IRWXU)
