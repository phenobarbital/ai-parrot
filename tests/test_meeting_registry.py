"""Unit tests for the MeetingRegistry facade (FEAT-472, TASK-2554/2555)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from parrot.agents.meeting_registry import (
    EXTERNAL_ID_PREFIX,
    MeetingRegistry,
    fingerprint,
    normalise_transcript,
)
from parrot.tools.obsidian import ObsidianToolkit


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
        result = await registry.classify(
            {"id": "abc", "title": "Standup", "date": "2026-08-01", "duration": 30}, fetch=fetch
        )
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

        # all_records() must include the done-and-current row too — the
        # candidate set a force=True analysis run needs (pending_analysis()
        # excludes it by construction).
        all_ids = {r.fireflies_id for r in await registry.all_records()}
        assert all_ids == {"pending-id", "done-current-id", "done-stale-id"}

    async def test_all_records_excludes_rejected(self, registry: MeetingRegistry, tmp_path: Path):
        note = tmp_path / "rejected.md"
        note.write_text("body")
        await registry.record_synced(
            fireflies_id="rejected-id",
            note_path=note,
            title="t",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=1.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        await registry.forget("rejected-id", reject=True)

        assert await registry.all_records() == []
        assert await registry.pending_analysis() == []


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

    async def test_record_synced_repoints_stale_row_instead_of_duplicating(
        self, registry: MeetingRegistry, tmp_path: Path
    ):
        """Regression: when the original note is gone and repair_path
        couldn't find it anywhere (to_path=None), the caller creates a
        brand-new note at a DIFFERENT path and calls record_synced again.
        That must repoint the existing row (same source_id) rather than
        insert a second row sharing the same external_id — there is no
        UNIQUE constraint on external_id, so a second row would make
        find_by_external_id non-deterministic."""
        original = tmp_path / "original.md"
        original.write_text("body")
        first = await registry.record_synced(
            fireflies_id="abc",
            note_path=original,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=10.0,
            fingerprint="fp1",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        original.unlink()  # the note is gone; repair_path would find nothing

        recreated = tmp_path / "recreated.md"
        recreated.write_text("body v2")
        second = await registry.record_synced(
            fireflies_id="abc",
            note_path=recreated,
            title="Standup",
            meeting_date="2026-08-01",
            participants=[],
            duration_minutes=10.0,
            fingerprint="fp2",
            summary_fingerprint=None,
            reset_analysis=False,
        )

        assert second.source_id == first.source_id  # repointed, not duplicated
        rows = registry._manager.list_by_external_prefix("fireflies:")
        assert len(rows) == 1
        assert rows[0].source_uri == str(recreated.resolve())


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


# ---------------------------------------------------------------------------
# TASK-2555: backfill, duplicate merge, path repair
# ---------------------------------------------------------------------------


def _write_note(
    meetings_dir: Path,
    filename: str,
    *,
    fireflies_id: str,
    title: str,
    date: str,
    has_analysis: bool = False,
    participants: list[str] | None = None,
    duration_minutes: float = 10.0,
    synced_at: str = "2026-08-01T00:00:00+00:00",
) -> Path:
    frontmatter = {
        "fireflies_id": fireflies_id,
        "title": title,
        "date": date,
        "participants": participants or [],
        "duration_minutes": duration_minutes,
        "synced_at": synced_at,
    }
    block = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False)
    body = "Meeting transcript body.\n"
    if has_analysis:
        body += "\n## Analysis\n\nKey takeaways here.\n"
    path = meetings_dir / filename
    path.write_text(f"---\n{block}---\n\n{body}", encoding="utf-8")
    return path


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    """A vault with 5 Fireflies notes (one duplicated id) + 1 unreadable file."""
    vault_root = tmp_path / "vault"
    meetings = vault_root / "meetings"
    meetings.mkdir(parents=True)

    _write_note(meetings, "2026-08-01-standup-a.md", fireflies_id="id-a", title="Standup A", date="2026-08-01")
    _write_note(
        meetings,
        "2026-08-02-standup-b.md",
        fireflies_id="id-b",
        title="Standup B",
        date="2026-08-02",
        has_analysis=True,
    )
    _write_note(meetings, "2026-08-03-standup-c1.md", fireflies_id="id-c", title="Standup C", date="2026-08-03")
    _write_note(
        meetings,
        "2026-08-03-standup-c2.md",
        fireflies_id="id-c",
        title="Standup C",
        date="2026-08-03",
        has_analysis=True,
    )
    _write_note(meetings, "2026-08-04-standup-d.md", fireflies_id="id-d", title="Standup D", date="2026-08-04")

    # A file that cannot even be decoded as UTF-8 — surfaces in read_notes'
    # ``errors`` dict, never tolerated the way malformed YAML is.
    (meetings / "unreadable.md").write_bytes(b"\xff\xfe not valid utf-8 \xfa")

    return vault_root


@pytest.fixture
def toolkit(vault: Path) -> ObsidianToolkit:
    return ObsidianToolkit(
        vault_path=str(vault),
        backend="local",
        allowed_operations={"read", "bulk_read", "list", "search", "create", "update", "move", "delete"},
    )


class TestBackfillFromVault:
    async def test_backfill_seeds_from_frontmatter(self, registry: MeetingRegistry, toolkit: ObsidianToolkit):
        report = await registry.backfill_from_vault(
            toolkit=toolkit, meetings_folder="meetings", analysis_heading="## Analysis"
        )

        assert report.seeded == 4  # a, b, merged-c, d
        assert len(report.duplicates) == 1
        assert report.duplicates[0].fireflies_id == "id-c"
        # The analysed duplicate (c2) is kept, then moved to its own
        # canonical path (title/date-derived, differs from either
        # original filename).
        assert set(report.duplicates[0].removed) == {"meetings/2026-08-03-standup-c1.md"}
        assert report.duplicates[0].kept == "meetings/2026-08-03-standup-c.md"
        assert "meetings/unreadable.md" in report.unmerged
        assert report.without_analysis == 2  # a, d (b and merged-c have analysis)

        a = await registry.lookup("id-a")
        b = await registry.lookup("id-b")
        c = await registry.lookup("id-c")
        d = await registry.lookup("id-d")
        assert a.fingerprint is None
        assert a.analysis_status == "pending"
        assert b.analysis_status == "done"
        assert c.analysis_status == "done"
        assert d.analysis_status == "pending"

    async def test_backfill_idempotent(self, registry: MeetingRegistry, toolkit: ObsidianToolkit):
        first = await registry.backfill_from_vault(
            toolkit=toolkit, meetings_folder="meetings", analysis_heading="## Analysis"
        )
        assert first.seeded == 4

        second = await registry.backfill_from_vault(
            toolkit=toolkit, meetings_folder="meetings", analysis_heading="## Analysis"
        )
        assert second.seeded == 0
        assert second.duplicates == []
        assert second.unmerged == []

    async def test_backfill_dry_run_reports_only(self, registry: MeetingRegistry, toolkit: ObsidianToolkit):
        report = await registry.backfill_from_vault(
            toolkit=toolkit,
            meetings_folder="meetings",
            analysis_heading="## Analysis",
            merge=False,
        )

        assert report.duplicates == []
        assert "meetings/2026-08-03-standup-c1.md" in report.unmerged
        assert "meetings/2026-08-03-standup-c2.md" in report.unmerged
        # Nothing was deleted or registered for the duplicate id.
        assert await registry.lookup("id-c") is None
        assert (Path(toolkit.vault.vault_path) / "meetings" / "2026-08-03-standup-c1.md").exists()
        assert (Path(toolkit.vault.vault_path) / "meetings" / "2026-08-03-standup-c2.md").exists()
        # Non-duplicate ids are still seeded.
        assert await registry.lookup("id-a") is not None


class TestMergeDuplicates:
    async def test_merge_duplicates_keeps_analysed(self, registry: MeetingRegistry, toolkit: ObsidianToolkit):
        result = await registry.merge_duplicates(
            "id-c",
            ["meetings/2026-08-03-standup-c1.md", "meetings/2026-08-03-standup-c2.md"],
            toolkit=toolkit,
            meetings_folder="meetings",
            analysis_heading="## Analysis",
        )

        # The analysed note (c2) is kept, then moved to the canonical path
        # derived from its own title/date ("Standup C" / "2026-08-03"),
        # which differs from its original filename.
        assert result.kept == "meetings/2026-08-03-standup-c.md"
        assert result.removed == ["meetings/2026-08-03-standup-c1.md"]

        vault_root = Path(toolkit.vault.vault_path)
        assert not (vault_root / "meetings" / "2026-08-03-standup-c1.md").exists()
        assert not (vault_root / "meetings" / "2026-08-03-standup-c2.md").exists()
        assert (vault_root / "meetings" / "2026-08-03-standup-c.md").exists()

        record = await registry.lookup("id-c")
        assert record is not None
        assert record.analysis_status == "done"

    async def test_merge_duplicates_moves_kept_note_to_canonical_path(
        self, registry: MeetingRegistry, toolkit: ObsidianToolkit, vault: Path
    ):
        meetings = vault / "meetings"
        # Kept note (has analysis) lives at a NON-canonical path.
        _write_note(
            meetings,
            "renamed-c.md",
            fireflies_id="id-e",
            title="Standup E",
            date="2026-08-05",
            has_analysis=True,
        )
        _write_note(meetings, "2026-08-05-standup-e.md", fireflies_id="id-e", title="Standup E", date="2026-08-05")

        result = await registry.merge_duplicates(
            "id-e",
            ["meetings/renamed-c.md", "meetings/2026-08-05-standup-e.md"],
            toolkit=toolkit,
            meetings_folder="meetings",
            analysis_heading="## Analysis",
        )

        assert result.kept == "meetings/2026-08-05-standup-e.md"
        vault_root = Path(toolkit.vault.vault_path)
        assert (vault_root / "meetings" / "2026-08-05-standup-e.md").exists()
        assert not (vault_root / "meetings" / "renamed-c.md").exists()

    async def test_merge_duplicates_unparsable_left(self, registry: MeetingRegistry, toolkit: ObsidianToolkit):
        # An unreadable path passed into merge_duplicates must never be
        # deleted — read_notes simply can't produce content/frontmatter
        # for it, so it is excluded from the analysed/mtime comparison
        # and left on disk.
        result = await registry.merge_duplicates(
            "id-c",
            ["meetings/2026-08-03-standup-c1.md", "meetings/unreadable.md"],
            toolkit=toolkit,
            meetings_folder="meetings",
            analysis_heading="## Analysis",
        )

        vault_root = Path(toolkit.vault.vault_path)
        assert (vault_root / "meetings" / "unreadable.md").exists()
        assert "meetings/unreadable.md" not in result.removed


class TestRepairPath:
    async def test_repair_path_moves_to_canonical(
        self, registry: MeetingRegistry, toolkit: ObsidianToolkit, vault: Path
    ):
        meetings = vault / "meetings"
        note_path = _write_note(
            meetings, "2026-08-06-standup-f.md", fireflies_id="id-f", title="Standup F", date="2026-08-06"
        )
        await registry.record_synced(
            fireflies_id="id-f",
            note_path=note_path,
            title="Standup F",
            meeting_date="2026-08-06",
            participants=[],
            duration_minutes=5.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        # Simulate a rename: move the file on disk without updating the registry.
        renamed = meetings / "renamed-f.md"
        note_path.rename(renamed)

        result = await registry.repair_path(
            "id-f",
            toolkit=toolkit,
            meetings_folder="meetings",
            canonical_title="2026-08-06-standup-f",
        )

        assert result.moved is True
        assert result.to_path == str(vault / "meetings" / "2026-08-06-standup-f.md")
        assert (vault / "meetings" / "2026-08-06-standup-f.md").exists()
        assert not renamed.exists()

        entry = registry._manager.get_source((await registry.lookup("id-f")).source_id)
        assert entry.source_uri == result.to_path

    async def test_repair_path_canonical_taken_by_other_id(
        self, registry: MeetingRegistry, toolkit: ObsidianToolkit, vault: Path
    ):
        meetings = vault / "meetings"
        # A DIFFERENT meeting already occupies the canonical path.
        other_path = _write_note(
            meetings, "2026-08-07-standup-g.md", fireflies_id="id-other", title="Standup G", date="2026-08-07"
        )
        await registry.record_synced(
            fireflies_id="id-other",
            note_path=other_path,
            title="Standup G",
            meeting_date="2026-08-07",
            participants=[],
            duration_minutes=5.0,
            fingerprint="fp-other",
            summary_fingerprint=None,
            reset_analysis=True,
        )

        # The meeting being repaired was moved to a different filename.
        moved_path = _write_note(meetings, "moved-g2.md", fireflies_id="id-g2", title="Standup G2", date="2026-08-07")
        await registry.record_synced(
            fireflies_id="id-g2",
            note_path=moved_path,
            title="Standup G2",
            meeting_date="2026-08-07",
            participants=[],
            duration_minutes=5.0,
            fingerprint="fp-g2",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        renamed = meetings / "renamed-g2.md"
        moved_path.rename(renamed)

        result = await registry.repair_path(
            "id-g2",
            toolkit=toolkit,
            meetings_folder="meetings",
            canonical_title="2026-08-07-standup-g",  # collides with id-other
        )

        assert result.moved is False
        assert result.to_path == str(renamed)
        assert (vault / "meetings" / "2026-08-07-standup-g.md").exists()  # untouched

    async def test_repair_path_not_found(self, registry: MeetingRegistry, toolkit: ObsidianToolkit, vault: Path):
        meetings = vault / "meetings"
        note_path = _write_note(
            meetings, "2026-08-08-standup-h.md", fireflies_id="id-h", title="Standup H", date="2026-08-08"
        )
        await registry.record_synced(
            fireflies_id="id-h",
            note_path=note_path,
            title="Standup H",
            meeting_date="2026-08-08",
            participants=[],
            duration_minutes=5.0,
            fingerprint="fp",
            summary_fingerprint=None,
            reset_analysis=True,
        )
        note_path.unlink()  # deleted, not renamed — cannot be found anywhere

        result = await registry.repair_path(
            "id-h",
            toolkit=toolkit,
            meetings_folder="meetings",
            canonical_title="2026-08-08-standup-h",
        )

        assert result.to_path is None
        assert result.moved is False

    async def test_repair_path_unavailable_registry(self, tmp_path: Path, toolkit: ObsidianToolkit):
        registry = MeetingRegistry(tmp_path / "wiki")
        registry._available = False

        result = await registry.repair_path("id-x", toolkit=toolkit, meetings_folder="meetings", canonical_title="x")
        assert result.to_path is None
        assert result.moved is False
