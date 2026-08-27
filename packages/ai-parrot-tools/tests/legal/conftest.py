"""Shared fixtures for BOE integration tests (TASK-2376).

No live ArangoDB and no network access anywhere in this suite:

- ``FakeGraphStore`` is an in-memory ``OntologyGraphStore`` double that
  faithfully reproduces the upsert/diff/traversal contract
  ``OntologyRefreshPipeline`` and ``article_in_force`` depend on (see its
  docstring for the one documented deviation, around ``_key`` derivation).
- The BOE fetch is mocked at the ``aiohttp`` boundary using the checked-in
  TASK-2372 fixture (``fixtures/boe_consolidated_sample.xml``) — parsing
  runs entirely off that fixture, never the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from parrot.knowledge.ontology.graph_store import UpsertResult
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.ontology.tenant import TenantOntologyManager

FIXTURE_DIR = Path(__file__).parent / "fixtures"
BOE_FIXTURE_PATH = FIXTURE_DIR / "boe_consolidated_sample.xml"
BOE_FIXTURE_ID = "BOE-A-2015-10566"


@pytest.fixture
def boe_corpus() -> str:
    """The checked-in BOE consolidated XML fixture (TASK-2372) — no network."""
    return BOE_FIXTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def legal_tenant_ctx() -> TenantContext:
    """Resolve a TenantContext for the "legal" domain from package defaults.

    Points ``TenantOntologyManager`` explicitly at the package-bundled
    ``ontology/defaults`` directory (rather than the deployment's
    configured ``ONTOLOGY_DIR``) so this fixture is deterministic in any
    environment. Which directory a deployment configures ``ONTOLOGY_DIR``
    to (so it contains a ``domains/legal.ontology.yaml`` copy) is a
    deployment concern, not a test one.
    """
    defaults_dir = OntologyParser.get_defaults_dir()
    manager = TenantOntologyManager(ontology_dir=defaults_dir)
    return manager.resolve("legal_test_tenant", domain="legal")


class FakeGraphStore:
    """In-memory ``OntologyGraphStore`` double — no ArangoDB, no network.

    Reproduces the contract ``OntologyRefreshPipeline`` and
    ``article_in_force`` depend on: ``initialize_tenant``,
    ``get_all_nodes`` (``_active`` filtering), ``upsert_nodes``
    (inserted/updated/unchanged counting), ``soft_delete_nodes``,
    ``create_edges``, and ``execute_traversal`` (simulating the
    ``article_in_force`` AQL's version selection over ``versions[]``).

    Nodes are keyed by their declared ``key_field`` value (e.g.
    ``articulo_key``), matching this feature's spec §2 intent ("Entity
    keys follow the source's principle — identifiers are canonical keys
    ... articulo._key is {norma}:{art}") and TASK-2371's
    ``article_in_force`` AQL (``FILTER a._key == @articulo_key``). This
    used to be a *documented deviation* from the real
    ``OntologyGraphStore.upsert_nodes`` AQL, which did not copy
    ``key_field``'s value into ArangoDB's own auto-generated ``_key``
    attribute on INSERT (see this task's Completion Note for the original
    finding) — fixed in a follow-up commit
    (``INSERT MERGE(doc, { _key: doc[@key_field], _active: true })``), so
    this fake now models the real behavior, not just the documented
    intent.
    """

    def __init__(self) -> None:
        # collection -> {key_field value -> document}
        self._collections: dict[str, dict[str, dict[str, Any]]] = {}
        self.upsert_calls: list[tuple[str, int]] = []
        self.inserted_documents: list[tuple[str, dict[str, Any]]] = []

    async def initialize_tenant(self, ctx: TenantContext) -> None:
        return None

    async def insert_document(self, ctx: TenantContext, collection: str, doc: dict[str, Any]) -> None:
        """Insert one document — used by SuppressionLog.append (TASK-2495).

        Mirrors ``OntologyGraphStore.insert_document``'s contract
        (auto-key when absent) closely enough for append-only writer
        tests: records the call and stores the doc keyed by ``_key``.
        """
        store = self._collections.setdefault(collection, {})
        key = doc.get("_key") or f"auto:{len(store)}"
        store[key] = dict(doc)
        self.inserted_documents.append((collection, dict(doc)))

    async def get_all_nodes(self, ctx: TenantContext, collection: str) -> list[dict[str, Any]]:
        docs = self._collections.get(collection, {})
        return [dict(d) for d in docs.values() if d.get("_active", True)]

    async def upsert_nodes(
        self,
        ctx: TenantContext,
        collection: str,
        nodes: list[dict[str, Any]],
        key_field: str,
    ) -> UpsertResult:
        if not nodes:
            return UpsertResult()

        store = self._collections.setdefault(collection, {})
        inserted = updated = unchanged = 0

        for node in nodes:
            key = node.get(key_field)
            doc = dict(node)
            doc["_active"] = True
            doc["_key"] = key
            existing = store.get(key)
            if existing is None:
                inserted += 1
            else:
                changed = any(existing.get(field) != doc.get(field) for field in doc if not field.startswith("_"))
                if changed:
                    updated += 1
                else:
                    unchanged += 1
            store[key] = doc

        self.upsert_calls.append((collection, len(nodes)))
        return UpsertResult(inserted=inserted, updated=updated, unchanged=unchanged)

    async def soft_delete_nodes(self, ctx: TenantContext, collection: str, keys: list[str]) -> None:
        store = self._collections.get(collection, {})
        for key in keys:
            if key in store:
                store[key]["_active"] = False

    async def create_edges(self, ctx: TenantContext, edge_collection: str, edges: list[dict[str, Any]]) -> int:
        store = self._collections.setdefault(f"__edges__{edge_collection}", {})
        for edge in edges:
            store[(edge.get("_from"), edge.get("_to"))] = edge
        return len(edges)

    async def execute_traversal(
        self,
        ctx: TenantContext,
        aql: str,
        bind_vars: dict[str, Any] | None = None,
        collection_binds: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Simulate the article_in_force AQL's version-selection semantics.

        Mirrors, in this TEST DOUBLE only, what a real ArangoDB engine
        would compute from the declarative query_template (embedded-list
        selection: the FILTER clauses' inclusive lower bound / exclusive
        upper bound). Production code (``queries.py``) never performs
        this comparison in Python — see TASK-2375.
        """
        bind_vars = bind_vars or {}
        articulo_key = bind_vars.get("articulo_key")
        as_of = bind_vars.get("as_of")
        if articulo_key is None or as_of is None:
            return []

        collection_name = (collection_binds or {}).get("@articulo", "articulo")
        articulo = self._collections.get(collection_name, {}).get(articulo_key)
        if not articulo:
            return []

        for version in articulo.get("versions", []):
            lower = version["valid_from"]
            upper = version["valid_to"]
            if lower <= as_of and (upper is None or upper > as_of):
                return [version]
        return []


@pytest.fixture
def fake_store() -> FakeGraphStore:
    return FakeGraphStore()
