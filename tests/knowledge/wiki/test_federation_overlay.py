"""Tests for FEAT-566 Module 13: Federation overlay namespace routing.

Overlay namespaces allow bare-id routing (issue:xyz without ledger:: prefix),
and support both outgoing (overlay->code) and incoming (code->overlay) edges.
"""

import pytest
from parrot.knowledge.wiki.federation import (
    FederatedWikiStore,
    NamespaceHandle,
)
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot.knowledge.wiki.store import SQLiteWikiStore, WikiPageRecord


class TestBareOverlayIdRouting:
    """Bare overlay IDs route to the overlay namespace without prefix."""

    @pytest.fixture
    async def federated_with_overlay(self, tmp_path):
        """FederatedWikiStore with a ledger overlay namespace."""
        # Create local plane (code plane)
        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="sym:pkg.py#Func",
                title="Func",
                summary="A function",
                body="Function body",
            )
        ])

        # Create ledger overlay store (read-only)
        ledger_writable = SQLiteWikiStore(tmp_path / "ledger" / "wiki.db")
        await ledger_writable.upsert_pages([
            WikiPageRecord(
                concept_id="issue:3f8a1c9e",
                title="Issue 3f8a1c9e",
                summary="A test issue",
                body="Issue body",
            ),
            WikiPageRecord(
                concept_id="task:TASK-001",
                title="Task 001",
                summary="A task",
                body="Task body",
            ),
            WikiPageRecord(
                concept_id="spec:FEAT-001",
                title="Spec 001",
                summary="A spec",
                body="Spec body",
            ),
        ])
        ledger = SQLiteWikiStore(tmp_path / "ledger" / "wiki.db", read_only=True)

        return FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="ledger",
                    store=ledger,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "ledger"),
                        overlay_prefixes=["issue", "task", "spec", "insight"],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "ledger",
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_bare_overlay_id_routes_to_overlay(self, federated_with_overlay):
        """Unqualified overlay IDs (issue:xyz) route to the ledger overlay."""
        # Bare "issue:" should route to ledger overlay
        page = await federated_with_overlay.get_page("issue:3f8a1c9e")
        assert page is not None
        # Returned qualified with overlay namespace
        assert page["concept_id"] == "ledger::issue:3f8a1c9e"
        assert page["title"] == "Issue 3f8a1c9e"

    @pytest.mark.asyncio
    async def test_bare_task_id_routes_to_overlay(self, federated_with_overlay):
        """Bare task: ids route to the ledger overlay."""
        page = await federated_with_overlay.get_page("task:TASK-001")
        assert page is not None
        assert page["concept_id"] == "ledger::task:TASK-001"
        assert page["title"] == "Task 001"

    @pytest.mark.asyncio
    async def test_bare_spec_id_routes_to_overlay(self, federated_with_overlay):
        """Bare spec: ids route to the ledger overlay."""
        page = await federated_with_overlay.get_page("spec:FEAT-001")
        assert page is not None
        assert page["concept_id"] == "ledger::spec:FEAT-001"

    @pytest.mark.asyncio
    async def test_qualified_overlay_id_still_works(self, federated_with_overlay):
        """Qualified overlay IDs (ledger::issue:xyz) still route correctly."""
        page = await federated_with_overlay.get_page("ledger::issue:3f8a1c9e")
        assert page is not None
        assert page["concept_id"] == "ledger::issue:3f8a1c9e"

    @pytest.mark.asyncio
    async def test_bare_code_id_still_routes_locally(self, federated_with_overlay):
        """Bare code plane IDs (sym:, file:, etc.) still route to local plane."""
        page = await federated_with_overlay.get_page("sym:pkg.py#Func")
        assert page is not None
        # Local plane ids are NOT qualified
        assert page["concept_id"] == "sym:pkg.py#Func"
        assert page["namespace"] is None

    @pytest.mark.asyncio
    async def test_unknown_overlay_id_returns_none(self, federated_with_overlay):
        """Unknown overlay IDs return None."""
        page = await federated_with_overlay.get_page("issue:unknown")
        assert page is None


class TestOverlayOutgoingEdges:
    """Outgoing edges from overlay to code plane are unqualified."""

    @pytest.fixture
    async def federated_with_edges(self, tmp_path):
        """FederatedWikiStore where overlay issue points to code symbol."""
        # Local plane with a symbol
        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="sym:federation.py#FederatedWikiStore",
                title="FederatedWikiStore",
                summary="The federated store",
                body="Store body",
            )
        ])

        # Ledger overlay with an issue that references the local symbol
        ledger_writable = SQLiteWikiStore(tmp_path / "ledger" / "wiki.db")
        await ledger_writable.upsert_pages([
            WikiPageRecord(
                concept_id="issue:abc123",
                title="Routing Issue",
                summary="Issue with federation",
                body="Issue body",
            ),
            WikiPageRecord(
                concept_id="sym:federation.py#FederatedWikiStore",
                title="FederatedWikiStore",
                summary="The federated store",
                body="Store body",
            ),
        ])
        # Issue points to the symbol (stored unqualified in ledger since it's code-plane)
        await ledger_writable.add_edges([
            ("issue:abc123", "sym:federation.py#FederatedWikiStore", "references")
        ])
        ledger = SQLiteWikiStore(tmp_path / "ledger" / "wiki.db", read_only=True)

        return FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="ledger",
                    store=ledger,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "ledger"),
                        overlay_prefixes=["issue", "task", "spec", "insight"],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "ledger",
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_overlay_outgoing_to_code_unqualified(self, federated_with_edges):
        """Neighbors from overlay to code plane return unqualified."""
        neighbors = await federated_with_edges.neighbors("ledger::issue:abc123")
        assert len(neighbors) > 0
        # The neighbor should be unqualified (not ledger::sym:...)
        neighbor = neighbors[0]
        assert neighbor["concept_id"] == "sym:federation.py#FederatedWikiStore"
        assert neighbor["namespace"] is None

    @pytest.mark.asyncio
    async def test_bare_overlay_neighbor_also_unqualified(self, federated_with_edges):
        """Same test using bare overlay ID (issue:abc123)."""
        neighbors = await federated_with_edges.neighbors("issue:abc123")
        assert len(neighbors) > 0
        neighbor = neighbors[0]
        assert neighbor["concept_id"] == "sym:federation.py#FederatedWikiStore"
        assert neighbor["namespace"] is None


class TestLocalIncomingFromOverlay:
    """Local seeds see incoming edges from overlay namespaces."""

    @pytest.fixture
    async def federated_with_incoming(self, tmp_path):
        """FederatedWikiStore where overlay issue points TO local symbol."""
        # Local plane with a symbol
        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="sym:federation.py#FederatedWikiStore",
                title="FederatedWikiStore",
                summary="The federated store",
                body="Store body",
            )
        ])

        # Ledger overlay with issues that reference the local symbol
        ledger_writable = SQLiteWikiStore(tmp_path / "ledger" / "wiki.db")
        await ledger_writable.upsert_pages([
            WikiPageRecord(
                concept_id="issue:xyz789",
                title="Overlay Issue",
                summary="Issue in overlay",
                body="Issue body",
            ),
            # Store unqualified in ledger (code plane reference)
            WikiPageRecord(
                concept_id="sym:federation.py#FederatedWikiStore",
                title="FederatedWikiStore (stub)",
                summary="The federated store",
                body="",
            ),
        ])
        # Issue points TO the local symbol (unqualified in ledger)
        await ledger_writable.add_edges([
            ("issue:xyz789", "sym:federation.py#FederatedWikiStore", "touches")
        ])
        ledger = SQLiteWikiStore(tmp_path / "ledger" / "wiki.db", read_only=True)

        return FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="ledger",
                    store=ledger,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "ledger"),
                        overlay_prefixes=["issue", "task", "spec", "insight"],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "ledger",
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_local_seed_sees_incoming_from_overlay(self, federated_with_incoming):
        """Local seed neighbors(direction='in') includes overlay incoming edges."""
        # Query the local symbol with incoming edges
        neighbors = await federated_with_incoming.neighbors(
            "sym:federation.py#FederatedWikiStore",
            direction="in"
        )
        # Should include the overlay issue pointing to it
        concept_ids = [n["concept_id"] for n in neighbors]
        assert "ledger::issue:xyz789" in concept_ids

    @pytest.mark.asyncio
    async def test_local_seed_both_direction_includes_overlay(self, federated_with_incoming):
        """Local seed neighbors(direction='both') includes overlay edges."""
        neighbors = await federated_with_incoming.neighbors(
            "sym:federation.py#FederatedWikiStore",
            direction="both"
        )
        concept_ids = [n["concept_id"] for n in neighbors]
        assert "ledger::issue:xyz789" in concept_ids


class TestOverlayPrefixCollisions:
    """Prefix collisions are rejected at construction time."""

    @pytest.mark.asyncio
    async def test_overlay_prefix_collision_raises(self, tmp_path):
        """Two overlays claiming the same prefix raise ValueError."""
        # Create local store
        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="sym:placeholder.py#Local",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])

        # Create ledger1 store and read-only copy
        ledger1_w = SQLiteWikiStore(tmp_path / "ledger1" / "wiki.db")
        await ledger1_w.upsert_pages([
            WikiPageRecord(
                concept_id="issue:placeholder-1",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])
        ledger1 = SQLiteWikiStore(tmp_path / "ledger1" / "wiki.db", read_only=True)

        # Create ledger2 store and read-only copy
        ledger2_w = SQLiteWikiStore(tmp_path / "ledger2" / "wiki.db")
        await ledger2_w.upsert_pages([
            WikiPageRecord(
                concept_id="issue:placeholder-2",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])
        ledger2 = SQLiteWikiStore(tmp_path / "ledger2" / "wiki.db", read_only=True)

        # Both overlays claim "issue" - collision
        with pytest.raises(ValueError, match="Overlay prefix"):
            FederatedWikiStore(
                local=local,
                local_name="local",
                handles=[
                    NamespaceHandle(
                        name="ledger1",
                        store=ledger1,
                        config=WikiNamespaceConfig(
                            store=str(tmp_path / "ledger1"),
                            overlay_prefixes=["issue", "task"],
                        ),
                        origin="repo",
                        storage_dir=tmp_path / "ledger1",
                    ),
                    NamespaceHandle(
                        name="ledger2",
                        store=ledger2,
                        config=WikiNamespaceConfig(
                            store=str(tmp_path / "ledger2"),
                            overlay_prefixes=["issue", "spec"],
                        ),
                        origin="repo",
                        storage_dir=tmp_path / "ledger2",
                    ),
                ],
            )

    @pytest.mark.asyncio
    async def test_unique_prefixes_no_collision(self, tmp_path):
        """Non-overlapping prefixes do not raise."""
        # Create local store
        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="sym:placeholder.py#Local",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])

        # Create ledger1 store and read-only copy
        ledger1_w = SQLiteWikiStore(tmp_path / "ledger1" / "wiki.db")
        await ledger1_w.upsert_pages([
            WikiPageRecord(
                concept_id="issue:placeholder-1",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])
        ledger1 = SQLiteWikiStore(tmp_path / "ledger1" / "wiki.db", read_only=True)

        # Create ledger2 store and read-only copy
        ledger2_w = SQLiteWikiStore(tmp_path / "ledger2" / "wiki.db")
        await ledger2_w.upsert_pages([
            WikiPageRecord(
                concept_id="issue:placeholder-2",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])
        ledger2 = SQLiteWikiStore(tmp_path / "ledger2" / "wiki.db", read_only=True)

        # Different prefixes - no collision
        fed = FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="ledger1",
                    store=ledger1,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "ledger1"),
                        overlay_prefixes=["issue", "task"],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "ledger1",
                ),
                NamespaceHandle(
                    name="ledger2",
                    store=ledger2,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "ledger2"),
                        overlay_prefixes=["spec"],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "ledger2",
                ),
            ],
        )
        assert fed is not None

    @pytest.mark.asyncio
    async def test_empty_overlay_no_collision(self, tmp_path):
        """Overlays with empty prefixes do not affect collision detection."""
        # Create local store
        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="sym:placeholder.py#Local",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])

        # Create ledger1 store and read-only copy
        ledger1_w = SQLiteWikiStore(tmp_path / "ledger1" / "wiki.db")
        await ledger1_w.upsert_pages([
            WikiPageRecord(
                concept_id="issue:placeholder-1",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])
        ledger1 = SQLiteWikiStore(tmp_path / "ledger1" / "wiki.db", read_only=True)

        # Create ledger2 store and read-only copy
        ledger2_w = SQLiteWikiStore(tmp_path / "ledger2" / "wiki.db")
        await ledger2_w.upsert_pages([
            WikiPageRecord(
                concept_id="issue:placeholder-2",
                title="Placeholder",
                summary="Placeholder page so the SQLite plane exists on disk.",
                body="placeholder",
            )
        ])
        ledger2 = SQLiteWikiStore(tmp_path / "ledger2" / "wiki.db", read_only=True)

        # One overlay has empty prefixes (not an overlay)
        fed = FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="regular",
                    store=ledger1,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "ledger1"),
                        overlay_prefixes=[],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "ledger1",
                ),
                NamespaceHandle(
                    name="ledger",
                    store=ledger2,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "ledger2"),
                        overlay_prefixes=["issue"],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "ledger2",
                ),
            ],
        )
        assert fed is not None


class TestRegression:
    """Existing federation behavior unchanged without overlays (regression test)."""

    @pytest.fixture
    async def federated_no_overlay(self, tmp_path):
        """Regular FederatedWikiStore with no overlays."""
        # Create local plane
        local = SQLiteWikiStore(tmp_path / "local" / "wiki.db")
        await local.upsert_pages([
            WikiPageRecord(
                concept_id="file:local.py",
                title="Local File",
                summary="Local file",
                body="Local body",
            )
        ])

        # Create foreign namespace (not an overlay)
        foreign_writable = SQLiteWikiStore(tmp_path / "foreign" / "wiki.db")
        await foreign_writable.upsert_pages([
            WikiPageRecord(
                concept_id="file:foreign.py",
                title="Foreign File",
                summary="Foreign file",
                body="Foreign body",
            )
        ])
        foreign = SQLiteWikiStore(tmp_path / "foreign" / "wiki.db", read_only=True)

        return FederatedWikiStore(
            local=local,
            local_name="local",
            handles=[
                NamespaceHandle(
                    name="other",
                    store=foreign,
                    config=WikiNamespaceConfig(
                        store=str(tmp_path / "foreign"),
                        overlay_prefixes=[],
                    ),
                    origin="repo",
                    storage_dir=tmp_path / "foreign",
                )
            ],
        )

    @pytest.mark.asyncio
    async def test_bare_local_id_routes_local(self, federated_no_overlay):
        """Without overlays, bare IDs route to local plane."""
        page = await federated_no_overlay.get_page("file:local.py")
        assert page is not None
        assert page["concept_id"] == "file:local.py"
        assert page["namespace"] is None

    @pytest.mark.asyncio
    async def test_qualified_foreign_routes_foreign(self, federated_no_overlay):
        """Without overlays, qualified IDs route to foreign namespace."""
        page = await federated_no_overlay.get_page("other::file:foreign.py")
        assert page is not None
        assert page["concept_id"] == "other::file:foreign.py"
        assert page["namespace"] == "other"

    @pytest.mark.asyncio
    async def test_unknown_bare_id_returns_none(self, federated_no_overlay):
        """Without overlays, unknown bare IDs return None."""
        page = await federated_no_overlay.get_page("file:unknown.py")
        assert page is None
