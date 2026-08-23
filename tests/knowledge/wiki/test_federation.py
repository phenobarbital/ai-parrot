"""Tests for multi-wiki federation (FEAT-450, wiki/federation.py).

Two real SQLite planes under ``tmp_path`` — no mocks for the store
layer: the retrieval plane is fast enough to federate for real.
"""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from parrot.knowledge.wiki.federation import (
    FederatedWikiStore,
    NamespaceHandle,
    NamespaceSkip,
    normalize_scores,
    open_namespace_store,
    resolve_namespaces,
)
from parrot.knowledge.wiki.project import (
    GlobalWikiRegistry,
    WikiNamespaceConfig,
    WikiProjectConfig,
    save_global_registry,
    save_project_config,
)
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


async def _build_plane(
    storage_dir: Path,
    pages: list[tuple[str, str, str]],
    edges: list[tuple[str, str, str]] | None = None,
) -> SQLiteWikiStore:
    """Create and populate a SQLite plane at ``storage_dir``."""
    store = SQLiteWikiStore(storage_dir / "wiki.db")
    await store.upsert_pages(
        [
            WikiPageRecord(concept_id=cid, title=title, summary=body, body=body)
            for cid, title, body in pages
        ]
    )
    if edges:
        await store.add_edges(list(edges))
    return store


def _handle(
    name: str, store: SQLiteWikiStore, storage_dir: Path, weight: float = 1.0
) -> NamespaceHandle:
    return NamespaceHandle(
        name=name,
        store=store,
        config=WikiNamespaceConfig(store=str(storage_dir), weight=weight),
        origin="repo",
        storage_dir=storage_dir,
        read_only=True,
    )


@pytest.fixture
async def fed(tmp_path: Path) -> FederatedWikiStore:
    """A federation of the local plane plus one read-only namespace."""
    local = await _build_plane(
        tmp_path / "local",
        [
            ("file:README.md", "README", "alpha local readme"),
            ("file:a.py", "a", "alpha local code"),
        ],
        edges=[("file:README.md", "file:a.py", "references")],
    )
    await _build_plane(
        tmp_path / "other",
        [
            ("file:README.md", "README", "alpha other readme"),
            ("file:a.py", "a", "alpha other code"),
        ],
        edges=[("file:README.md", "file:a.py", "references")],
    )
    other = SQLiteWikiStore(tmp_path / "other" / "wiki.db", read_only=True)
    return FederatedWikiStore(
        local=local,
        local_name="local",
        handles=[_handle("other", other, tmp_path / "other")],
        skipped=[],
    )


class TestSearchMerge:
    """Fan-out, qualification and per-namespace normalisation."""

    async def test_search_qualifies_and_merges(self, fed: FederatedWikiStore):
        rows = await fed.search_fts("alpha", limit=10)
        ids = {row["concept_id"] for row in rows}
        assert "file:README.md" in ids
        assert "other::file:README.md" in ids
        assert all(0.0 <= row["score"] <= 1.0 for row in rows)
        assert all("namespace" in row for row in rows)
        by_id = {row["concept_id"]: row for row in rows}
        assert by_id["file:README.md"]["namespace"] is None
        assert by_id["other::file:README.md"]["namespace"] == "other"

    async def test_rows_sorted_by_score(self, fed: FederatedWikiStore):
        rows = await fed.search_fts("alpha", limit=10)
        scores = [row["score"] for row in rows]
        assert scores == sorted(scores, reverse=True)

    async def test_limit_is_respected(self, fed: FederatedWikiStore):
        rows = await fed.search_fts("alpha", limit=2)
        assert len(rows) == 2

    async def test_small_plane_does_not_dominate(self, tmp_path: Path):
        """Per-namespace min-max keeps a tiny corpus from outranking a big one."""
        local = await _build_plane(
            tmp_path / "big",
            [
                (f"file:big{i}.py", f"big{i}", f"alpha token{i} " * (i + 1))
                for i in range(40)
            ],
        )
        await _build_plane(
            tmp_path / "small", [("file:small.py", "small", "alpha")]
        )
        small = SQLiteWikiStore(tmp_path / "small" / "wiki.db", read_only=True)
        fed = FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[_handle("small", small, tmp_path / "small")],
        )
        rows = await fed.search_fts("alpha", limit=50)
        # Each namespace's best hit normalises to 1.0 — the merge is fair.
        assert max(r["score"] for r in rows if r["namespace"] is None) == 1.0
        assert max(r["score"] for r in rows if r["namespace"] == "small") == 1.0

    async def test_weight_is_applied(self, tmp_path: Path):
        local = await _build_plane(
            tmp_path / "local", [("file:a.py", "a", "alpha local")]
        )
        await _build_plane(
            tmp_path / "other", [("file:b.py", "b", "alpha other")]
        )
        other = SQLiteWikiStore(tmp_path / "other" / "wiki.db", read_only=True)
        fed = FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[_handle("other", other, tmp_path / "other", weight=0.25)],
        )
        rows = {r["concept_id"]: r["score"] for r in await fed.search_fts("alpha")}
        assert rows["file:a.py"] == 1.0
        assert rows["other::file:b.py"] == 0.25

    async def test_normalize_scores_all_equal(self):
        rows = [{"score": -3.0}, {"score": -3.0}]
        assert [r["score"] for r in normalize_scores(rows)] == [1.0, 1.0]

    async def test_namespace_failure_is_skipped(self, fed: FederatedWikiStore):
        broken = AsyncMock()
        broken.search_fts.side_effect = RuntimeError("boom")
        fed.namespaces["broken"] = _handle(
            "broken", broken, Path("/nonexistent")
        )
        rows = await fed.search_fts("alpha", limit=10)
        assert rows  # the healthy namespaces still answered
        assert [s.name for s in fed.last_skipped] == ["broken"]
        assert fed.last_skipped[0].reason == "unreachable"

    async def test_list_pages_merges_without_ranking(self, fed: FederatedWikiStore):
        rows = await fed.list_pages(limit=100)
        ids = {row["concept_id"] for row in rows}
        assert {"file:README.md", "other::file:README.md"} <= ids


class TestRouting:
    """``get_page`` / ``neighbors`` route on the ``ns::`` prefix."""

    async def test_get_page_routes(self, fed: FederatedWikiStore):
        foreign = await fed.get_page("other::file:README.md")
        assert foreign is not None
        assert foreign["concept_id"] == "other::file:README.md"
        assert foreign["namespace"] == "other"
        assert "other readme" in foreign["body"]

        local = await fed.get_page("file:README.md")
        assert local is not None
        assert local["concept_id"] == "file:README.md"
        assert "local readme" in local["body"]

    async def test_unknown_namespace(self, fed: FederatedWikiStore):
        assert await fed.get_page("nope::file:x") is None
        assert await fed.neighbors("nope::file:x") == []

    async def test_neighbors_are_qualified(self, fed: FederatedWikiStore):
        neighbours = await fed.neighbors("other::file:README.md")
        assert neighbours
        assert all(n["concept_id"].startswith("other::") for n in neighbours)
        assert all(n["namespace"] == "other" for n in neighbours)

        local_neighbours = await fed.neighbors("file:README.md")
        assert local_neighbours
        assert all("::" not in n["concept_id"] for n in local_neighbours)

    async def test_missing_page_returns_none(self, fed: FederatedWikiStore):
        assert await fed.get_page("other::file:missing.md") is None


class TestScoped:
    """Selector semantics for ``--ns``."""

    async def test_all_and_none_are_the_federation(self, fed: FederatedWikiStore):
        assert fed.scoped(None) is fed
        assert fed.scoped("all") is fed

    async def test_local_only(self, fed: FederatedWikiStore):
        rows = await fed.scoped("local").search_fts("alpha", limit=10)
        assert rows
        assert all("::" not in row["concept_id"] for row in rows)

    async def test_single_namespace_keeps_qualified_ids(
        self, fed: FederatedWikiStore
    ):
        scoped = fed.scoped("other")
        rows = await scoped.search_fts("alpha", limit=10)
        assert rows
        assert all(row["concept_id"].startswith("other::") for row in rows)
        page = await scoped.get_page("other::file:README.md")
        assert page is not None and page["concept_id"] == "other::file:README.md"

    async def test_subset_selector(self, fed: FederatedWikiStore):
        rows = await fed.scoped("local,other").search_fts("alpha", limit=10)
        ids = {row["concept_id"] for row in rows}
        assert "file:README.md" in ids
        assert "other::file:README.md" in ids

    async def test_unknown_namespace_raises(self, fed: FederatedWikiStore):
        with pytest.raises(KeyError):
            fed.scoped("nope")


class TestWrites:
    """Writes land on the local plane; foreign ids are refused."""

    async def test_writes_are_local(self, fed: FederatedWikiStore):
        await fed.upsert_pages(
            [WikiPageRecord(concept_id="file:new.md", title="new")]
        )
        assert await fed.get_page("file:new.md") is not None
        assert await fed.namespaces["other"].store.get_page("file:new.md") is None

    async def test_qualified_id_is_refused(self, fed: FederatedWikiStore):
        with pytest.raises(ValueError, match="requires --ns other"):
            await fed.delete_page("other::file:README.md")
        with pytest.raises(ValueError):
            await fed.upsert_pages(
                [WikiPageRecord(concept_id="other::file:x", title="x")]
            )
        with pytest.raises(ValueError):
            await fed.add_edges([("file:a.py", "other::file:b.py", "references")])
        with pytest.raises(ValueError):
            await fed.upsert_embedding("other::file:x", [0.1])

    async def test_scoped_namespace_write_targets_that_plane(
        self, fed: FederatedWikiStore, tmp_path: Path
    ):
        """``scoped(name)`` accepts its own qualified ids on write paths."""
        writable = SQLiteWikiStore(tmp_path / "other" / "wiki.db")
        scoped = FederatedWikiStore(
            local=writable, local_name="other", qualify_local=True
        )
        await scoped.upsert_pages(
            [WikiPageRecord(concept_id="file:written.md", title="w")]
        )
        assert await scoped.get_page("other::file:written.md") is not None


class TestStats:
    """``stats`` keeps the local shape and adds the namespace block."""

    async def test_stats_shape(self, fed: FederatedWikiStore):
        stats = await fed.stats()
        for key in ("pages", "edges", "sources", "embeddings", "total_tokens"):
            assert key in stats
        assert stats["local"] == "local"
        assert stats["skipped"] == []
        block = stats["namespaces"]["other"]
        assert block["status"] == "ok"
        assert block["pages"] == 2
        assert block["kind"] == "store"
        assert block["backend"] == "sqlite"
        assert block["origin"] == "repo"
        assert block["read_only"] is True

    async def test_stats_reports_resolve_time_skips(self, fed: FederatedWikiStore):
        fed.skipped.append(
            NamespaceSkip(name="ghost", reason="unbuilt", detail="no plane")
        )
        stats = await fed.stats()
        assert [s["name"] for s in stats["skipped"]] == ["ghost"]

    async def test_stats_marks_a_failing_namespace(self, fed: FederatedWikiStore):
        broken = AsyncMock()
        broken.stats.side_effect = RuntimeError("down")
        fed.namespaces["broken"] = _handle("broken", broken, Path("/nope"))
        stats = await fed.stats()
        assert stats["namespaces"]["broken"]["status"] == "unreachable"
        assert any(s["name"] == "broken" for s in stats["skipped"])


class TestResolveNamespaces:
    """Registry merge + per-kind opening."""

    async def test_resolves_store_and_path_kinds(self, tmp_path: Path):
        await _build_plane(tmp_path / "planes" / "s", [("file:x", "x", "body")])
        other_root = tmp_path / "proj"
        (other_root / ".parrot" / "wiki").mkdir(parents=True)
        save_project_config(other_root, WikiProjectConfig(wiki_name="proj"))
        await _build_plane(other_root / ".parrot" / "wiki", [("file:y", "y", "b")])

        config = WikiProjectConfig(
            namespaces={
                "sdir": WikiNamespaceConfig(store=str(tmp_path / "planes" / "s")),
                "proj": WikiNamespaceConfig(path=str(other_root)),
            }
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert skipped == []
        assert sorted(h.name for h in handles) == ["proj", "sdir"]
        assert all(h.read_only for h in handles)
        assert all(isinstance(h.store, SQLiteWikiStore) for h in handles)
        assert all(h.store.read_only for h in handles)

    async def test_relative_repo_path_resolves_against_root(self, tmp_path: Path):
        await _build_plane(tmp_path / "planes", [("file:x", "x", "body")])
        config = WikiProjectConfig(
            namespaces={"rel": WikiNamespaceConfig(store="planes")}
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert skipped == [] and handles[0].storage_dir == tmp_path / "planes"

    async def test_skips_unbuilt_with_hint(self, tmp_path: Path):
        (tmp_path / "x").mkdir()
        config = WikiProjectConfig(
            namespaces={"x": WikiNamespaceConfig(path=str(tmp_path / "x"))}
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert not handles
        assert skipped[0].reason == "unbuilt"
        assert "wikitoolkit build --path" in skipped[0].hint

    async def test_skips_missing_root(self, tmp_path: Path):
        config = WikiProjectConfig(
            namespaces={"gone": WikiNamespaceConfig(path=str(tmp_path / "gone"))}
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert not handles and skipped[0].reason == "unbuilt"

    async def test_only_filter(self, tmp_path: Path):
        await _build_plane(tmp_path / "a", [("file:x", "x", "b")])
        await _build_plane(tmp_path / "b", [("file:y", "y", "b")])
        config = WikiProjectConfig(
            namespaces={
                "a": WikiNamespaceConfig(store=str(tmp_path / "a")),
                "b": WikiNamespaceConfig(store=str(tmp_path / "b")),
            }
        )
        handles, _ = await resolve_namespaces(
            tmp_path,
            config,
            only={"b"},
            registry_path=tmp_path / "absent.json",
        )
        assert [h.name for h in handles] == ["b"]

    async def test_repo_entry_wins_over_global(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("PARROT_HOME", str(tmp_path / "home"))
        await _build_plane(tmp_path / "repo-plane", [("file:x", "x", "b")])
        await _build_plane(tmp_path / "global-plane", [("file:y", "y", "b")])
        save_global_registry(
            GlobalWikiRegistry(
                namespaces={
                    "dup": WikiNamespaceConfig(store=str(tmp_path / "global-plane")),
                    "only-global": WikiNamespaceConfig(
                        store=str(tmp_path / "global-plane")
                    ),
                }
            )
        )
        config = WikiProjectConfig(
            namespaces={"dup": WikiNamespaceConfig(store=str(tmp_path / "repo-plane"))}
        )
        handles, skipped = await resolve_namespaces(tmp_path, config)
        assert skipped == []
        by_name = {h.name: h for h in handles}
        assert by_name["dup"].origin == "repo"
        assert by_name["dup"].storage_dir == tmp_path / "repo-plane"
        assert by_name["only-global"].origin == "global"

    async def test_arango_entry_uses_credentials_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("LEGAL_HOST", "db.example")
        monkeypatch.setenv("LEGAL_PORT", "9999")
        monkeypatch.setenv("LEGAL_PASSWORD", "s3cret")
        captured: dict[str, Any] = {}

        class _FakeArango:
            closed = False

            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)
                self.read_only = kwargs.get("read_only", False)

            async def initialize(self) -> None:
                return None

            async def close(self) -> None:
                type(self).closed = True

        import parrot.knowledge.wiki.arango_store as arango_module

        monkeypatch.setattr(arango_module, "ArangoDBWikiStore", _FakeArango)
        config = WikiProjectConfig(
            namespaces={
                "legal": WikiNamespaceConfig(
                    database="wiki_legal", credentials_env="LEGAL"
                )
            }
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert skipped == [] and [h.name for h in handles] == ["legal"]
        assert captured["database"] == "wiki_legal"
        assert captured["arango_params"]["host"] == "db.example"
        assert captured["arango_params"]["port"] == 9999
        assert captured["arango_params"]["password"] == "s3cret"
        # A foreign namespace is opened read-only (never provisioned)...
        assert captured["read_only"] is True
        assert handles[0].read_only is True
        # ...and the probe connection is dropped, so the store re-connects
        # on whatever loop actually serves the read.
        assert _FakeArango.closed is True

    async def test_unreachable_arango_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        class _HangingArango:
            def __init__(self, **kwargs: Any) -> None:
                self.read_only = kwargs.get("read_only", False)

            async def initialize(self) -> None:
                raise ConnectionError("no route to host")

            async def close(self) -> None:
                return None

        import parrot.knowledge.wiki.arango_store as arango_module

        monkeypatch.setattr(arango_module, "ArangoDBWikiStore", _HangingArango)
        config = WikiProjectConfig(
            namespaces={"legal": WikiNamespaceConfig(database="wiki_legal")}
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert not handles
        assert skipped[0].reason == "unreachable"

    async def test_open_namespace_store_writable(self, tmp_path: Path):
        await _build_plane(tmp_path / "w", [("file:x", "x", "b")])
        store, storage_dir = await open_namespace_store(
            "w",
            WikiNamespaceConfig(store=str(tmp_path / "w")),
            base_dir=tmp_path,
            read_only=False,
        )
        assert storage_dir == tmp_path / "w"
        assert isinstance(store, SQLiteWikiStore) and not store.read_only
        await store.upsert_pages(
            [WikiPageRecord(concept_id="file:new", title="n")]
        )
        assert await store.get_page("file:new") is not None


class TestReviewRegressions:
    """Regressions from the FEAT-450 code review (F1, F2, F5, L3, H1, H2)."""

    async def test_scoped_write_strips_the_namespace_prefix(
        self, tmp_path: Path
    ):
        """F1 — the backing plane must never see a ``ns::`` id."""
        store = await _build_plane(tmp_path / "other", [])
        scoped = FederatedWikiStore(store, "other", qualify_local=True)
        await scoped.upsert_pages([
            WikiPageRecord(
                concept_id="other::file:x.py",
                node_id="other::file:x.py",
                title="x",
            )
        ])
        await scoped.add_edges(
            [("other::file:x.py", "other::file:y.py", "references")]
        )
        await scoped.replace_source_slice(
            "src",
            [WikiPageRecord(concept_id="other::file:z.py", title="z")],
            [("other::file:z.py", "other::file:x.py", "references")],
        )

        raw_ids = {r["concept_id"] for r in await store.list_pages(limit=50)}
        assert raw_ids == {"file:x.py", "file:z.py"}
        assert all(
            "::" not in e["src"] and "::" not in e["dst"]
            for e in await store.dump_edges()
        )
        # The federated view still presents them qualified.
        page = await scoped.get_page("other::file:x.py")
        assert page is not None
        assert page["concept_id"] == "other::file:x.py"
        assert page["node_id"] == "other::file:x.py"

    async def test_scoped_write_still_rejects_another_namespace(
        self, tmp_path: Path
    ):
        store = await _build_plane(tmp_path / "other", [])
        scoped = FederatedWikiStore(store, "other", qualify_local=True)
        with pytest.raises(ValueError, match="requires --ns elsewhere"):
            await scoped.upsert_pages(
                [WikiPageRecord(concept_id="elsewhere::file:x", title="x")]
            )

    async def test_list_pages_represents_every_namespace(self, tmp_path: Path):
        """F2 — a busy local plane must not starve the namespaces."""
        local = await _build_plane(
            tmp_path / "local",
            [(f"file:l{i}.py", f"l{i}", "body") for i in range(40)],
        )
        await _build_plane(tmp_path / "other", [("file:o.py", "o", "body")])
        other = SQLiteWikiStore(tmp_path / "other" / "wiki.db", read_only=True)
        fed = FederatedWikiStore(
            local, "local", [_handle("other", other, tmp_path / "other")]
        )
        rows = await fed.list_pages(limit=20)
        assert len(rows) == 20
        assert "other::file:o.py" in {row["concept_id"] for row in rows}

    async def test_list_pages_still_honours_the_limit(self, tmp_path: Path):
        local = await _build_plane(
            tmp_path / "local",
            [(f"file:l{i}.py", f"l{i}", "b") for i in range(10)],
        )
        await _build_plane(
            tmp_path / "other",
            [(f"file:o{i}.py", f"o{i}", "b") for i in range(10)],
        )
        other = SQLiteWikiStore(tmp_path / "other" / "wiki.db", read_only=True)
        fed = FederatedWikiStore(
            local, "local", [_handle("other", other, tmp_path / "other")]
        )
        rows = await fed.list_pages(limit=6)
        assert len(rows) == 6
        assert len({row["concept_id"] for row in rows}) == 6

    async def test_concurrent_reads_keep_their_own_skips(self, fed):
        """F5 — skip notes are task-local, not shared instance state."""
        broken = AsyncMock()
        broken.search_fts.side_effect = RuntimeError("boom")
        fed.namespaces["broken"] = _handle("broken", broken, Path("/nope"))

        async def one() -> list[str]:
            await fed.search_fts("alpha", limit=5)
            return [skip.name for skip in fed.last_skipped]

        first, second = await asyncio.gather(one(), one())
        assert first == ["broken"]
        assert second == ["broken"]

    async def test_stale_plane_is_reported_with_a_rebuild_hint(
        self, tmp_path: Path
    ):
        """L3 — a pre-migration plane is `invalid`, not an opaque failure."""
        await _build_plane(tmp_path / "old", [("file:x", "x", "body")])
        db = tmp_path / "old" / "wiki.db"
        with contextlib.closing(sqlite3.connect(str(db))) as conn:
            conn.execute("ALTER TABLE pages DROP COLUMN asserted_by")
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ("-wal", "-shm"):
            db.with_name(db.name + suffix).unlink(missing_ok=True)

        config = WikiProjectConfig(
            namespaces={"old": WikiNamespaceConfig(store=str(tmp_path / "old"))}
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert not handles
        assert skipped[0].reason == "invalid"
        assert "predates the current schema" in skipped[0].detail
        assert "wikitoolkit build" in skipped[0].hint

    async def test_healthy_plane_passes_the_schema_probe(self, tmp_path: Path):
        await _build_plane(tmp_path / "ok", [("file:x", "x", "body")])
        config = WikiProjectConfig(
            namespaces={"ok": WikiNamespaceConfig(store=str(tmp_path / "ok"))}
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert skipped == [] and [h.name for h in handles] == ["ok"]

    async def test_arango_namespace_never_provisions(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """H1 — an unbuilt arango namespace is a skip, not a new database."""
        created: list[str] = []

        class _FakeArango:
            def __init__(self, **kwargs: Any) -> None:
                self.read_only = kwargs.get("read_only", False)

            async def initialize(self) -> None:
                if self.read_only:
                    raise FileNotFoundError(
                        "ArangoDB database 'wiki_typo' does not exist"
                    )
                created.append("wiki_typo")

            async def close(self) -> None:
                return None

        import parrot.knowledge.wiki.arango_store as arango_module

        monkeypatch.setattr(arango_module, "ArangoDBWikiStore", _FakeArango)
        config = WikiProjectConfig(
            namespaces={"legal": WikiNamespaceConfig(database="wiki_typo")}
        )
        handles, skipped = await resolve_namespaces(
            tmp_path, config, registry_path=tmp_path / "absent.json"
        )
        assert not handles
        assert skipped[0].reason == "unbuilt"
        assert created == []
