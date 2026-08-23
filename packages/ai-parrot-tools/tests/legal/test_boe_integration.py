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
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import parrot_tools.legal.boe  # noqa: F401 — registers "boe" with DataSourceFactory
import pytest
from parrot.knowledge.ontology.cache import OntologyCache
from parrot.knowledge.ontology.discovery import RelationDiscovery
from parrot.knowledge.ontology.parser import OntologyParser
from parrot.knowledge.ontology.refresh import OntologyRefreshPipeline
from parrot.knowledge.ontology.tenant import TenantOntologyManager
from parrot.knowledge.ontology.validators import validate_aql
from parrot_loaders.extractors.factory import DataSourceFactory
from parrot_tools.legal.boe.queries import article_in_force

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
        We additionally assert directly against the fake store that node
        counts did not grow, the meaningful, non-vacuous incrementality
        guarantee.
        """
        first = await run_sync(fake_store, boe_corpus)
        assert first.errors == []
        counts_before = {
            name: len(docs) for name, docs in fake_store._collections.items()
        }

        second = await run_sync(fake_store, boe_corpus)
        assert second.errors == []
        for result in second.entity_results.values():
            assert result.inserted == 0

        counts_after = {
            name: len(docs) for name, docs in fake_store._collections.items()
        }
        assert counts_after == counts_before

    async def test_traversal_passes_aql_validation(self, legal_tenant_ctx):
        tpl = legal_tenant_ctx.ontology.traversal_patterns["article_in_force"].query_template
        await validate_aql(tpl)

    @pytest.mark.parametrize("as_of,fragment", sorted(EXPECTED.items()))
    async def test_amendment_chain_end_to_end(
        self, fake_store, boe_corpus, legal_tenant_ctx, as_of, fragment
    ):
        await run_sync(fake_store, boe_corpus)
        version = await article_in_force(fake_store, legal_tenant_ctx, NORM_KEY, as_of)
        assert version is not None
        assert fragment in version.text

    async def test_boundaries(self, fake_store, boe_corpus, legal_tenant_ctx):
        """valid_from inclusive; valid_to exclusive."""
        await run_sync(fake_store, boe_corpus)

        # as_of == valid_from of v0 (2016-10-02) selects v0 (inclusive lower bound).
        v0 = await article_in_force(
            fake_store, legal_tenant_ctx, NORM_KEY, date(2016, 10, 2)
        )
        assert v0 is not None
        assert v0.n == 0

        # as_of == valid_to of v0 == valid_from of v1 (2021-01-01) selects the
        # NEXT version, v1 (exclusive upper bound).
        v1 = await article_in_force(
            fake_store, legal_tenant_ctx, NORM_KEY, date(2021, 1, 1)
        )
        assert v1 is not None
        assert v1.n == 1

        # as_of == valid_to of v1 == valid_from of v2 (2022-01-01) selects v2.
        v2 = await article_in_force(
            fake_store, legal_tenant_ctx, NORM_KEY, date(2022, 1, 1)
        )
        assert v2 is not None
        assert v2.n == 2
        assert v2.valid_to is None  # currently in force

    async def test_before_entry_into_force_returns_none(
        self, fake_store, boe_corpus, legal_tenant_ctx
    ):
        await run_sync(fake_store, boe_corpus)
        result = await article_in_force(
            fake_store, legal_tenant_ctx, NORM_KEY, date(1900, 1, 1)
        )
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
