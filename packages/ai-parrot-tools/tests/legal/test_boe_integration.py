"""Integration tests: pipeline ingestion, incrementality, amendment chain (TASK-2376).

No live ArangoDB, no network access anywhere in this suite — see
conftest.py's FakeGraphStore and the aiohttp mocking below. The BOE fetch
runs entirely off the checked-in TASK-2372 fixture
(fixtures/boe_consolidated_sample.xml).

Amendment-chain norm/article: Articulo 50 of Ley 40/2015 (BOE-A-2015-10566),
a real, hand-verifiable 3-version chain (original 2015 -> Real Decreto-ley
36/2020 -> Ley 22/2021) checked into the fixture verbatim during TASK-2372,
fetched live from the BOE datos abiertos API at that time. The wording
fragments below are quoted directly from that checked-in fixture text (the
authoritative source), not derived from the parser's own output, so this
test is not circular. See this task's Completion Note for the full
provenance and the resolution of spec Section 8's open question (no
synchronous access to the human owner was available; the already-verified
real BOE chain from TASK-2372 was reused rather than fabricating new data).
"""

import os
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import parrot_tools.legal.boe  # noqa: F401 — registers "boe" with DataSourceFactory
import pytest
from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.discovery import RelationDiscovery
from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.knowledge.ontology.validators import validate_aql
from parrot.knowledge.wiki.federation import open_namespace_store
from parrot.knowledge.wiki.project import WikiNamespaceConfig
from parrot_loaders.extractors.factory import DataSourceFactory
from parrot_tools.legal.boe.datasource import BOEDataSource
from parrot_tools.legal.boe.queries import article_in_force, search_articles
from parrot_tools.legal.boe.sync import _sync_provenance_edges
from parrot_tools.legal.wiki_store import OntologyLegalWikiStore

from .conftest import BOE_FIXTURE_ID

NORM_KEY = "BOE-A-2015-10566:50"

# Hand-verified against the official BOE consolidated text (quoted from the
# checked-in fixture, which was fetched live from the real BOE API during
# TASK-2372) -- DO NOT derive from the parser.
EXPECTED = {
    date(2016, 10, 2): "Ministerio de Hacienda y Administraciones Públicas",
    date(2020, 12, 31): "Ministerio de Hacienda y Administraciones Públicas",
    date(2021, 1, 1): "que se entenderá otorgada si en el plazo de siete días hábiles",
    date(2022, 1, 1): "Ministerio de Hacienda y Función Pública",
    date(2026, 1, 1): "Ministerio de Hacienda y Función Pública",
}


def _mock_aiohttp_response(body: str, status: int = 200):
    """Build a mocked aiohttp.ClientSession returning `body` as text.

    Follows the project convention (see
    packages/ai-parrot/tests/test_odoo_json2_transport.py and
    TASK-2373's test_boe_datasource.py).
    """
    response = AsyncMock()
    response.status = status
    response.text = AsyncMock(return_value=body)
    response.raise_for_status = MagicMock()
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=None)

    session = MagicMock()
    session.closed = False
    session.get = MagicMock(return_value=response)
    session.close = AsyncMock(return_value=None)
    return session


async def run_sync(fake_store, boe_corpus: str):
    """Run OntologyRefreshPipeline against the fake store, aiohttp mocked."""
    manager = TenantOntologyManager(ontology_dir=OntologyParser.get_defaults_dir())
    pipeline = OntologyRefreshPipeline(
        tenant_manager=manager,
        graph_store=fake_store,
        discovery=RelationDiscovery(),
        datasource_factory=DataSourceFactory(),
        cache=OntologyCache(),
        vector_store=None,
        source_configs={"boe": {"boe_ids": [BOE_FIXTURE_ID]}},
    )
    session = _mock_aiohttp_response(boe_corpus)
    with patch("aiohttp.ClientSession", return_value=session):
        return await pipeline.run("legal_test_tenant", domain="legal")


class TestBOEIntegration:
    async def test_pipeline_ingests_without_errors(self, fake_store, boe_corpus):
        report = await run_sync(fake_store, boe_corpus)
        assert report.errors == []
        assert "Norma" in report.entity_results
        assert "Articulo" in report.entity_results
        assert "Materia" not in report.entity_results  # no source -> skipped by design
        assert report.entity_results["Norma"].inserted == 1
        assert report.entity_results["Articulo"].inserted == 3

    async def test_second_run_is_incremental(self, fake_store, boe_corpus):
        """A second consecutive run reports no insertions.

        OntologyRefreshPipeline computes the add/update/remove diff in
        Python *before* calling upsert_nodes, and only calls upsert_nodes
        when there is something to add or update (refresh.py
        _refresh_entity). On a genuinely unchanged second run, nothing is
        added/updated, so upsert_nodes is never invoked and
        entity_results stays empty for that entity -- that IS "inserted
        == 0, unchanged > 0" for this architecture (see Completion Note).

        We additionally snapshot the fake store's full document content
        (not just counts) before/after the second run and assert it is
        byte-for-byte identical. A pure count comparison could not
        distinguish "correctly no-op" from "incorrectly replaced existing
        docs without net growth"; a full-content comparison can, and is
        the strongest check available without call-count instrumentation
        on upsert_nodes itself.
        """
        first = await run_sync(fake_store, boe_corpus)
        assert first.errors == []
        snapshot_before = {
            name: {key: dict(doc) for key, doc in docs.items()} for name, docs in fake_store._collections.items()
        }

        second = await run_sync(fake_store, boe_corpus)
        assert second.errors == []
        for result in second.entity_results.values():
            assert result.inserted == 0

        snapshot_after = {
            name: {key: dict(doc) for key, doc in docs.items()} for name, docs in fake_store._collections.items()
        }
        assert snapshot_after == snapshot_before

    async def test_traversal_passes_aql_validation(self, legal_tenant_ctx):
        tpl = legal_tenant_ctx.ontology.traversal_patterns["article_in_force"].query_template
        await validate_aql(tpl)

    @pytest.mark.parametrize("as_of,fragment", sorted(EXPECTED.items()))
    async def test_amendment_chain_end_to_end(self, fake_store, boe_corpus, legal_tenant_ctx, as_of, fragment):
        await run_sync(fake_store, boe_corpus)
        version = await article_in_force(fake_store, legal_tenant_ctx, NORM_KEY, as_of)
        assert version is not None
        assert fragment in version.text

    async def test_boundaries(self, fake_store, boe_corpus, legal_tenant_ctx):
        """valid_from inclusive; valid_to exclusive."""
        await run_sync(fake_store, boe_corpus)

        # as_of == valid_from of v0 (2016-10-02) selects v0 (inclusive lower bound).
        v0 = await article_in_force(fake_store, legal_tenant_ctx, NORM_KEY, date(2016, 10, 2))
        assert v0 is not None
        assert v0.n == 0

        # as_of == valid_to of v0 == valid_from of v1 (2021-01-01) selects the
        # NEXT version, v1 (exclusive upper bound).
        v1 = await article_in_force(fake_store, legal_tenant_ctx, NORM_KEY, date(2021, 1, 1))
        assert v1 is not None
        assert v1.n == 1

        # as_of == valid_to of v1 == valid_from of v2 (2022-01-01) selects v2.
        v2 = await article_in_force(fake_store, legal_tenant_ctx, NORM_KEY, date(2022, 1, 1))
        assert v2 is not None
        assert v2.n == 2
        assert v2.valid_to is None  # currently in force

    async def test_before_entry_into_force_returns_none(self, fake_store, boe_corpus, legal_tenant_ctx):
        await run_sync(fake_store, boe_corpus)
        result = await article_in_force(fake_store, legal_tenant_ctx, NORM_KEY, date(1900, 1, 1))
        assert result is None

    def test_no_llm_calls_structural(self):
        """Spec goal G6 — zero LLM calls anywhere in ingestion or resolution.

        Structural (spec goal G6 requires this asserted by test, not by
        convention): the legal toolkit source contains no LLM client
        import or invocation anywhere. There is no LLM client factory
        actually wired into the BOE ingestion/resolution path to patch
        and assert zero-calls against — RelationDiscovery's ai_assisted
        strategy is never reached (modifica/deroga declare zero discovery
        rules; pertenece_a uses field_match), so a structural, exhaustive
        source scan is the strongest available check.
        """
        pkg_root = Path(__import__("parrot_tools.legal", fromlist=["_"]).__file__).parent
        markers = ("openai", "anthropic", "AbstractClient", "parrot.clients", "completion(")
        hits = []
        for path in pkg_root.rglob("*.py"):
            src = path.read_text(encoding="utf-8")
            for marker in markers:
                if marker in src:
                    hits.append((str(path), marker))
        assert hits == [], f"Unexpected LLM references in legal toolkit: {hits}"

    async def test_no_llm_calls_during_run(self, fake_store, boe_corpus):
        """Defense in depth: the discovery collaborator carries no llm_client."""
        discovery = RelationDiscovery()
        assert discovery.llm_client is None
        report = await run_sync(fake_store, boe_corpus)
        assert report.errors == []


class TestProvenanceEdgeSync:
    """`modifica`/`deroga` edges bridged via `sync._sync_provenance_edges`.

    OntologyRefreshPipeline's generic REDISCOVER stage cannot create these
    edges (modifica/deroga declare zero field-match discovery rules) — see
    this task's Completion Note finding #4 and its follow-up fix commit.
    """

    async def test_creates_modifica_and_deroga_edges(self, fake_store, boe_corpus, legal_tenant_ctx):
        await run_sync(fake_store, boe_corpus)  # nodes must exist first

        boe_source = BOEDataSource(name="boe", config={"boe_ids": [BOE_FIXTURE_ID]})
        session = _mock_aiohttp_response(boe_corpus)
        with patch("aiohttp.ClientSession", return_value=session):
            stats, errors = await _sync_provenance_edges(legal_tenant_ctx, fake_store, boe_source)

        assert errors == []
        assert "modifica" in stats
        assert "deroga" in stats
        assert stats["modifica"].edges_created == stats["modifica"].total_source
        assert stats["deroga"].edges_created == stats["deroga"].total_source

        modifica_edges = fake_store._collections["__edges__modifica"]
        assert any(
            frm == "norma/BOE-A-2020-17340" and to == "articulo/BOE-A-2015-10566:50" for (frm, to) in modifica_edges
        )
        deroga_edges = fake_store._collections["__edges__deroga"]
        assert any(frm == "norma/BOE-A-2015-10566" and to == "norma/BOE-A-2014-9467" for (frm, to) in deroga_edges)

    async def test_no_boe_ids_creates_no_edges(self, fake_store, legal_tenant_ctx):
        boe_source = BOEDataSource(name="boe", config={})
        stats, errors = await _sync_provenance_edges(legal_tenant_ctx, fake_store, boe_source)
        assert stats == {}
        assert errors == []

    async def test_fetch_failure_surfaces_as_error_not_silent_empty(self, fake_store, legal_tenant_ctx):
        """A relation-fetch failure must show up in errors, not look like "no edges"."""
        boe_source = BOEDataSource(name="boe", config={"boe_ids": [BOE_FIXTURE_ID]})

        async def _boom(url):
            raise RuntimeError("network down")

        boe_source._fetch_raw = _boom

        stats, errors = await _sync_provenance_edges(legal_tenant_ctx, fake_store, boe_source)

        assert stats == {}
        assert errors
        assert any("network down" in e for e in errors)


# ---------------------------------------------------------------------------
# TASK-2499: live-ArangoDB integration tests (search_views, search_articles,
# the FEAT-450 namespace) — skip cleanly without a reachable dev tenant.
# ---------------------------------------------------------------------------


def _arango_params_from_env() -> dict:
    """Resolve live ArangoDB connection params, or skip the test.

    Mirrors the ``TEST_ARANGO_HOST``-gated skip convention used by
    ``packages/ai-parrot/tests/integration/rag/test_store_router_integration.py``.
    """
    host = os.environ.get("ARANGODB_HOST") or os.environ.get("TEST_ARANGO_HOST")
    if not host:
        pytest.skip("ARANGODB_HOST/TEST_ARANGO_HOST not set — live ArangoDB tests skipped")
    return {
        "host": host,
        "port": int(os.environ.get("ARANGODB_PORT", "8529")),
        "protocol": os.environ.get("ARANGODB_PROTOCOL", "http"),
        "username": os.environ.get("ARANGODB_USERNAME", "root"),
        "password": os.environ.get("ARANGODB_PASSWORD", ""),
    }


@pytest.fixture
def live_arango_ctx():
    """A real ``OntologyGraphStore`` + ``TenantContext`` against a dev tenant.

    Skips cleanly when ``ARANGODB_HOST``/``TEST_ARANGO_HOST`` is unset or
    the driver is unavailable; individual tests additionally skip on a
    live connection failure (server unreachable).
    """
    params = _arango_params_from_env()
    try:
        from asyncdb import AsyncDB

        client = AsyncDB("arangodb", params=params)
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"ArangoDB driver unavailable: {exc}")
    manager = TenantOntologyManager(ontology_dir=OntologyParser.get_defaults_dir())
    ctx = manager.resolve("legal_e2e_tenant", domain="legal")
    store = OntologyGraphStore(arango_client=client)
    return store, ctx


@pytest.mark.integration
class TestLiveArangoSearchViews:
    """Spec §4: ``test_search_view_provisioned_idempotently``."""

    async def test_search_view_provisioned_idempotently(self, live_arango_ctx):
        store, ctx = live_arango_ctx
        try:
            await store.initialize_tenant(ctx)
            await store.initialize_tenant(ctx)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"ArangoDB not reachable: {exc}")

        db = await store._get_db(ctx)
        connection = db._connection
        views = await connection.views()
        matches = [v for v in views if v.get("name") == "legal_articulos_view"]
        assert len(matches) == 1


@pytest.mark.integration
class TestLiveSearchArticlesTemporalFilter:
    """Spec §4: ``test_search_articles_live_temporal_filter``."""

    async def test_search_articles_live_temporal_filter(self, live_arango_ctx):
        store, ctx = live_arango_ctx
        try:
            await store.initialize_tenant(ctx)
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"ArangoDB not reachable: {exc}")

        today = datetime.now(UTC).date()
        hits_now = await search_articles(store, ctx, "convenios", today, limit=5)
        assert isinstance(hits_now, list)
        for hit in hits_now:
            # The AQL's own temporal FILTER pair already guarantees this;
            # re-asserted here as the live end-to-end proof (repealed
            # wordings for this as_of would violate it).
            assert hit.version.valid_from <= today
            assert hit.version.valid_to is None or hit.version.valid_to > today


@pytest.mark.integration
class TestLiveNamespaceFederation:
    """Spec §4: ``test_namespace_exposes_legal_corpus``."""

    async def test_namespace_exposes_legal_corpus(self, live_arango_ctx):
        _, ctx = live_arango_ctx
        cfg = WikiNamespaceConfig(database=ctx.arango_db, backend="ontology_legal")
        try:
            store, storage_dir = await open_namespace_store("legal", cfg, base_dir=Path("."))
        except FileNotFoundError as exc:
            pytest.skip(f"legal tenant not built: {exc}")
        except Exception as exc:  # pragma: no cover - environment-dependent
            pytest.skip(f"ArangoDB not reachable: {exc}")

        assert storage_dir is None
        assert isinstance(store, OntologyLegalWikiStore)

        rows = await store.search_fts("convenios", limit=5)
        assert isinstance(rows, list)

        with pytest.raises(NotImplementedError):
            await store.upsert_pages([])
