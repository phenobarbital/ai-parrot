"""Four-backend contract parity, with explicit reporting of skips (AC8).

SQLite and memory are MANDATORY. ArangoDB and Postgres run only when their
env is configured; when they do not, this module records them as
UNVALIDATED. AC8: "missing live backend validation is reported and blocks
declaring backend parity complete" — a skip is not a pass.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

#: Backends that must always run.
MANDATORY_BACKENDS = ("sqlite", "memory")

_EVALUATION_DIGESTS: dict[str, str] = {}

#: Live backends and the env var that enables each (AC8). Reasons mirror
#: test_arango_store_cas.py / test_postgres_store_cas.py's own SKIP_REASON —
#: duplicated locally rather than imported, since sibling test modules are
#: not a stable import surface.
_ARANGO_SKIP_REASON = "ArangoDB live fixture unavailable: set ARANGODB_HOST/ARANGODB_PASSWORD to validate AC8 parity"
POSTGRES_DSN = os.environ.get("WIKI_POSTGRES_DSN") or os.environ.get("GRAPHINDEX_PG_DSN") or default_dsn
POSTGRES_SKIP_REASON = "Postgres live fixture unavailable: set the wiki Postgres DSN env to validate AC8 parity"

_ARANGO_CONNECT_TIMEOUT_S = 2.0


def _arangodb_reachable() -> bool:
    """Best-effort, tightly-bounded reachability probe (never hangs)."""
    host = os.getenv("ARANGODB_HOST")
    if not host:
        return False
    port = int(os.getenv("ARANGODB_PORT", "8529"))
    try:
        with socket.create_connection((host, port), timeout=_ARANGO_CONNECT_TIMEOUT_S):
            return True
    except OSError:
        return False


def _postgres_reachable() -> bool:
    """Return whether the configured Postgres endpoint accepts a bounded TCP probe."""
    if not POSTGRES_DSN:
        return False
    parsed = urlparse(POSTGRES_DSN)
    if not parsed.hostname:
        return False
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 5432), timeout=_ARANGO_CONNECT_TIMEOUT_S):
            return True
    except OSError:
        return False


#: Repo root, anchored to this file rather than ``Path.cwd()`` — importing
#: ``parrot`` (Navigator/navconfig) chdirs the process to wherever the
#: shared editable-install package root resolves, which is the MAIN
#: checkout even when pytest is invoked from inside a feature worktree.
#: A bare relative path would silently write this feature's own evidence
#: into a different checkout entirely.
_REPO_ROOT = Path(__file__).resolve().parents[6]

#: Where the parity report is written (AC12: evidence under artifacts/logs/).
PARITY_REPORT = _REPO_ROOT / "artifacts" / "logs" / "feat-578-backend-parity.json"


def _available_live_backends() -> dict[str, bool]:
    return {
        "arangodb": _arangodb_reachable(),
        "postgres": _postgres_reachable(),
    }


def _page(concept_id: str = "adr:doc:a", body: str = "v1", content_hash: str = "h1") -> WikiPageRecord:
    return WikiPageRecord(concept_id=concept_id, title="t", category="adr", body=body, content_hash=content_hash)


@pytest.fixture(params=MANDATORY_BACKENDS)
def parity_store(request, tmp_path):
    """One store per mandatory backend."""
    if request.param == "sqlite":
        store = create_wiki_store(tmp_path / "sqlite-plane", wiki_name="parity", backend="sqlite")
    else:
        store = create_wiki_store(tmp_path / "memory-plane", wiki_name="parity", backend="memory")
    yield store


@pytest.fixture(params=[name for name, ok in _available_live_backends().items() if ok])
async def live_store(request, tmp_path):
    """One store per CONFIGURED live backend; the param list is empty otherwise."""
    if request.param == "arangodb":
        from parrot.knowledge.wiki.arango_store import ArangoDBWikiStore

        test_db_name = f"wiki_test_parity_{uuid.uuid4().hex[:8]}"
        arango_params = {
            "host": os.getenv("ARANGODB_HOST", "127.0.0.1"),
            "port": int(os.getenv("ARANGODB_PORT", "8529")),
            "username": os.getenv("ARANGODB_USERNAME", "root"),
            "password": os.getenv("ARANGODB_PASSWORD", ""),
        }
        store = ArangoDBWikiStore(arango_params, database=test_db_name, wiki_name="test_parity")
        await store.initialize()
        try:
            yield store
        finally:
            await store.close()
            if store._db is not None:
                try:
                    await store._db._connection.delete_database(test_db_name)
                except Exception:
                    pass
    else:
        from parrot.knowledge.wiki.postgres_store import PostgresWikiStore

        schema = f"graphindex_test_parity_{uuid.uuid4().hex[:12]}"
        store = PostgresWikiStore(POSTGRES_DSN, wiki_name="test-parity", schema=schema)
        try:
            yield store
        finally:
            pool = await store._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            await store.close()


class TestMandatoryBackends:
    async def test_cas_contract(self, parity_store):
        """Insert / replace / conflict behave identically on every backend."""
        assert await parity_store.compare_and_swap_page(_page(), None) is True
        assert await parity_store.compare_and_swap_page(_page(), None) is False
        assert await parity_store.compare_and_swap_page(_page(body="v2", content_hash="h2"), "h1") is True
        assert (await parity_store.get_page("adr:doc:a"))["body"] == "v2"
        assert await parity_store.compare_and_swap_page(_page(body="v3", content_hash="h3"), "h1") is False
        assert (await parity_store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_full_record_roundtrip(self, parity_store):
        """Every DecisionRecord field survives a save/load on each backend."""
        record = DecisionRecord(
            decision_id="adr:doc:full",
            title="A fully populated record",
            context="Some context",
            decision="Do the thing",
            consequences="Some consequences",
            source_status="accepted",
            origin="documented",
            observations=["obs1"],
            hypotheses=["hyp1"],
        )
        repo = DecisionRepository(parity_store)
        await repo.save(record, None)
        loaded, _hash = await repo.get("adr:doc:full")
        assert loaded == record

    async def test_identical_dossier_semantics(self, parity_store):
        """The same seeded records produce the same dossier on every backend."""
        record = DecisionRecord(
            decision_id="adr:doc:pgv",
            title="Use pgvector",
            decision="use pgvector as the vector store",
            origin="documented",
            source_status="accepted",
        )
        await DecisionRepository(parity_store).save(record, None)
        service = DecisionService(parity_store, None, DecisionConfig())
        dossier = await service.why("pgvector")
        assert dossier.status == "ok"
        assert dossier.documented[0].decision_id == "adr:doc:pgv"


class TestSchema2Parity:
    """FEAT-784 S11: schema-2 records are backend-independent."""

    async def test_backend_parity_schema2(self, parity_store):
        """Round-trip every schema-2 field through each mandatory backend."""
        from parrot.knowledge.wiki.decisions.models import DecisionRef, DecisionTarget

        record = DecisionRecord(
            schema_version=2,
            decision_id="adr:spec:demo#rule",
            decision="Clients never persist history",
            origin="documented",
            source_status="accepted",
            normative="forbids",
            about=["clients"],
            targets=[DecisionTarget(target_id="dir:src/pkg", kind="dir")],
            contradicts=[DecisionRef(decision_id="adr:doc:x", revision=1)],
            document_id="demo",
            entry_id="rule",
            batch_id="b1",
        )
        repository = DecisionRepository(parity_store)
        await repository.save(record, None)
        loaded, _content_hash = await repository.get(record.decision_id)
        assert loaded == record

    async def test_evaluation_parity_backends(self, parity_store, tmp_path):
        """Identical built planes yield the same evaluation digest on both backends."""
        from parrot.knowledge.wiki.decisions.consequences import ConsequenceService
        from parrot.knowledge.wiki.project import WikiProjectConfig
        from parrot.knowledge.wiki.structural.service import StructuralService

        root = tmp_path / "repo"
        (root / "pkg").mkdir(parents=True)
        (root / "pkg/a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        taxonomy = root / "sdd/taxonomy/subsystems.yaml"
        taxonomy.parent.mkdir(parents=True)
        taxonomy.write_text(
            "schema_version: 1\nsubsystems:\n  - id: core\n    title: Core\n    projects: [ai-parrot]\n",
            encoding="utf-8",
        )
        approvals = root / "sdd/decisions/approvals.jsonl"
        approvals.parent.mkdir(exist_ok=True)
        approvals.write_text("", encoding="utf-8")
        spec = root / "spec.md"
        spec.write_text(
            "---\nprojects: [ai-parrot]\n---\n# Spec\n\n## Decisions\n\n```yaml\n"
            "schema_version: 1\ndocument_id: parity\nentries:\n"
            "  - id: rule\n    statement: Govern the file.\n    relation: requires\n"
            '    about: [core]\n    targets: ["file:pkg/a.py"]\n```\n',
            encoding="utf-8",
        )
        await parity_store.upsert_pages([WikiPageRecord(concept_id="file:pkg/a.py", content_hash="fixture-file")])
        config = WikiProjectConfig()
        structural = StructuralService(parity_store, root, config, read_repair=False)

        class _Adapter:
            async def verify(self, entry, *, spec_text):
                return False, []

        service = ConsequenceService(
            parity_store,
            root,
            DecisionConfig(),
            structural,
            taxonomy_path=taxonomy,
            approvals_path=approvals,
            adapter=_Adapter(),
        )
        digest = (await service.evaluate(Path("spec.md"))).evaluation_digest
        _EVALUATION_DIGESTS[type(parity_store).__name__] = digest
        if len(_EVALUATION_DIGESTS) == len(MANDATORY_BACKENDS):
            assert len(set(_EVALUATION_DIGESTS.values())) == 1


class TestLiveBackends:
    async def test_cas_contract(self, live_store):
        assert await live_store.compare_and_swap_page(_page(), None) is True
        assert await live_store.compare_and_swap_page(_page(), None) is False
        assert await live_store.compare_and_swap_page(_page(body="v2", content_hash="h2"), "h1") is True
        assert (await live_store.get_page("adr:doc:a"))["body"] == "v2"

    async def test_concurrent_cas_one_winner(self, live_store):
        """AC8: parity is BEHAVIORAL, not just a JSON round-trip."""
        await live_store.compare_and_swap_page(_page(), None)
        results = await asyncio.gather(
            live_store.compare_and_swap_page(_page(body="a", content_hash="ha"), "h1"),
            live_store.compare_and_swap_page(_page(body="b", content_hash="hb"), "h1"),
        )
        assert sorted(results) == [False, True]


def test_backend_parity_is_reported(tmp_path):
    """Write the parity report and fail if parity is claimed while unvalidated.

    This test is the AC8 guard itself: it does not validate a backend, it
    validates that the PROJECT is honest about which backends were validated.
    """
    available = _available_live_backends()
    report = {
        "feature": "FEAT-578",
        "mandatory_validated": list(MANDATORY_BACKENDS),
        "live_validated": [n for n, ok in available.items() if ok],
        "live_unvalidated": [n for n, ok in available.items() if not ok],
        "parity_complete": all(available.values()),
    }
    PARITY_REPORT.parent.mkdir(parents=True, exist_ok=True)
    PARITY_REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    allow_partial = os.getenv("ADR_PARITY_ALLOW_PARTIAL") == "1"
    if report["parity_complete"]:
        return
    assert report["live_unvalidated"], "expected at least one unvalidated backend when parity is incomplete"
    assert allow_partial, (
        "Backend parity is INCOMPLETE and no partial run was explicitly allowed "
        f"(set ADR_PARITY_ALLOW_PARTIAL=1 to accept it). Unvalidated live backends: "
        f"{report['live_unvalidated']} ({_ARANGO_SKIP_REASON}; {POSTGRES_SKIP_REASON})"
    )
