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

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from parrot.knowledge.ontology.graph_store import UpsertResult
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.schema import TenantContext
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot_tools.legal.boe.hashing import seal_hash
from parrot_tools.legal.boe.parser import parse_consolidated
from parrot_tools.legal.librarian.models import (
    DraftAnswer,
    DraftReadingNote,
    DraftSpan,
    PayloadEntry,
)

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
        self.last_traversal: tuple[str, dict[str, Any], dict[str, Any] | None] | None = None

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
        """Simulate the article_in_force / search_articles AQL semantics.

        Mirrors, in this TEST DOUBLE only, what a real ArangoDB engine
        would compute from the declarative query_templates (embedded-list
        selection: the FILTER clauses' inclusive lower bound / exclusive
        upper bound). Production code (``queries.py``) never performs
        this comparison in Python — see TASK-2375/TASK-2496.

        Branches on ``"legal_articulos_view"`` appearing in the AQL to
        simulate the ``search_articles`` pattern (TASK-2496) — the real
        engine's ``SEARCH`` matches at DOCUMENT level (any version's text
        can match); this fake reproduces that by checking the query
        substring against ANY version's text before resolving the
        in-force version for ``as_of`` (the token-containment guard in
        ``queries.py`` is what then drops a document-level match that
        landed only in a superseded wording — this fake does not
        pre-filter for that, by design).
        """
        bind_vars = bind_vars or {}
        self.last_traversal = (aql, bind_vars, collection_binds)
        if "legal_articulos_view" in aql:
            return self._search_articles_rows(bind_vars)

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

    def _search_articles_rows(self, bind_vars: dict[str, Any]) -> list[dict[str, Any]]:
        """Fake ``search_articles`` row production — see execute_traversal."""
        query = (bind_vars.get("query") or "").lower()
        as_of = bind_vars.get("as_of")
        limit = bind_vars.get("limit", 20)
        rows: list[dict[str, Any]] = []

        for doc in self._collections.get("articulo", {}).values():
            if not doc.get("_active", True):
                continue
            versions = doc.get("versions", [])
            if not any(query and query in (v.get("text") or "").lower() for v in versions):
                continue

            in_force = None
            for version in versions:
                lower = version["valid_from"]
                upper = version["valid_to"]
                if lower <= as_of and (upper is None or upper > as_of):
                    in_force = version
                    break
            if in_force is None:
                continue

            rows.append(
                {
                    "articulo_key": doc.get("articulo_key"),
                    "norma_ref": doc.get("norma_ref"),
                    "numero": doc.get("numero"),
                    "version": in_force,
                    "score": 1.0,
                }
            )
            if len(rows) >= limit:
                break
        return rows


@pytest.fixture
def fake_store() -> FakeGraphStore:
    return FakeGraphStore()


# ---------------------------------------------------------------------------
# TASK-2499: end-to-end librarian fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def seeded_store(boe_corpus: str, legal_tenant_ctx: TenantContext) -> FakeGraphStore:
    """A ``FakeGraphStore`` seeded by parsing the TASK-2372 fixture.

    Runs ``parse_consolidated`` (TASK-2492 sealed-hash path) over the
    checked-in BOE fixture and upserts the resulting norma/articulo
    records — every non-``supresion`` version carries a verifiable
    ``content_hash``, exactly like a real re-ingest.
    """
    parsed = parse_consolidated(boe_corpus)
    store = FakeGraphStore()
    if parsed.norma:
        await store.upsert_nodes(legal_tenant_ctx, "norma", [parsed.norma], key_field="boe_id")
    if parsed.articulos:
        await store.upsert_nodes(
            legal_tenant_ctx, "articulo", parsed.articulos, key_field="articulo_key"
        )
    return store


@pytest.fixture
def tampered_payload_entry() -> PayloadEntry:
    """A ``PayloadEntry`` whose text was mutated AFTER its hash was sealed.

    Simulates store tampering/drift since ingest — ``content_hash`` still
    carries the ORIGINAL text's sealed hash, but ``payload`` holds
    different text, so ``seal_hash(payload) != content_hash``
    (``SpanVerifier``'s defence-in-depth check, TASK-2495).
    """
    original_text = "El plazo sera de tres meses."
    sealed_hash = seal_hash(original_text)
    tampered_text = "El plazo sera de VEINTE meses."
    return PayloadEntry(
        payload_key="BOE-A-2015-10566:50:0",
        payload=tampered_text,
        content_hash=sealed_hash,
        title="Ley 40/2015 art. 50",
        url="https://www.boe.es/buscar/act.php?id=BOE-A-2015-10566",
        as_of=date(2019, 6, 1),
        version_n=0,
        articulo_key="BOE-A-2015-10566:50",
        basis="retrieval",
    )


class _CannedAgent:
    """Stands in for ``LegalLibrarianAgent`` — returns a fixed ``DraftAnswer``.

    ``ask`` raises if called: every e2e test query states its ``as_of``
    explicitly (e.g. "... a 2019-06-01") so ``extract_as_of`` never needs
    the LLM fallback — a call here would mean a test query regressed.
    """

    def __init__(self, draft: DraftAnswer) -> None:
        self._draft = draft

    async def draft(self, enumerated_dossier: str, query: str, as_of: date) -> DraftAnswer:
        return self._draft

    async def ask(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("as_of fallback must not be needed in deterministic e2e tests")


@dataclass
class CannedDrafts:
    """Four canned librarian agents for the fail-closed invariant e2e tests."""

    anchored: _CannedAgent
    fabricated: _CannedAgent
    mangled: _CannedAgent
    empty: _CannedAgent


# The real, in-force (as of 2019-06-01) wording of BOE-A-2015-10566:50
# version 0 (see boe_consolidated_sample.xml) — quoted VERBATIM so the
# "anchored" canned draft cites a real fixture substring.
ANCHORED_QUOTE = (
    "será necesario que el convenio se acompañe de una memoria "
    "justificativa donde se analice su necesidad y oportunidad"
)


@pytest.fixture
def canned_drafts() -> CannedDrafts:
    """Canned ``DraftAnswer``s exercising the fail-closed invariant end-to-end."""
    anchored = DraftAnswer(
        reading_order=["BOE-A-2015-10566:50:0"],
        conflicts=[],
        not_found=[],
        reading_guide=[
            DraftReadingNote(
                text="El convenio debe acompañarse de una memoria justificativa.",
                basis="llm",
                spans=[
                    DraftSpan(payload_key="BOE-A-2015-10566:50:0", quote=ANCHORED_QUOTE)
                ],
            )
        ],
    )
    fabricated = DraftAnswer(
        reading_order=["BOE-A-9999-1:art99:0"],
        conflicts=[],
        not_found=[],
        reading_guide=[
            DraftReadingNote(
                text="Dice algo inventado.",
                basis="llm",
                spans=[DraftSpan(payload_key="BOE-A-9999-1:art99:0", quote="inventado")],
            )
        ],
    )
    mangled = DraftAnswer(
        reading_order=["BOE-A-2015-10566:50:0"],
        conflicts=[],
        not_found=[],
        reading_guide=[
            DraftReadingNote(
                text="Texto distinto al original.",
                basis="llm",
                spans=[
                    DraftSpan(
                        payload_key="BOE-A-2015-10566:50:0",
                        quote="texto que no existe en absoluto en el payload",
                    )
                ],
            )
        ],
    )
    empty = DraftAnswer(reading_order=[], conflicts=[], reading_guide=[], not_found=[])
    return CannedDrafts(
        anchored=_CannedAgent(anchored),
        fabricated=_CannedAgent(fabricated),
        mangled=_CannedAgent(mangled),
        empty=_CannedAgent(empty),
    )


class FakeLog:
    """Records every appended ``SuppressionRecord`` — stands in for ``SuppressionLog``."""

    def __init__(self) -> None:
        self.records: list[Any] = []

    async def append(self, record: Any) -> None:
        self.records.append(record)


@pytest.fixture
def fake_log() -> FakeLog:
    return FakeLog()
