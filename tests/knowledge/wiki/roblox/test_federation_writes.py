"""Cross-namespace edge ownership regressions (FEAT-532 TASK-2903).

Exercises the real federation relaxation directly against
``FederatedWikiStore`` (no Roblox-specific code involved yet — TASK-2904/
TASK-2905 build the neighbor-routing/health layer on top of this). Named
under ``tests/knowledge/wiki/roblox/`` per this task's own file table,
even though it tests generic federation machinery, because it is the
regression suite motivated by and scoped to the Roblox code-to-API
linking use case (spec §"Code-to-API linking").
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
async def fed(tmp_path: Path) -> FederatedWikiStore:
    """A local (writable) plane federated with a read-only "roblox" plane."""
    local = await _build_plane(
        tmp_path / "local",
        [("file:Main.luau", "Main", "requires the API")],
    )
    await _build_plane(
        tmp_path / "roblox",
        [("class/Players", "Players", "the Players service")],
    )
    roblox_store = SQLiteWikiStore(tmp_path / "roblox" / "wiki.db", read_only=True)
    return FederatedWikiStore(
        local=local,
        local_name="local",
        handles=[_handle("roblox", roblox_store, tmp_path / "roblox")],
        skipped=[],
    )


# ---------------------------------------------------------------------------
# test_foreign_destination_reference_is_local
# ---------------------------------------------------------------------------


async def test_foreign_destination_reference_is_local(fed: FederatedWikiStore):
    """Reference is stored locally with unchanged foreign id and provenance."""
    written = await fed.add_edges([("file:Main.luau", "roblox::class/Players", "references", "code-to-api")])
    assert written == 1

    stored = await fed._local.dump_edges()
    match = next(e for e in stored if e["src"] == "file:Main.luau")
    assert match["dst"] == "roblox::class/Players"  # unchanged, verbatim
    assert match["rel"] == "references"
    # Provenance survives the 4-element tuple form.
    if "provenance" in match:
        assert match["provenance"] == "code-to-api"


async def test_foreign_destination_survives_without_foreign_plane_online():
    """Do not require the foreign plane to be online to retain an
    already-known reference — a namespace with NO resolved handle at
    all still accepts the edge (it is a pure string check)."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        local = await _build_plane(tmp_path / "local", [("file:Main.luau", "Main", "x")])
        fed = FederatedWikiStore(local=local, local_name="local", handles=[], skipped=[])

        written = await fed.add_edges([("file:Main.luau", "roblox::class/Players", "references")])
        assert written == 1


# ---------------------------------------------------------------------------
# test_foreign_sources_and_page_writes_refused
# ---------------------------------------------------------------------------


async def test_foreign_sources_and_page_writes_refused(fed: FederatedWikiStore):
    """All existing foreign mutation prohibitions remain enforced."""
    # Foreign SOURCE is still forbidden, even though foreign destinations
    # are now allowed — this is the asymmetry the spec calls for.
    with pytest.raises(ValueError, match="requires --ns roblox"):
        await fed.add_edges([("roblox::class/Players", "file:Main.luau", "references")])

    # Foreign page writes remain forbidden.
    with pytest.raises(ValueError):
        await fed.upsert_pages([WikiPageRecord(concept_id="roblox::class/Evil", title="Evil")])

    # Foreign delete/embedding writes remain forbidden.
    with pytest.raises(ValueError):
        await fed.delete_page("roblox::class/Players")
    with pytest.raises(ValueError):
        await fed.upsert_embedding("roblox::class/Players", [0.1])


# ---------------------------------------------------------------------------
# test_replace_source_slice_foreign_destination
# ---------------------------------------------------------------------------


async def test_replace_source_slice_foreign_destination(fed: FederatedWikiStore):
    """Source-owned replacement removes obsolete outgoing external edges."""
    await fed.replace_source_slice(
        "src:Main.luau",
        [WikiPageRecord(concept_id="file:Main.luau", title="Main", source_id="src:Main.luau")],
        [("file:Main.luau", "roblox::class/Players", "references")],
    )
    first_pass = await fed._local.dump_edges()
    assert any(e["dst"] == "roblox::class/Players" for e in first_pass)

    # Re-ingest the same source with the API use REMOVED — the old
    # outgoing external edge must be gone, not accumulated.
    await fed.replace_source_slice(
        "src:Main.luau",
        [WikiPageRecord(concept_id="file:Main.luau", title="Main", source_id="src:Main.luau")],
        [],
    )
    second_pass = await fed._local.dump_edges()
    assert not any(e["dst"] == "roblox::class/Players" for e in second_pass)


async def test_replace_source_slice_rejects_foreign_source(fed: FederatedWikiStore):
    with pytest.raises(ValueError):
        await fed.replace_source_slice(
            "src:x",
            [WikiPageRecord(concept_id="file:x.luau", title="x")],
            [("roblox::class/Players", "file:x.luau", "references")],
        )


# ---------------------------------------------------------------------------
# test_invalid_batch_is_atomic
# ---------------------------------------------------------------------------


async def test_invalid_batch_is_atomic(fed: FederatedWikiStore):
    """A forbidden source in a batch leaves no earlier edge inserted."""
    before = await fed._local.dump_edges()

    with pytest.raises(ValueError):
        await fed.add_edges(
            [
                ("file:Main.luau", "roblox::class/Players", "references"),  # valid
                ("roblox::class/Evil", "file:Main.luau", "references"),  # forbidden source
            ]
        )

    after = await fed._local.dump_edges()
    assert after == before  # nothing from the batch was written


async def test_invalid_batch_is_atomic_in_replace_source_slice(fed: FederatedWikiStore):
    before = await fed._local.dump_edges()

    with pytest.raises(ValueError):
        await fed.replace_source_slice(
            "src:Main.luau",
            [WikiPageRecord(concept_id="file:Main.luau", title="Main")],
            [
                ("file:Main.luau", "roblox::class/Players", "references"),
                ("roblox::class/Evil", "file:Main.luau", "references"),
            ],
        )

    after = await fed._local.dump_edges()
    assert after == before
