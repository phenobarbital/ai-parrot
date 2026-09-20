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

import pytest

from parrot.conf import default_dsn
from parrot.knowledge.wiki.decisions.models import DecisionConfig, DecisionRecord
from parrot.knowledge.wiki.decisions.repository import DecisionRepository
from parrot.knowledge.wiki.decisions.service import DecisionService
from parrot.knowledge.wiki.store import WikiPageRecord, create_wiki_store

#: Backends that must always run.
MANDATORY_BACKENDS = ("sqlite", "memory")

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
        "postgres": bool(POSTGRES_DSN),
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
