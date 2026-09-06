"""Two-plane outgoing/incoming/scoped neighbor-routing tests (FEAT-532 TASK-2904).

Builds a local "code" plane and a read-only "roblox" API plane, links
them via the TASK-2903 edge-destination exception, and exercises
``FederatedWikiStore.neighbors()``'s outgoing hydration and incoming
local-reference routing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from parrot.knowledge.wiki.federation import FederatedWikiStore, NamespaceHandle
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


async def _build_plane(
    storage_dir: Path,
    pages: list[tuple[str, str, str]],
    edges: list[tuple[str, str, str]] | None = None,
) -> SQLiteWikiStore:
    store = SQLiteWikiStore(storage_dir / "wiki.db")
    await store.upsert_pages(
        [WikiPageRecord(concept_id=cid, title=title, summary=body, body=body) for cid, title, body in pages]
    )
    if edges:
        await store.add_edges(list(edges))
    return store


def _handle(name: str, store: SQLiteWikiStore, storage_dir: Path) -> NamespaceHandle:
    return NamespaceHandle(
        name=name,
        store=store,
        config=WikiNamespaceConfig(store=str(storage_dir), weight=1.0),
        origin="repo",
        storage_dir=storage_dir,
        read_only=True,
    )


@pytest.fixture
async def two_plane_fed(tmp_path: Path) -> FederatedWikiStore:
    """local: Main.luau --references--> roblox::class/Players.

    The roblox plane itself has class/Players --extends--> class/Instance
    (an internal edge, never qualified within its own plane).
    """
    local = await _build_plane(
        tmp_path / "local",
        [("file:Main.luau", "Main", "requires the Players service")],
        edges=[("file:Main.luau", "roblox::class/Players", "references")],
    )
    await _build_plane(
        tmp_path / "roblox",
        [
            ("class/Players", "Players", "the Players service"),
            ("class/Instance", "Instance", "the Instance base class"),
        ],
        edges=[("class/Players", "class/Instance", "extends")],
    )
    roblox_store = SQLiteWikiStore(tmp_path / "roblox" / "wiki.db", read_only=True)
    return FederatedWikiStore(
        local=local,
        local_name="local",
        handles=[_handle("roblox", roblox_store, tmp_path / "roblox")],
        skipped=[],
    )


# ---------------------------------------------------------------------------
# test_outgoing_api_stub_no_double_prefix
# ---------------------------------------------------------------------------


async def test_outgoing_api_stub_no_double_prefix(two_plane_fed: FederatedWikiStore):
    """Qualified class destination resolves once with API title."""
    rows = await two_plane_fed.neighbors("file:Main.luau", direction="out")
    assert len(rows) == 1
    row = rows[0]
    assert row["concept_id"] == "roblox::class/Players"  # exactly one prefix
    assert "::" not in row["concept_id"].removeprefix("roblox::")
    assert row["title"] == "Players"  # hydrated from the real API page
    assert row["namespace"] == "roblox"


# ---------------------------------------------------------------------------
# test_incoming_references_from_local_plane
# ---------------------------------------------------------------------------


async def test_incoming_references_from_local_plane(two_plane_fed: FederatedWikiStore):
    """API page expansion includes local callers without API-plane writes."""
    rows = await two_plane_fed.neighbors("roblox::class/Players")

    concept_ids = {r["concept_id"] for r in rows}
    # The class's own internal edge (extends Instance) is present, qualified once.
    assert "roblox::class/Instance" in concept_ids
    # The local caller is present too, unprefixed (it IS local).
    assert "file:Main.luau" in concept_ids

    # Never a write into the read-only API plane.
    roblox_handle = two_plane_fed.namespaces["roblox"]
    assert roblox_handle.store.read_only is True


async def test_incoming_references_direction_out_excludes_them(two_plane_fed: FederatedWikiStore):
    rows = await two_plane_fed.neighbors("roblox::class/Players", direction="out")
    concept_ids = {r["concept_id"] for r in rows}
    assert "file:Main.luau" not in concept_ids
    assert "roblox::class/Instance" in concept_ids


# ---------------------------------------------------------------------------
# test_rel_direction_and_scope
# ---------------------------------------------------------------------------


async def test_rel_direction_and_scope(two_plane_fed: FederatedWikiStore):
    """Filters and scoped foreign reads retain the correct local callers only."""
    referenced_only = await two_plane_fed.neighbors("roblox::class/Players", rel="references")
    concept_ids = {r["concept_id"] for r in referenced_only}
    assert "file:Main.luau" in concept_ids
    assert "roblox::class/Instance" not in concept_ids  # that edge is "extends"

    extends_only = await two_plane_fed.neighbors("roblox::class/Players", rel="extends")
    concept_ids = {r["concept_id"] for r in extends_only}
    assert "roblox::class/Instance" in concept_ids
    assert "file:Main.luau" not in concept_ids

    # A scoped(single-namespace) read still finds the local caller via
    # the retained origin_local, without changing what a write there targets.
    scoped = two_plane_fed.scoped("roblox")
    scoped_rows = await scoped.neighbors("class/Players")
    scoped_ids = {r["concept_id"] for r in scoped_rows}
    assert "roblox::class/Instance" in scoped_ids
    assert "local::file:Main.luau" in scoped_ids or "file:Main.luau" in scoped_ids


# ---------------------------------------------------------------------------
# test_missing_namespace_degrades
# ---------------------------------------------------------------------------


async def test_missing_namespace_degrades(tmp_path: Path):
    """Unknown/unbuilt namespace does not break local neighbor results."""
    local = await _build_plane(
        tmp_path / "local",
        [("file:Main.luau", "Main", "x")],
        edges=[
            ("file:Main.luau", "roblox::class/Players", "references"),
            ("file:Main.luau", "unbuilt::whatever", "references"),
        ],
    )
    fed = FederatedWikiStore(local=local, local_name="local", handles=[], skipped=[])

    rows = await fed.neighbors("file:Main.luau", direction="out")
    concept_ids = {r["concept_id"] for r in rows}
    # Both stubs still present, retained verbatim -- no crash, no fabricated title.
    assert concept_ids == {"roblox::class/Players", "unbuilt::whatever"}
    for row in rows:
        assert not row.get("title")  # never fabricated


async def test_missing_namespace_seed_returns_empty_not_raise(two_plane_fed: FederatedWikiStore):
    assert await two_plane_fed.neighbors("nope::class/Foo") == []


# ---------------------------------------------------------------------------
# test_source_removed_reverse_lookup_updates
# ---------------------------------------------------------------------------


async def test_source_removed_reverse_lookup_updates(tmp_path: Path):
    """Deletion/replacement automatically updates incoming results without a stale cache."""
    local = await _build_plane(tmp_path / "local", [])
    await _build_plane(tmp_path / "roblox", [("class/Players", "Players", "the Players service")])
    roblox_store = SQLiteWikiStore(tmp_path / "roblox" / "wiki.db", read_only=True)
    fed = FederatedWikiStore(
        local=local,
        local_name="local",
        handles=[_handle("roblox", roblox_store, tmp_path / "roblox")],
        skipped=[],
    )

    # First ingest: Main.luau references the API — established THROUGH
    # replace_source_slice (as the real scanner/enrichment pipeline
    # would) so a later re-ingest of the same source_id can clean it up.
    await fed.replace_source_slice(
        "src:Main.luau",
        [WikiPageRecord(concept_id="file:Main.luau", title="Main", source_id="src:Main.luau")],
        [("file:Main.luau", "roblox::class/Players", "references")],
    )
    before = await fed.neighbors("roblox::class/Players", direction="in")
    assert any(r["concept_id"] == "file:Main.luau" for r in before)

    # Re-ingest the SAME source with the API use removed — a live query,
    # never a stale cache, must stop finding it as a caller.
    await fed.replace_source_slice(
        "src:Main.luau",
        [WikiPageRecord(concept_id="file:Main.luau", title="Main", source_id="src:Main.luau")],
        [],
    )
    after = await fed.neighbors("roblox::class/Players", direction="in")
    assert not any(r["concept_id"] == "file:Main.luau" for r in after)
