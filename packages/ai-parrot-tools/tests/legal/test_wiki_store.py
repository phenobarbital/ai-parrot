"""Unit tests for OntologyLegalWikiStore (FEAT-449 TASK-2498)."""

import pytest
from parrot_tools.legal.wiki_store import OntologyLegalWikiStore

STUB_KEYS = {
    "concept_id",
    "node_id",
    "title",
    "category",
    "summary",
    "source_id",
    "token_count",
    "score",
}


def _version(n, text, valid_from, valid_to):
    return {
        "n": n,
        "text": text,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "modified_by": None,
        "kind": "redaccion",
        "source": "boe_consolidada",
        "derived": False,
        "content_hash": "deadbeef",
        "hash_norm_version": 1,
    }


class FakeLegalStore:
    """Minimal OntologyGraphStore double tailored to the adapter's own AQL shapes."""

    def __init__(self):
        self.articulos: dict[str, dict] = {}
        self.normas: dict[str, dict] = {}
        self.edges: dict[str, list[dict]] = {"modifica": [], "deroga": [], "pertenece_a": []}

    def seed_articulo(self, key, norma_ref, numero, versions):
        self.articulos[key] = {"norma_ref": norma_ref, "numero": numero, "versions": versions}

    @staticmethod
    def _in_force(versions, as_of):
        for v in versions:
            if v["valid_from"] <= as_of and (v["valid_to"] is None or v["valid_to"] > as_of):
                return v
        return None

    async def execute_traversal(self, ctx, aql, bind_vars=None, collection_binds=None):
        bind_vars = bind_vars or {}
        collection_binds = collection_binds or {}

        if "legal_articulos_view" in aql:
            return self._search_rows(bind_vars)

        if "@articulo" in collection_binds:
            if "RETURN a.versions" in aql:
                return [doc["versions"] for doc in self.articulos.values()]
            if "key" in bind_vars:
                return self._get_page_rows(bind_vars)
            return self._list_pages_rows(bind_vars)

        if "@norma" in collection_binds:
            if "RETURN 1" in aql:
                return [1] * len(self.normas)
            return self._list_norma_rows(bind_vars)

        if "@edges" in collection_binds:
            return self._edge_rows(aql, bind_vars, collection_binds["@edges"])

        return []

    def _search_rows(self, bind_vars):
        query = (bind_vars.get("query") or "").lower()
        as_of = bind_vars.get("as_of")
        limit = bind_vars.get("limit", 20)
        rows = []
        for key, doc in self.articulos.items():
            versions = doc["versions"]
            if not any(query and query in (v.get("text") or "").lower() for v in versions):
                continue
            in_force = self._in_force(versions, as_of)
            if in_force is None:
                continue
            rows.append(
                {
                    "articulo_key": key,
                    "norma_ref": doc["norma_ref"],
                    "numero": doc["numero"],
                    "version": in_force,
                    "score": 1.0,
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _get_page_rows(self, bind_vars):
        doc = self.articulos.get(bind_vars["key"])
        if not doc:
            return []
        v = self._in_force(doc["versions"], bind_vars["as_of"])
        if v is None:
            return []
        return [{"norma_ref": doc["norma_ref"], "numero": doc["numero"], "version": v}]

    def _list_pages_rows(self, bind_vars):
        as_of = bind_vars["as_of"]
        limit = bind_vars["limit"]
        rows = []
        for key, doc in self.articulos.items():
            v = self._in_force(doc["versions"], as_of)
            if v is None:
                continue
            rows.append({"articulo_key": key, "norma_ref": doc["norma_ref"], "numero": doc["numero"], "version": v})
            if len(rows) >= limit:
                break
        return rows

    def _list_norma_rows(self, bind_vars):
        limit = bind_vars["limit"]
        rows = []
        for boe_id, doc in self.normas.items():
            rows.append({"boe_id": boe_id, "titulo": doc.get("titulo")})
            if len(rows) >= limit:
                break
        return rows

    def _edge_rows(self, aql, bind_vars, collection):
        edges = self.edges.get(collection, [])
        if "rel" in bind_vars:
            return [{"src": e["_from"], "dst": e["_to"], "rel": collection} for e in edges]
        seed = bind_vars.get("seed")
        if "e._from == @seed" in aql:
            return [{"target": e["_to"]} for e in edges if e["_from"] == seed]
        if "e._to == @seed" in aql:
            return [{"target": e["_from"]} for e in edges if e["_to"] == seed]
        return []


@pytest.fixture
def fake_legal_store():
    fake = FakeLegalStore()
    fake.seed_articulo(
        "BOE-A-2015-10566:50",
        "BOE-A-2015-10566",
        "50",
        [_version(0, "El plazo sera de tres meses.", "2010-01-01", None)],
    )
    fake.normas["BOE-A-2015-10566"] = {"titulo": "Ley de Ejemplo"}
    fake.edges["modifica"].append({"_from": "norma/BOE-A-2020-1", "_to": "articulo/BOE-A-2015-10566:50"})
    return fake


@pytest.fixture
def fake_legal_wiki_store(fake_legal_store, legal_tenant_ctx):
    return OntologyLegalWikiStore(
        arango_params={},
        database="test_legal_db",
        wiki_name="legal",
        store=fake_legal_store,
        ctx=legal_tenant_ctx,
    )


class TestReadOnly:
    async def test_write_methods_raise(self, fake_legal_wiki_store):
        with pytest.raises(NotImplementedError):
            await fake_legal_wiki_store.upsert_pages([])
        with pytest.raises(NotImplementedError):
            await fake_legal_wiki_store.add_edges([])
        with pytest.raises(NotImplementedError):
            await fake_legal_wiki_store.replace_source_slice("x", [])
        with pytest.raises(NotImplementedError):
            await fake_legal_wiki_store.delete_page("x")
        with pytest.raises(NotImplementedError):
            await fake_legal_wiki_store.upsert_embedding("x", [0.1])

    async def test_search_vector_returns_empty_never_raises(self, fake_legal_wiki_store):
        assert await fake_legal_wiki_store.search_vector([0.1] * 8, limit=5) == []


class TestSearchFts:
    async def test_search_fts_stub_shape(self, fake_legal_wiki_store):
        rows = await fake_legal_wiki_store.search_fts("tres", category=None, limit=5)
        assert rows
        assert set(rows[0]) == STUB_KEYS

    async def test_search_fts_non_articulo_category_returns_empty(self, fake_legal_wiki_store):
        assert await fake_legal_wiki_store.search_fts("tres", category="norma", limit=5) == []


class TestGetPage:
    async def test_get_page_returns_body_and_title(self, fake_legal_wiki_store):
        page = await fake_legal_wiki_store.get_page("BOE-A-2015-10566:50")
        assert page["concept_id"] == "BOE-A-2015-10566:50"
        assert page["title"] == "BOE-A-2015-10566 art. 50"
        assert page["category"] == "articulo"
        assert "tres meses" in page["body"]

    async def test_get_page_excludes_body_when_requested(self, fake_legal_wiki_store):
        page = await fake_legal_wiki_store.get_page("BOE-A-2015-10566:50", include_body=False)
        assert "body" not in page

    async def test_get_page_missing_returns_none(self, fake_legal_wiki_store):
        assert await fake_legal_wiki_store.get_page("nope:0") is None


class TestListPages:
    async def test_list_pages_includes_both_categories_by_default(self, fake_legal_wiki_store):
        rows = await fake_legal_wiki_store.list_pages()
        categories = {r["category"] for r in rows}
        assert categories == {"articulo", "norma"}

    async def test_list_pages_filters_by_category(self, fake_legal_wiki_store):
        rows = await fake_legal_wiki_store.list_pages(category="norma")
        assert all(r["category"] == "norma" for r in rows)


class TestNeighbors:
    async def test_neighbors_finds_incoming_edge(self, fake_legal_wiki_store):
        rows = await fake_legal_wiki_store.neighbors("articulo/BOE-A-2015-10566:50", rel="modifica", direction="in")
        assert rows == [{"concept_id": "norma/BOE-A-2020-1", "rel": "modifica", "direction": "in"}]


class TestLintApi:
    async def test_lint_methods_return_empty(self, fake_legal_wiki_store):
        assert await fake_legal_wiki_store.orphan_sources() == []
        assert await fake_legal_wiki_store.broken_edges() == []
        assert await fake_legal_wiki_store.missing_bodies() == []


class TestStats:
    async def test_stats_counts(self, fake_legal_wiki_store):
        stats = await fake_legal_wiki_store.stats()
        assert stats["normas"] == 1
        assert stats["articulos"] == 1
        assert stats["total_versions"] == 1
        assert stats["in_force_versions"] == 1


class TestFactory:
    async def test_factory_raises_when_database_unbuilt(self, monkeypatch):
        """The store produced by factory() raises FileNotFoundError on first
        real use when the target database/collection doesn't exist —
        factory() itself stays synchronous and non-connecting (mirrors
        ArangoDBWikiStore); verification happens lazily in initialize().
        """

        class FakeProbe:
            async def connection(self):
                return None

            async def list_databases(self):
                return []  # target database absent

            async def close(self):
                return None

        import sys
        import types

        import parrot_tools.legal.wiki_store as wiki_store_module

        fake_module = types.ModuleType("asyncdb")
        fake_module.AsyncDB = lambda *args, **kwargs: FakeProbe()
        monkeypatch.setitem(sys.modules, "asyncdb", fake_module)

        store = wiki_store_module.OntologyLegalWikiStore.factory(
            wiki_name="legal", database="does_not_exist", arango_params={}
        )
        with pytest.raises(FileNotFoundError):
            await store.initialize()
