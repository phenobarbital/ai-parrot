"""Tests for parrot.knowledge.graphindex.persist_sqlite.SQLitePersistence (FEAT-240)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import aiosqlite
import pytest

from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_ctx(tenant_id: str = "test_tenant") -> Any:
    """Create a minimal TenantContext-like object with just tenant_id."""
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


@pytest.fixture
def ctx():
    """Default tenant context for tests."""
    return _make_ctx("test_tenant")


@pytest.fixture
def persistence(tmp_path):
    """SQLitePersistence instance using a temp directory."""
    return SQLitePersistence(db_dir=tmp_path)


@pytest.fixture
def module_node():
    """A module node with mtime and sha1 in domain_tags."""
    return UniversalNode(
        node_id="n1",
        kind=NodeKind.SYMBOL,
        title="my_module",
        source_uri="mod/file.py",
        domain_tags={"symbol_type": "module", "sha1": "abc123def456" * 3 + "ab12", "mtime": 100.0},
    )


@pytest.fixture
def canonical_node():
    """A canonical Odoo model node with synthetic source_uri."""
    return UniversalNode(
        node_id="n2",
        kind=NodeKind.SYMBOL,
        title="res.partner",
        source_uri="odoo-model://res.partner",
        domain_tags={"symbol_type": "odoo_model", "model_name": "res.partner"},
    )


@pytest.fixture
def class_node():
    """An odoo_model_class node."""
    return UniversalNode(
        node_id="n3",
        kind=NodeKind.SYMBOL,
        title="ResPartner",
        source_uri="mod/file.py",
        domain_tags={"symbol_type": "odoo_model_class", "lineno": 5, "end_lineno": 20},
    )


@pytest.fixture
def field_node():
    """An odoo_field node."""
    return UniversalNode(
        node_id="n4",
        kind=NodeKind.SYMBOL,
        title="vat_verified",
        source_uri="mod/file.py",
        summary="VAT Verified",
        domain_tags={"symbol_type": "odoo_field", "field_type": "Boolean"},
    )


@pytest.fixture
def sample_edge(class_node, canonical_node):
    """A DEFINES edge between class and canonical node."""
    return UniversalEdge(
        source_id=class_node.node_id,
        target_id=canonical_node.node_id,
        kind=EdgeKind.DEFINES,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSQLitePersistence:
    """Tests for SQLitePersistence backend."""

    @pytest.mark.asyncio
    async def test_persist_creates_db_file(self, persistence, ctx, module_node):
        """persist_graph creates the database file."""
        db_path = Path(persistence._db_dir) / f"{ctx.tenant_id}.db"
        assert not db_path.exists()

        await persistence.persist_graph(ctx, [module_node], [])

        assert db_path.exists()

    @pytest.mark.asyncio
    async def test_persist_roundtrip_node_count(
        self, persistence, ctx, module_node, canonical_node, class_node
    ):
        """persist_graph returns correct node/edge count."""
        nodes = [module_node, canonical_node, class_node]
        result = await persistence.persist_graph(ctx, nodes, [])

        assert result["nodes_persisted"] == 3
        assert result["edges_persisted"] == 0

    @pytest.mark.asyncio
    async def test_persist_roundtrip_read_back(
        self, persistence, ctx, module_node, canonical_node
    ):
        """Nodes persisted can be read back from the DB."""
        await persistence.persist_graph(ctx, [module_node, canonical_node], [])

        db_path = persistence._db_path(ctx)
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        try:
            async with conn.execute("SELECT node_id FROM nodes ORDER BY node_id") as cur:
                rows = await cur.fetchall()
                node_ids = {r["node_id"] for r in rows}
        finally:
            await conn.close()

        assert module_node.node_id in node_ids
        assert canonical_node.node_id in node_ids

    @pytest.mark.asyncio
    async def test_persist_edges_stored(
        self, persistence, ctx, class_node, canonical_node, sample_edge
    ):
        """Edges are stored and readable."""
        await persistence.persist_graph(
            ctx, [class_node, canonical_node], [sample_edge]
        )

        db_path = persistence._db_path(ctx)
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        try:
            async with conn.execute("SELECT * FROM edges") as cur:
                rows = await cur.fetchall()
        finally:
            await conn.close()

        assert len(rows) == 1
        assert rows[0]["source_id"] == sample_edge.source_id
        assert rows[0]["kind"] == "defines"

    @pytest.mark.asyncio
    async def test_persist_fts5_populated(
        self, persistence, ctx, module_node, canonical_node
    ):
        """FTS5 index is populated with node titles."""
        await persistence.persist_graph(ctx, [module_node, canonical_node], [])

        db_path = persistence._db_path(ctx)
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        try:
            async with conn.execute(
                "SELECT node_id FROM nodes_fts WHERE nodes_fts MATCH ?",
                ("partner",),
            ) as cur:
                rows = await cur.fetchall()
        finally:
            await conn.close()

        node_ids = {r["node_id"] for r in rows}
        assert canonical_node.node_id in node_ids

    @pytest.mark.asyncio
    async def test_replace_slice_preserves_canonical(
        self, persistence, ctx, module_node, canonical_node, class_node, sample_edge
    ):
        """replace_document_slice does NOT delete canonical nodes (odoo-model:// URIs)."""
        # First persist everything
        await persistence.persist_graph(
            ctx,
            [module_node, canonical_node, class_node],
            [sample_edge],
        )

        # Now replace mod/file.py slice — canonical node must survive
        extends_edge = UniversalEdge(
            source_id=class_node.node_id,
            target_id=canonical_node.node_id,
            kind=EdgeKind.EXTENDS,
        )
        new_class = UniversalNode(
            node_id=class_node.node_id,
            kind=NodeKind.SYMBOL,
            title="ResPartner",
            source_uri="mod/file.py",
            domain_tags={"symbol_type": "odoo_model_class"},
        )
        await persistence.replace_document_slice(
            ctx,
            "mod/file.py",
            [new_class, canonical_node],
            [extends_edge],
        )

        db_path = persistence._db_path(ctx)
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        try:
            async with conn.execute(
                "SELECT node_id FROM nodes WHERE source_uri = ?",
                ("odoo-model://res.partner",),
            ) as cur:
                row = await cur.fetchone()
        finally:
            await conn.close()

        assert row is not None, "Canonical node must survive replace_document_slice"

    @pytest.mark.asyncio
    async def test_replace_slice_replaces_regular_nodes(
        self, persistence, ctx, module_node, class_node
    ):
        """replace_document_slice replaces non-canonical nodes for the document."""
        await persistence.persist_graph(ctx, [module_node, class_node], [])

        updated_module = UniversalNode(
            node_id=module_node.node_id,
            kind=NodeKind.SYMBOL,
            title="my_module_updated",
            source_uri="mod/file.py",
            domain_tags={"symbol_type": "module", "sha1": "newsha1" * 5 + "12345", "mtime": 200.0},
        )
        await persistence.replace_document_slice(
            ctx, "mod/file.py", [updated_module], []
        )

        db_path = persistence._db_path(ctx)
        conn = await aiosqlite.connect(str(db_path))
        conn.row_factory = aiosqlite.Row
        try:
            async with conn.execute(
                "SELECT title FROM nodes WHERE node_id = ?",
                (module_node.node_id,),
            ) as cur:
                row = await cur.fetchone()
        finally:
            await conn.close()

        assert row["title"] == "my_module_updated"

    @pytest.mark.asyncio
    async def test_is_stale_not_indexed(self, persistence, ctx):
        """is_stale returns True when the file has never been indexed."""
        result = await persistence.is_stale(ctx, "mod/file.py", 100.0, "abc123")
        assert result is True

    @pytest.mark.asyncio
    async def test_is_stale_mtime_match(self, persistence, ctx, module_node):
        """is_stale returns False when mtime and sha1 both match stored values."""
        await persistence.persist_graph(ctx, [module_node], [])

        # The module_node has mtime=100.0 and sha1="abc123def456..."
        stored_sha1 = module_node.domain_tags["sha1"]
        stored_mtime = module_node.domain_tags["mtime"]

        result = await persistence.is_stale(
            ctx, "mod/file.py", stored_mtime, stored_sha1
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_is_stale_sha1_differs(self, persistence, ctx, module_node):
        """is_stale returns True when sha1 differs even if mtime matches."""
        await persistence.persist_graph(ctx, [module_node], [])

        stored_mtime = module_node.domain_tags["mtime"]

        result = await persistence.is_stale(
            ctx, "mod/file.py", stored_mtime, "different_sha1_value"
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_is_stale_mtime_differs(self, persistence, ctx, module_node):
        """is_stale returns True when mtime has changed."""
        await persistence.persist_graph(ctx, [module_node], [])

        stored_sha1 = module_node.domain_tags["sha1"]

        result = await persistence.is_stale(
            ctx, "mod/file.py", 999.0, stored_sha1
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_per_tenant_isolation(self, persistence):
        """Each tenant gets its own .db file."""
        ctx_a = _make_ctx("tenant_a")
        ctx_b = _make_ctx("tenant_b")

        node_a = UniversalNode(
            node_id="na",
            kind=NodeKind.SYMBOL,
            title="module_a",
            source_uri="a.py",
            domain_tags={"symbol_type": "module", "sha1": "a" * 40, "mtime": 1.0},
        )
        node_b = UniversalNode(
            node_id="nb",
            kind=NodeKind.SYMBOL,
            title="module_b",
            source_uri="b.py",
            domain_tags={"symbol_type": "module", "sha1": "b" * 40, "mtime": 2.0},
        )

        await persistence.persist_graph(ctx_a, [node_a], [])
        await persistence.persist_graph(ctx_b, [node_b], [])

        db_a = persistence._db_path(ctx_a)
        db_b = persistence._db_path(ctx_b)

        assert db_a.name == "tenant_a.db"
        assert db_b.name == "tenant_b.db"
        assert db_a != db_b

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, persistence, ctx, module_node):
        """Database uses WAL journal mode."""
        await persistence.persist_graph(ctx, [module_node], [])

        db_path = persistence._db_path(ctx)
        conn = await aiosqlite.connect(str(db_path))
        try:
            async with conn.execute("PRAGMA journal_mode") as cur:
                row = await cur.fetchone()
                journal_mode = row[0]
        finally:
            await conn.close()

        assert journal_mode == "wal"

    @pytest.mark.asyncio
    async def test_persist_returns_correct_counts(
        self, persistence, ctx, module_node, canonical_node, sample_edge
    ):
        """persist_graph returns accurate node and edge counts."""
        result = await persistence.persist_graph(
            ctx,
            [module_node, canonical_node],
            [sample_edge],
        )
        assert result == {"nodes_persisted": 2, "edges_persisted": 1}
