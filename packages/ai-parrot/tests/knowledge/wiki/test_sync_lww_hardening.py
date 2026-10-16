"""Clock-safe, origin-checked sync LWW and the stub-based pull window (FEAT-692 TASK-4403)."""

from datetime import datetime, timedelta, timezone

import pytest

from parrot.knowledge.wiki.operations import SyncPagesInput, op_sync_pull, op_sync_push
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store
from parrot.knowledge.wiki.sync import (
    SYNC_CLOCK_SKEW,
    _sync_records,
    normalize_sync_stamp,
    parse_sync_stamp,
)


def _mem(concept_id: str, body: str, updated_at: str | None, asserted_by: str = "human:a") -> WikiPageRecord:
    """Build a memory-origin record."""
    return WikiPageRecord(
        concept_id=concept_id,
        title=concept_id,
        body=body,
        origin="memory",
        asserted_by=asserted_by,
        updated_at=updated_at,
    )


def _stamp(delta: timedelta) -> str:
    """An ISO stamp `delta` away from now."""
    return (datetime.now(tz=timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%S+00:00")


@pytest.fixture
def store(tmp_path):
    """An isolated SQLite wiki plane."""
    root = tmp_path / "wiki"
    root.mkdir()
    return create_wiki_store(root, wiki_name="t", backend="sqlite")


@pytest.fixture
def other_store(tmp_path):
    """A second isolated SQLite wiki plane."""
    root = tmp_path / "other"
    root.mkdir()
    return create_wiki_store(root, wiki_name="o", backend="sqlite")


async def _push(store, *pages, **context):
    """Run op_sync_push and return its report data."""
    result = await op_sync_push(store, SyncPagesInput(pages=list(pages)), wiki_name="t", **context)
    return result.data


class TestStampParsing:
    def test_z_and_offset_are_equal(self):
        assert parse_sync_stamp("2026-10-05T10:00:00Z") == parse_sync_stamp("2026-10-05T10:00:00+00:00")

    def test_offset_converted_to_utc(self):
        assert parse_sync_stamp("2026-10-05T12:00:00+02:00") == datetime(2026, 10, 5, 10, tzinfo=timezone.utc)

    def test_fractional_and_naive(self):
        assert parse_sync_stamp("2026-10-05T10:00:00.250000").microsecond == 250000
        assert parse_sync_stamp("2026-10-05T10:00:00").tzinfo is timezone.utc

    @pytest.mark.parametrize("value", [None, "", "not-a-date", 42])
    def test_unparseable_is_none(self, value):
        assert parse_sync_stamp(value) is None

    def test_normalize_clamps_future(self):
        now = datetime(2026, 10, 16, tzinfo=timezone.utc)
        assert normalize_sync_stamp("9999-01-01T00:00:00Z", now=now) == (now + SYNC_CLOCK_SKEW).isoformat()
        assert normalize_sync_stamp("2026-10-05T10:00:00Z", now=now) == "2026-10-05T10:00:00+00:00"


class TestPush:
    async def test_z_format_newer_stamp_wins(self, store):
        await store.upsert_pages([_mem("memory:x", "server", "2026-10-05T10:00:00+00:00")])
        data = await _push(store, _mem("memory:x", "client", "2026-10-05T10:00:00.5Z"))
        assert data["updated"] == 1
        assert (await store.get_page("memory:x"))["body"] == "client"

    async def test_older_offset_stamp_loses_despite_larger_string(self, store):
        # "…T11:00:00+02:00" sorts after "…T10:00:00+00:00" as a string but is 09:00 UTC.
        await store.upsert_pages([_mem("memory:x", "server", "2026-10-05T10:00:00+00:00")])
        data = await _push(store, _mem("memory:x", "client", "2026-10-05T11:00:00+02:00"))
        assert data["skipped_older"] == 1
        assert (await store.get_page("memory:x"))["body"] == "server"

    async def test_far_future_stamp_is_clamped(self, store):
        await _push(store, _mem("memory:x", "future", "9999-01-01T00:00:00+00:00"))
        stored = parse_sync_stamp((await store.get_page("memory:x"))["updated_at"])
        assert stored <= datetime.now(tz=timezone.utc) + SYNC_CLOCK_SKEW
        data = await _push(store, _mem("memory:x", "later", _stamp(timedelta(minutes=10))))
        assert data["updated"] == 1
        assert (await store.get_page("memory:x"))["body"] == "later"

    async def test_unparseable_stamp_never_wins(self, store):
        await store.upsert_pages([_mem("memory:x", "server", "2026-10-05T10:00:00+00:00")])
        data = await _push(store, _mem("memory:x", "client", "yesterday"))
        assert data["skipped_older"] == 1
        assert (await store.get_page("memory:x"))["body"] == "server"

    async def test_non_memory_page_is_never_overwritten(self, store):
        await store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id="mod:a",
                    title="a",
                    body="scanned",
                    origin="ingest",
                    updated_at="2026-01-01T00:00:00+00:00",
                )
            ]
        )
        data = await _push(store, _mem("mod:a", "hijack", _stamp(timedelta(0))))
        assert data["skipped_foreign"] == 1
        page = await store.get_page("mod:a")
        assert (page["body"], page["origin"]) == ("scanned", "ingest")

    async def test_caller_identity_overrides_asserted_by(self, store):
        await _push(
            store,
            _mem("memory:x", "b", "2026-10-05T10:00:00Z", asserted_by="human:spoof"),
            caller_identity="human:real",
        )
        assert (await store.get_page("memory:x"))["asserted_by"] == "human:real"

    async def test_client_asserted_by_kept_without_caller_identity(self, store):
        await _push(store, _mem("memory:x", "b", "2026-10-05T10:00:00Z", asserted_by="human:a"))
        assert (await store.get_page("memory:x"))["asserted_by"] == "human:a"


class TestLocalEngine:
    async def test_non_memory_destination_is_skipped_foreign(self, store, other_store):
        await store.upsert_pages([_mem("mod:a", "memory", _stamp(timedelta(0)))])
        await other_store.upsert_pages(
            [
                WikiPageRecord(
                    concept_id="mod:a",
                    title="a",
                    body="scanned",
                    origin="ingest",
                    updated_at="2026-01-01T00:00:00+00:00",
                )
            ]
        )
        report, selected = await _sync_records(
            source=store, destination=other_store, direction="push", env="o", dry_run=False, skip_asserted_by=None
        )
        assert report.skipped_foreign == 1
        assert (await other_store.get_page("mod:a"))["body"] == "scanned"


class TestPull:
    async def test_pull_fetches_bodies_only_for_the_returned_page(self, store, monkeypatch):
        await store.upsert_pages(
            [_mem(f"memory:p{i:03d}", "body", f"2026-01-01T00:00:{i:02d}+00:00") for i in range(30)]
        )
        calls = 0
        real_get_page = store.get_page

        async def counting_get_page(*args, **kwargs):
            nonlocal calls
            calls += 1
            return await real_get_page(*args, **kwargs)

        monkeypatch.setattr(store, "get_page", counting_get_page)
        seen: list[str] = []
        cursor = None
        while True:
            calls = 0
            data = (await op_sync_pull(store, SyncPagesInput(limit=7, cursor=cursor))).data
            assert calls <= 7
            seen.extend(page["concept_id"] for page in data["pages"])
            cursor = data["next_cursor"]
            if cursor is None:
                break
        assert seen == [f"memory:p{i:03d}" for i in range(30)]

    async def test_since_with_z_stamp(self, store):
        await store.upsert_pages(
            [
                _mem("memory:old", "b", "2026-01-01T00:00:00+00:00"),
                _mem("memory:new", "b", "2026-01-02T00:00:00+00:00"),
            ]
        )
        data = (await op_sync_pull(store, SyncPagesInput(since="2026-01-01T00:00:00Z"))).data
        assert [page["concept_id"] for page in data["pages"]] == ["memory:new"]

    async def test_skip_asserted_by(self, store):
        await store.upsert_pages(
            [
                _mem("memory:mine", "b", "2026-01-01T00:00:00+00:00", asserted_by="human:me"),
                _mem("memory:theirs", "b", "2026-01-01T00:00:00+00:00", asserted_by="human:you"),
            ]
        )
        data = (await op_sync_pull(store, SyncPagesInput(skip_asserted_by="human:me"))).data
        assert [page["concept_id"] for page in data["pages"]] == ["memory:theirs"]
