"""Two-plane sync tests — both planes are local stores; no Arango needed.

FEAT-461 Module 5 (TASK-2466): `sync_push` / `sync_pull` — record
selection, last-write-wins, author-filtered pull, and append-if-absent
note merge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parrot.knowledge.wiki.bookkeeper import WikiBookkeeper
from parrot.knowledge.wiki.project import load_effective_config
from parrot.knowledge.wiki.store import BaseWikiStore, WikiPageRecord
from parrot.knowledge.wiki.sync import (
    SyncError,
    _open_plane,
    default_local_identity,
    sync_pull,
    sync_push,
)


def _page(cid: str, **kw) -> WikiPageRecord:
    """Shorthand page-record builder (mirrors test_store.py's helper)."""
    defaults = {
        "concept_id": cid,
        "title": kw.pop("title", cid.replace("-", " ").title()),
        "category": kw.pop("category", "concept"),
        "summary": kw.pop("summary", f"Summary of {cid}"),
        "body": kw.pop("body", f"# {cid}\n\nBody of {cid}."),
        "origin": kw.pop("origin", "memory"),
    }
    defaults.update(kw)
    return WikiPageRecord(**defaults)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WIKI_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)


@pytest.fixture
def two_planes(tmp_path: Path) -> tuple[Path, BaseWikiStore, BaseWikiStore]:
    """A local sqlite plane + a "dev" sqlite plane, both under `tmp_path`.

    The `dev` overlay points `storage_dir` at a sibling directory
    (`WikiEnvOverlay.storage_dir` — a permitted overlay field), so the two
    planes are genuinely independent on-disk stores without needing two
    separate project roots. Both are real `BaseWikiStore`s — no Arango.
    """
    root = tmp_path
    parrot_dir = root / ".parrot"
    parrot_dir.mkdir()
    (parrot_dir / "wiki.json").write_text(json.dumps({"backend": "sqlite"}), encoding="utf-8")
    (parrot_dir / "wiki.dev.json").write_text(
        json.dumps({"backend": "sqlite", "storage_dir": ".parrot/wiki-remote"}),
        encoding="utf-8",
    )
    local_config = load_effective_config(root, env="local").config
    remote_config = load_effective_config(root, env="dev").config
    local_store = _open_plane(root, local_config)
    remote_store = _open_plane(root, remote_config)
    return root, local_store, remote_store


class TestSelection:
    async def test_push_moves_memory_pages_only(self, two_planes) -> None:
        root, local, remote = two_planes
        await local.upsert_pages([_page("mem-1", origin="memory"), _page("ingest-1", origin="ingest")])
        report = await sync_push(root, target_env="dev")
        assert report.created == 1
        remote_ids = {p["concept_id"] for p in await remote.list_pages(limit=1000)}
        assert remote_ids == {"mem-1"}

    async def test_push_moves_asserted_edges_of_synced_pages(self, two_planes) -> None:
        root, local, remote = two_planes
        await local.upsert_pages([_page("mem-1"), _page("mem-2"), _page("ingest-1", origin="ingest")])
        await local.add_edges(
            [
                ("mem-1", "mem-2", "references", "asserted"),
                ("ingest-1", "mem-2", "references", "extracted"),
            ]
        )
        await sync_push(root, target_env="dev")
        remote_edges = await remote.dump_edges()
        assert ("mem-1", "mem-2", "references") in {(e["src"], e["dst"], e["rel"]) for e in remote_edges}
        # The extracted edge's src ("ingest-1") was never synced as a page,
        # so its edge must not appear at the destination either.
        assert not any(e["src"] == "ingest-1" for e in remote_edges)


class TestLWW:
    async def test_newer_source_wins_and_preserves_stamp(self, two_planes) -> None:
        root, local, remote = two_planes
        await remote.upsert_pages([_page("mem-1", body="old", updated_at="2020-01-01T00:00:00+00:00")])
        await local.upsert_pages([_page("mem-1", body="new", updated_at="2025-01-01T00:00:00+00:00")])
        report = await sync_push(root, target_env="dev")
        assert report.updated == 1
        page = await remote.get_page("mem-1")
        assert "new" in page["body"]
        assert page["updated_at"] == "2025-01-01T00:00:00+00:00"

    async def test_equal_or_older_skipped(self, two_planes) -> None:
        root, local, remote = two_planes
        await remote.upsert_pages([_page("mem-1", body="remote", updated_at="2025-01-01T00:00:00+00:00")])
        await local.upsert_pages([_page("mem-1", body="local-older", updated_at="2020-01-01T00:00:00+00:00")])
        report = await sync_push(root, target_env="dev")
        assert report.skipped_older == 1
        assert report.updated == 0
        page = await remote.get_page("mem-1")
        assert "remote" in page["body"]


class TestPullAuthorFilter:
    async def test_own_records_skipped_by_default(self, two_planes) -> None:
        root, local, remote = two_planes
        identity = default_local_identity()
        await remote.upsert_pages(
            [_page("mem-mine", asserted_by=identity), _page("mem-theirs", asserted_by="human:other")]
        )
        report = await sync_pull(root, target_env="dev")
        assert report.skipped_own == 1
        assert report.created == 1
        local_ids = {p["concept_id"] for p in await local.list_pages(limit=1000)}
        assert local_ids == {"mem-theirs"}

    async def test_include_own_pulls_everything(self, two_planes) -> None:
        root, _local, remote = two_planes
        identity = default_local_identity()
        await remote.upsert_pages(
            [_page("mem-mine", asserted_by=identity), _page("mem-theirs", asserted_by="human:other")]
        )
        report = await sync_pull(root, target_env="dev", include_own=True)
        assert report.skipped_own == 0
        assert report.created == 2


class TestNoteMerge:
    async def test_two_sided_notes_union_date_ordered(self, two_planes) -> None:
        root, local, remote = two_planes
        base_body = "# mem-1\n\nMain content."
        remote_body = base_body + "\n\n> **Note (2024-01-01, human:alice):** Remote note."
        local_body = base_body + "\n\n> **Note (2024-02-01, human:bob):** Local note."
        await remote.upsert_pages([_page("mem-1", body=remote_body, updated_at="2020-01-01T00:00:00+00:00")])
        await local.upsert_pages([_page("mem-1", body=local_body, updated_at="2025-01-01T00:00:00+00:00")])
        report = await sync_push(root, target_env="dev")
        assert report.updated == 1
        merged = (await remote.get_page("mem-1"))["body"]
        assert "Remote note." in merged
        assert "Local note." in merged
        # Date-ordered: 2024-01-01 before 2024-02-01.
        assert merged.index("Remote note.") < merged.index("Local note.")

    async def test_note_merge_idempotent(self, two_planes) -> None:
        root, local, remote = two_planes
        body = "# mem-1\n\nContent.\n\n> **Note (2024-01-01, human:alice):** A note."
        await local.upsert_pages([_page("mem-1", body=body, updated_at="2025-01-01T00:00:00+00:00")])
        first = await sync_push(root, target_env="dev")
        assert first.created == 1
        first_body = (await remote.get_page("mem-1"))["body"]

        second = await sync_push(root, target_env="dev")
        assert second.skipped_older == 1
        second_body = (await remote.get_page("mem-1"))["body"]
        assert first_body == second_body
        assert first_body.count("A note.") == 1


class TestSafety:
    async def test_dry_run_applies_nothing(self, two_planes) -> None:
        root, local, remote = two_planes
        await local.upsert_pages([_page("mem-1")])
        report = await sync_push(root, target_env="dev", dry_run=True)
        assert report.created == 1
        assert report.dry_run is True
        assert await remote.get_page("mem-1") is None

    async def test_report_counts_accurate(self, two_planes) -> None:
        root, local, remote = two_planes
        await remote.upsert_pages([_page("mem-old", updated_at="2020-01-01T00:00:00+00:00")])
        await local.upsert_pages(
            [
                _page("mem-new"),
                _page("mem-old", updated_at="2020-01-01T00:00:00+00:00"),
                _page("ingest-1", origin="ingest"),
            ]
        )
        report = await sync_push(root, target_env="dev")
        assert report.created == 1  # mem-new
        assert report.skipped_older == 1  # mem-old, equal stamp
        assert report.updated == 0


class TestAudit:
    async def test_applied_changes_are_bookkeeper_logged(self, two_planes) -> None:
        root, local, _remote = two_planes
        await local.upsert_pages([_page("mem-1")])
        await sync_push(root, target_env="dev")
        remote_config = load_effective_config(root, env="dev").config
        log = WikiBookkeeper().read_log(remote_config.storage_path(root))
        assert "SYNC_PUSH" in log

    async def test_dry_run_logs_nothing(self, two_planes) -> None:
        root, local, _remote = two_planes
        await local.upsert_pages([_page("mem-1")])
        await sync_push(root, target_env="dev", dry_run=True)
        remote_config = load_effective_config(root, env="dev").config
        log_path = remote_config.storage_path(root) / WikiBookkeeper.LOG_FILENAME
        assert not log_path.exists()


class TestUnreachableRemote:
    async def test_unreachable_arango_raises_clean_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        class _HangingArango:
            def __init__(self, **kwargs) -> None:
                pass

            async def initialize(self) -> None:
                raise ConnectionError("no route to host")

            async def close(self) -> None:
                return None

        import parrot.knowledge.wiki.arango_store as arango_module

        monkeypatch.setattr(arango_module, "ArangoDBWikiStore", _HangingArango)
        root = tmp_path
        parrot_dir = root / ".parrot"
        parrot_dir.mkdir()
        (parrot_dir / "wiki.json").write_text(json.dumps({"backend": "sqlite"}), encoding="utf-8")
        (parrot_dir / "wiki.prod.json").write_text(
            json.dumps({"backend": "arangodb", "arango_database": "wiki_x"}),
            encoding="utf-8",
        )
        with pytest.raises(SyncError, match="prod"):
            await sync_push(root, target_env="prod")
