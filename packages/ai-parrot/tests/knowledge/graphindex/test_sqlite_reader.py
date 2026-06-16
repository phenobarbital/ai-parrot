"""Tests for parrot.knowledge.graphindex.sqlite_reader.SQLiteGraphReader (FEAT-240)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from parrot.knowledge.graphindex.persist_sqlite import SQLitePersistence
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    UniversalEdge,
    UniversalNode,
)
from parrot.knowledge.graphindex.sqlite_reader import SQLiteGraphReader


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_ctx(tenant_id: str = "t1") -> MagicMock:
    """Create a mock TenantContext with the given tenant_id."""
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


def _node(node_id, title, source_uri, symbol_type, parent_id=None, lineno=None, end_lineno=None, **extra):
    """Create a minimal UniversalNode for test fixtures."""
    tags = {"symbol_type": symbol_type, **extra}
    if lineno is not None:
        tags["lineno"] = lineno
        tags["end_lineno"] = end_lineno
    return UniversalNode(
        node_id=node_id,
        kind=NodeKind.SYMBOL,
        title=title,
        source_uri=source_uri,
        parent_id=parent_id,
        domain_tags=tags,
    )


def _edge(source_id, target_id, kind):
    """Create a minimal UniversalEdge for test fixtures."""
    return UniversalEdge(source_id=source_id, target_id=target_id, kind=kind)


@pytest.fixture
async def populated_db(tmp_path):
    """Build a small graph and return (db_path, ctx.tenant_id, tmp_path)."""
    ctx = _make_ctx("reader_test")
    persistence = SQLitePersistence(db_dir=tmp_path)

    # Graph:
    # module_node (mod/models.py)
    #   ├─ CONTAINS → class_node (ResPartner)
    #   │     ├─ DEFINES → canonical (res.partner)
    #   │     └─ CONTAINS → field_node (vat_verified)
    #   └─ CONTAINS → ext_class_node (ResPartnerExt, ext/partner.py)
    #         └─ EXTENDS → canonical (res.partner)
    #               ← field_node2 (loyalty, ext/partner.py)

    module_node = _node(
        "m1", "my_module", "mod/models.py", "module",
        sha1="a" * 40, mtime=100.0,
    )
    canonical = _node("c1", "res.partner", "odoo-model://res.partner", "odoo_model",
                      model_name="res.partner")
    class_node = _node(
        "n1", "ResPartner", "mod/models.py", "odoo_model_class",
        parent_id="m1", lineno=5, end_lineno=20,
    )
    field_node = _node(
        "f1", "vat_verified", "mod/models.py", "odoo_field",
        parent_id="n1", lineno=6, end_lineno=6,
        field_type="Boolean", string="VAT Verified",
    )
    field_node.summary = "VAT Verified"

    ext_module = _node(
        "m2", "ext_module", "ext/partner.py", "module",
        sha1="b" * 40, mtime=200.0,
    )
    ext_class = _node(
        "n2", "ResPartnerExt", "ext/partner.py", "odoo_model_class",
        parent_id="m2", lineno=3, end_lineno=10,
    )
    field_node2 = _node(
        "f2", "loyalty", "ext/partner.py", "odoo_field",
        parent_id="n2", lineno=4, end_lineno=4,
        field_type="Integer", string="Points",
    )
    func_node = _node(
        "fn1", "_compute_vat_status", "mod/models.py", "function",
        parent_id="n1", lineno=10, end_lineno=12,
    )

    nodes = [module_node, canonical, class_node, field_node, ext_module, ext_class, field_node2, func_node]
    edges = [
        _edge("m1", "n1", EdgeKind.CONTAINS),
        _edge("n1", "c1", EdgeKind.DEFINES),
        _edge("n1", "f1", EdgeKind.CONTAINS),
        _edge("n1", "fn1", EdgeKind.CONTAINS),
        _edge("m2", "n2", EdgeKind.CONTAINS),
        _edge("n2", "c1", EdgeKind.EXTENDS),
        _edge("n2", "f2", EdgeKind.CONTAINS),
    ]

    await persistence.persist_graph(ctx, nodes, edges)
    return tmp_path / f"{ctx.tenant_id}.db"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSQLiteGraphReader:
    """Tests for SQLiteGraphReader."""

    @pytest.mark.asyncio
    async def test_load_counts_nodes(self, populated_db):
        """After load(), list_models returns known models."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            models = reader.list_models()
            assert "res.partner" in models
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_load_idempotent(self, populated_db):
        """Calling load() twice does not raise or change state."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        await reader.load()  # should be a no-op
        try:
            assert len(reader.list_models()) > 0
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_list_models_sorted(self, populated_db):
        """list_models returns names in sorted order."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            models = reader.list_models()
            assert models == sorted(models)
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_get_node_returns_payload(self, populated_db):
        """get_node returns a dict with title and domain_tags."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            n = reader.get_node("c1")
            assert n is not None
            assert n["title"] == "res.partner"
            assert n["domain_tags"]["symbol_type"] == "odoo_model"
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_get_node_missing_returns_none(self, populated_db):
        """get_node for an unknown id returns None."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            assert reader.get_node("nonexistent") is None
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_children_of_class_includes_field(self, populated_db):
        """children() of a class node includes its fields (CONTAINS children)."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            kids = reader.children("n1")
            titles = {k["title"] for k in kids}
            assert "vat_verified" in titles
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_children_filtered_by_symbol_type(self, populated_db):
        """children() with symbol_type filter returns only matching nodes."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            fields = reader.children("n1", symbol_type="odoo_field")
            assert all(f["domain_tags"]["symbol_type"] == "odoo_field" for f in fields)
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_who_extends_returns_extender(self, populated_db):
        """who_extends lists classes with EXTENDS to the canonical model."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            result = reader.who_extends("res.partner")
            titles = {r["title"] for r in result}
            assert "ResPartnerExt" in titles
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_who_extends_has_module_key(self, populated_db):
        """who_extends results carry the 'module' key."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            result = reader.who_extends("res.partner")
            assert all("module" in r for r in result)
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_who_extends_include_definers(self, populated_db):
        """who_extends(include_definers=True) also includes DEFINES contributors."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            result = reader.who_extends("res.partner", include_definers=True)
            titles = {r["title"] for r in result}
            assert "ResPartner" in titles
            assert "ResPartnerExt" in titles
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_find_model_returns_aggregate(self, populated_db):
        """find_model returns aggregate with fields and methods."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            model = reader.find_model("res.partner")
            assert model is not None
            assert model["model_name"] == "res.partner"
            assert "fields" in model
            assert "methods" in model
            assert "contributors" in model
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_find_model_aggregates_from_all_contributors(self, populated_db):
        """find_model collects fields from both defining and extending classes."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            model = reader.find_model("res.partner")
            field_names = {f["title"] for f in model["fields"]}
            # vat_verified from ResPartner, loyalty from ResPartnerExt
            assert "vat_verified" in field_names
            assert "loyalty" in field_names
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_find_model_returns_none_for_unknown(self, populated_db):
        """find_model returns None for an unknown model name."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            assert reader.find_model("nonexistent.model") is None
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_search_symbols_returns_results(self, populated_db):
        """search_symbols returns matches for a query present in title."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            results = await reader.search_symbols("partner")
            assert len(results) > 0
            assert all("node_id" in r for r in results)
            assert all("score" in r for r in results)
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_search_symbols_no_match_returns_empty(self, populated_db):
        """search_symbols returns empty list for no match."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            results = await reader.search_symbols("zzznomatch_xxy")
            assert results == []
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_get_source_without_repo_root(self, populated_db):
        """get_source without repo_root falls back to summary."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            # f1 (vat_verified) has summary="VAT Verified" set in the fixture
            src = await reader.get_source("f1")
            assert src == "VAT Verified"
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_get_source_with_repo_root(self, populated_db, tmp_path):
        """get_source with repo_root reads the actual line span from disk."""
        # Write a source file that matches the fixture's source_uri
        source_dir = tmp_path / "mod"
        source_dir.mkdir()
        source_file = source_dir / "models.py"
        # lines: 1-12; class starts at line 5 (0-indexed: 4), ends at 20
        content_lines = ["# line 1\n"] * 4 + [
            "class ResPartner(models.Model):\n",  # line 5
            "    vat_verified = fields.Boolean(string='VAT Verified')\n",  # line 6
            "    # ...\n",
        ] + ["# more\n"] * 13
        source_file.write_text("".join(content_lines))

        reader = SQLiteGraphReader(populated_db, repo_root=tmp_path)
        await reader.load()
        try:
            src = await reader.get_source("n1")
            assert src is not None
            assert "ResPartner" in src
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_get_source_missing_node_returns_none(self, populated_db):
        """get_source for an unknown node_id returns None."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        try:
            result = await reader.get_source("no_such_node")
            assert result is None
        finally:
            await reader.close()

    @pytest.mark.asyncio
    async def test_lru_cache_respects_size(self, populated_db):
        """LRU body cache does not exceed body_cache_size entries."""
        reader = SQLiteGraphReader(populated_db, body_cache_size=2)
        await reader.load()
        try:
            # Access 3 different nodes that have summaries
            await reader.get_source("f1")  # vat_verified — has summary
            await reader.get_source("f2")  # loyalty — no summary
            await reader.get_source("n1")  # ResPartner class node
            assert len(reader._body_cache) <= 2
        finally:
            await reader.close()

    def test_not_loaded_list_models_raises(self):
        """list_models() before load() raises RuntimeError."""
        reader = SQLiteGraphReader(Path("/nonexistent.db"))
        with pytest.raises(RuntimeError, match="load"):
            reader.list_models()

    def test_not_loaded_children_raises(self):
        """children() before load() raises RuntimeError."""
        reader = SQLiteGraphReader(Path("/nonexistent.db"))
        with pytest.raises(RuntimeError, match="load"):
            reader.children("x")

    def test_not_loaded_who_extends_raises(self):
        """who_extends() before load() raises RuntimeError."""
        reader = SQLiteGraphReader(Path("/nonexistent.db"))
        with pytest.raises(RuntimeError, match="load"):
            reader.who_extends("res.partner")

    def test_not_loaded_find_model_raises(self):
        """find_model() before load() raises RuntimeError."""
        reader = SQLiteGraphReader(Path("/nonexistent.db"))
        with pytest.raises(RuntimeError, match="load"):
            reader.find_model("res.partner")

    @pytest.mark.asyncio
    async def test_module_of_synthetic_uri(self, populated_db):
        """_module_of returns empty string for synthetic odoo-model:// URIs."""
        assert SQLiteGraphReader._module_of("odoo-model://res.partner") == ""

    @pytest.mark.asyncio
    async def test_module_of_file_uri(self, populated_db):
        """_module_of extracts the top path segment from a file URI."""
        assert SQLiteGraphReader._module_of("sale/models/partner.py") == "sale"

    @pytest.mark.asyncio
    async def test_close_is_idempotent(self, populated_db):
        """close() can be called multiple times without error."""
        reader = SQLiteGraphReader(populated_db)
        await reader.load()
        await reader.close()
        await reader.close()  # should not raise
