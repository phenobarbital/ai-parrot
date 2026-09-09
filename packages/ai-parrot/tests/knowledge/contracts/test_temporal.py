"""Recoverable temporal publication tests (TASK-3039).

Live tests require an explicit ``GRAPHINDEX_PG_DSN`` and use a temporary
GraphIndex schema per tenant — this feature deliberately does not fall back
to ``parrot.conf.default_dsn``.
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional
from unittest.mock import MagicMock

import pytest
from parrot.knowledge.contracts.models import (
    ContractCard,
    ContractVersion,
    Party,
    TermSpec,
)
from parrot.knowledge.contracts.temporal import (
    NODE_ID_PREFIX,
    TEMPORAL_AGENT_ID,
    ContractTemporalPublisher,
    build_graph_update,
    contract_node_id,
    revision_run_id,
)
from parrot.knowledge.graphindex.schema import NodeKind

from .test_catalog_contract import InMemoryContractCatalog

PG_DSN: Optional[str] = os.environ.get("GRAPHINDEX_PG_DSN")
requires_pg = pytest.mark.skipif(not PG_DSN, reason="live GraphIndex tests require an explicit GRAPHINDEX_PG_DSN")

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def card(contract_id: str = "acme-msa", **overrides) -> ContractCard:
    """A synthetic card ready for temporal publication."""
    payload = {
        "contract_id": contract_id,
        "title": f"{contract_id} agreement",
        "summary": "Security obligations for ACME.",
        "contract_type": "msa",
        "status": "active",
        "source_uri": f"sharepoint://legal/{contract_id}.pdf",
        "source_sha256": f"sha-{contract_id}",
        "source_format": "pdf",
        "parties": [Party(party_id="party-acme", name="ACME Inc.", role="customer")],
        "term": TermSpec(effective_date=date(2026, 1, 1)),
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


def make_ctx(tenant_id: str = "troc") -> Any:
    ctx = MagicMock()
    ctx.tenant_id = tenant_id
    return ctx


class Receipt:
    def __init__(self, commit_id: str) -> None:
        self.commit_id = commit_id


class FakePersistence:
    """Records commits the way ``PostgresPersistence`` would."""

    def __init__(self) -> None:
        self.commits: list[dict[str, Any]] = []
        self.fail_next = 0
        self.swallow_receipt = False
        self.applied = 0

    async def apply_update(self, ctx, update):
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError("temporal plane unavailable")
        self.applied += 1
        commit_id = f"commit-{len(self.commits) + 1}"
        self.commits.append(
            {
                "commit_id": commit_id,
                "run_id": update.run_id,
                "agent_id": update.agent_id,
                "payload": {"nodes": [node.model_dump(mode="json") for node in update.nodes]},
            }
        )
        if self.swallow_receipt:
            raise RuntimeError("crashed after commit, before receipt")
        return Receipt(commit_id)

    async def list_commits(self, ctx, run_id=None, agent_id=None, limit=50):
        rows = [
            {k: v for k, v in commit.items() if k != "payload"}
            for commit in self.commits
            if run_id is None or commit["run_id"] == run_id
        ]
        return list(reversed(rows))[:limit]

    async def get_commit(self, ctx, commit_id):
        for commit in self.commits:
            if commit["commit_id"] == commit_id:
                return dict(commit)
        return None


@pytest.fixture()
async def publisher() -> ContractTemporalPublisher:
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card())
    return ContractTemporalPublisher(catalog=catalog, persistence=FakePersistence())


# --------------------------------------------------------------------------
# GraphUpdate mapping
# --------------------------------------------------------------------------


def test_node_identity_and_run_id_are_stable():
    assert contract_node_id("acme-msa") == "contracts:contract:acme-msa"
    assert NODE_ID_PREFIX == "contracts:contract:"
    assert revision_run_id("acme-msa", 2, 3) == "contracts:acme-msa:2:3"


def test_update_uses_existing_enum_values_and_embeds_history():
    version = ContractVersion(
        n=2,
        revision=3,
        valid_from=date(2026, 7, 1),
        valid_to=None,
        kind="amendment",
        source_sha256="sha-v2",
        card_snapshot=card(title="historical title").model_dump(mode="json", exclude={"versions"}),
        recorded_at=FROZEN_NOW,
    )
    update = build_graph_update(card(), version, tenant_id="troc", revision=3)

    node = update.nodes[0]
    assert node.kind is NodeKind.DOCUMENT, "no new NodeKind member is introduced"
    assert node.node_id == "contracts:contract:acme-msa"
    assert node.source_uri == "sharepoint://legal/acme-msa.pdf"
    assert update.run_id == "contracts:acme-msa:2:3"
    assert update.agent_id == TEMPORAL_AGENT_ID
    assert update.edges == [] and update.removed_nodes == []

    tags = node.domain_tags
    assert tags["contract_id"] == "acme-msa"
    assert tags["tenant_id"] == "troc"
    assert tags["version_n"] == 2
    assert tags["revision"] == 3
    assert tags["effective_from"] == "2026-07-01"
    assert tags["effective_to"] is None
    assert tags["source_sha256"] == "sha-v2"
    assert node.title == "historical title"
    assert tags["card_snapshot"]["title"] == "historical title", (
        "historical values live in versioned node content, not only in an " "external mutable reference"
    )
    assert tags["tombstone"] is False


def test_tombstone_updates_are_marked_and_never_delete_the_node():
    update = build_graph_update(card(), None, tenant_id="troc", tombstone=True)
    assert update.nodes[0].domain_tags["tombstone"] is True
    assert update.nodes[0].domain_tags["active"] is False
    assert update.removed_nodes == [], "recorded history must survive a retraction"


def test_no_global_revert_is_exposed():
    assert not hasattr(ContractTemporalPublisher, "revert_commit")
    assert not hasattr(ContractTemporalPublisher, "revert")


# --------------------------------------------------------------------------
# Draining, receipts and recovery
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_publishes_queued_revisions_and_records_receipts(publisher):
    report = await publisher.drain(make_ctx())

    assert report.claimed == 1
    assert report.published == ["acme-msa"]
    assert report.receipts["acme-msa"] == "commit-1"
    assert await publisher.catalog.pending_publications(target="temporal") == []
    assert publisher.persistence.applied == 1


@pytest.mark.asyncio
async def test_a_failure_keeps_the_row_queued_and_observable(publisher):
    publisher.persistence.fail_next = 1
    report = await publisher.drain(make_ctx())

    assert report.failed == ["acme-msa"]
    assert report.errors and "unavailable" in report.errors[0]
    pending = await publisher.catalog.pending_publications(target="temporal")
    assert len(pending) == 1
    assert pending[0].state == "failed"
    assert pending[0].last_error

    retried = await publisher.drain(make_ctx())
    assert retried.published == ["acme-msa"]


@pytest.mark.asyncio
async def test_an_unavailable_target_is_reported_not_swallowed(publisher):
    publisher.catalog.unavailable_targets.add("temporal")
    report = await publisher.drain(make_ctx())

    assert report.unavailable is True
    assert report.claimed == 0
    assert len(await publisher.catalog.pending_publications(target="temporal")) == 1


@pytest.mark.asyncio
async def test_crash_after_commit_recovers_without_a_duplicate_version(publisher):
    publisher.persistence.swallow_receipt = True
    crashed = await publisher.drain(make_ctx())
    assert crashed.failed == ["acme-msa"]
    assert publisher.persistence.applied == 1, "the commit really happened"

    publisher.persistence.swallow_receipt = False
    recovered = await publisher.drain(make_ctx())

    assert recovered.recovered == ["acme-msa"]
    assert recovered.published == []
    assert recovered.receipts["acme-msa"] == "commit-1"
    assert publisher.persistence.applied == 1, "no second logical version"


@pytest.mark.asyncio
async def test_a_mismatched_payload_is_refused_rather_than_accepted(publisher):
    persistence = publisher.persistence
    persistence.commits.append(
        {
            "commit_id": "foreign-commit",
            "run_id": revision_run_id("acme-msa", 1, 1),
            "agent_id": TEMPORAL_AGENT_ID,
            "payload": {
                "nodes": [
                    {
                        "node_id": contract_node_id("acme-msa"),
                        "domain_tags": {
                            "version_n": 1,
                            "revision": 1,
                            "source_sha256": "a-different-hash",
                        },
                    }
                ]
            },
        }
    )
    report = await publisher.drain(make_ctx())

    assert report.failed == ["acme-msa"]
    assert any("does not match" in error for error in report.errors)
    assert persistence.applied == 0, "a mismatched commit never authorises a publish"
    assert len(await publisher.catalog.pending_publications(target="temporal")) == 1


@pytest.mark.asyncio
async def test_successive_revisions_publish_distinct_runs(publisher):
    await publisher.drain(make_ctx())
    stored = await publisher.catalog.get("acme-msa")
    await publisher.catalog.upsert(stored.model_copy(update={"summary": "revised"}), expected_revision=1)

    report = await publisher.drain(make_ctx())
    assert report.published == ["acme-msa"]
    assert publisher.persistence.applied == 2
    run_ids = {commit["run_id"] for commit in publisher.persistence.commits}
    assert run_ids == {"contracts:acme-msa:1:1", "contracts:acme-msa:1:2"}


@pytest.mark.asyncio
async def test_retraction_publishes_a_tombstone_commit(publisher):
    await publisher.drain(make_ctx())
    await publisher.catalog.remove("acme-msa")

    commit_id = await publisher.publish_retraction(make_ctx(), "acme-msa")
    payload = (await publisher.persistence.get_commit(make_ctx(), commit_id))["payload"]
    assert payload["nodes"][0]["domain_tags"]["tombstone"] is True

    with pytest.raises(RuntimeError, match="unknown contract"):
        await publisher.publish_retraction(make_ctx(), "ghost")


# --------------------------------------------------------------------------
# Recorded time vs contractual time
# --------------------------------------------------------------------------


def test_contract_in_force_is_effective_time_only():
    versions = [
        ContractVersion(n=1, valid_from=date(2026, 1, 1), valid_to=date(2026, 7, 1)),
        ContractVersion(n=2, valid_from=date(2026, 7, 1)),
        ContractVersion(n=3),  # unknown effective date stays unresolved
    ]
    subject = card(versions=versions)

    assert ContractTemporalPublisher.contract_in_force(subject, date(2026, 3, 1)).n == 1
    assert ContractTemporalPublisher.contract_in_force(subject, date(2026, 7, 1)).n == 2
    assert ContractTemporalPublisher.contract_in_force(subject, date(2025, 1, 1)) is None


@pytest.mark.asyncio
async def test_recorded_time_adapters_are_scoped_to_the_contract_node(publisher):
    calls: list[tuple[str, Any]] = []

    class Recording(FakePersistence):
        async def as_of(self, ctx, when):
            calls.append(("as_of", when))
            return ([], [])

        async def history(self, ctx, concept_id):
            calls.append(("history", concept_id))
            return []

        async def diff(self, ctx, concept_id, t1, t2):
            calls.append(("diff", concept_id))
            return {}

    publisher.persistence = Recording()
    await publisher.graph_as_of(make_ctx(), FROZEN_NOW)
    await publisher.contract_history(make_ctx(), "acme-msa")
    await publisher.contract_diff(make_ctx(), "acme-msa", FROZEN_NOW, FROZEN_NOW)

    assert calls[0][0] == "as_of"
    assert calls[1] == ("history", "contracts:contract:acme-msa")
    assert calls[2] == ("diff", "contracts:contract:acme-msa")


# --------------------------------------------------------------------------
# Live GraphIndex Postgres
# --------------------------------------------------------------------------


@pytest.fixture()
async def live_plane() -> AsyncIterator[tuple[Any, str]]:
    """A PostgresPersistence bound to a temporary GraphIndex schema."""
    from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence

    schema = f"gi_contracts_{uuid.uuid4().hex[:8]}"
    persistence = PostgresPersistence(dsn=PG_DSN, schema=schema)
    try:
        yield persistence, schema
    finally:
        pool = await persistence._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await persistence.close()


@requires_pg
@pytest.mark.asyncio
async def test_live_successive_revisions_and_recorded_history(live_plane):
    persistence, _ = live_plane
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card())
    publisher = ContractTemporalPublisher(catalog=catalog, persistence=persistence)
    ctx = make_ctx()

    first = await publisher.drain(ctx)
    assert first.published == ["acme-msa"]

    stored = await catalog.get("acme-msa")
    await catalog.upsert(stored.model_copy(update={"title": "ACME MSA (restated)"}), expected_revision=1)
    second = await publisher.drain(ctx)
    assert second.published == ["acme-msa"]
    assert second.receipts["acme-msa"] != first.receipts["acme-msa"]

    history = await publisher.contract_history(ctx, "acme-msa")
    assert len(history) >= 2
    titles = [row.title for row in history]
    assert "ACME MSA (restated)" in titles


@requires_pg
@pytest.mark.asyncio
async def test_live_recorded_time_and_effective_time_answer_differently(live_plane):
    """An amendment effective in July, recorded in September."""
    persistence, _ = live_plane
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card())
    publisher = ContractTemporalPublisher(catalog=catalog, persistence=persistence)
    ctx = make_ctx()

    before = datetime.now(tz=timezone.utc) - timedelta(seconds=1)
    await publisher.drain(ctx)

    stored = await catalog.get("acme-msa")
    late_amendment = ContractVersion(
        n=2,
        valid_from=date(2026, 7, 1),
        kind="amendment",
        source_sha256="sha-v2",
        recorded_at=FROZEN_NOW,
    )
    await catalog.upsert(stored, expected_revision=1, version=late_amendment)
    await publisher.drain(ctx)
    after = datetime.now(tz=timezone.utc)

    # Recorded time: nothing existed before the first publication.
    nodes_before, _ = await publisher.graph_as_of(ctx, before)
    assert not [node for node in nodes_before if node.node_id.startswith(NODE_ID_PREFIX)]
    nodes_after, _ = await publisher.graph_as_of(ctx, after)
    assert [node for node in nodes_after if node.node_id.startswith(NODE_ID_PREFIX)]

    # Effective time: the amendment applies from July, months before it was
    # recorded in September.
    final = await catalog.get("acme-msa")
    in_force = ContractTemporalPublisher.contract_in_force(final, date(2026, 8, 1))
    assert in_force is not None and in_force.n == 2
    assert in_force.valid_from == date(2026, 7, 1)


@requires_pg
@pytest.mark.asyncio
async def test_live_crash_recovery_produces_no_duplicate_commit(live_plane):
    persistence, _ = live_plane
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    await catalog.upsert(card())
    publisher = ContractTemporalPublisher(catalog=catalog, persistence=persistence)
    ctx = make_ctx()

    # Commit for real, then lose the receipt (the crash window).
    update = build_graph_update(
        await catalog.get("acme-msa"),
        (await catalog.versions("acme-msa"))[0],
        tenant_id="troc",
        revision=1,
    )
    receipt = await persistence.apply_update(ctx, update)

    report = await publisher.drain(ctx)
    assert report.recovered == ["acme-msa"]
    assert report.receipts["acme-msa"] == receipt.commit_id

    commits = await persistence.list_commits(ctx, run_id=update.run_id, limit=10)
    assert len(commits) == 1, "recovery must not emit a second logical version"


@requires_pg
@pytest.mark.asyncio
async def test_live_identical_slugs_in_separate_schemas_cannot_leak():
    """Two tenants reuse the same contract slug in separate schemas."""
    from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence

    schema_a = f"gi_a_{uuid.uuid4().hex[:8]}"
    schema_b = f"gi_b_{uuid.uuid4().hex[:8]}"
    plane_a = PostgresPersistence(dsn=PG_DSN, schema=schema_a)
    plane_b = PostgresPersistence(dsn=PG_DSN, schema=schema_b)
    catalog_a = InMemoryContractCatalog(tenant_id="a", now=FROZEN_NOW)
    catalog_b = InMemoryContractCatalog(tenant_id="b", now=FROZEN_NOW)
    await catalog_a.upsert(card(title="tenant a agreement"))
    await catalog_b.upsert(card(title="tenant b agreement"))

    try:
        publisher_a = ContractTemporalPublisher(catalog=catalog_a, persistence=plane_a)
        publisher_b = ContractTemporalPublisher(catalog=catalog_b, persistence=plane_b)
        await publisher_a.drain(make_ctx("a"))
        await publisher_b.drain(make_ctx("b"))

        history_a = await publisher_a.contract_history(make_ctx("a"), "acme-msa")
        history_b = await publisher_b.contract_history(make_ctx("b"), "acme-msa")
        assert [row.title for row in history_a] == ["tenant a agreement"]
        assert [row.title for row in history_b] == ["tenant b agreement"]
    finally:
        for plane, schema in ((plane_a, schema_a), (plane_b, schema_b)):
            pool = await plane._ensure_pool()
            async with pool.acquire() as conn:
                await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            await plane.close()


@requires_pg
@pytest.mark.asyncio
async def test_process_death_after_graph_commit_is_recovered_without_duplicate(live_plane):
    """Kill a worker without unwinding its claim transaction or recording a receipt."""
    import asyncio
    import os
    import sys

    from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog

    persistence, graph_schema = live_plane
    schema = f"contracts_crash_{uuid.uuid4().hex[:8]}"
    catalog = PostgresContractCatalog(dsn=PG_DSN, tenant_id="troc", schema=schema)
    await catalog.setup()
    try:
        await catalog.upsert(card())
        from pathlib import Path

        source_root = Path(__file__).resolve().parents[3] / "src"
        env = dict(
            os.environ,
            CONTRACTS_CRASH_SCHEMA=schema,
            CONTRACTS_CRASH_GRAPH_SCHEMA=graph_schema,
            PYTHONPATH=str(source_root),
        )
        script = """
import asyncio, os
from types import SimpleNamespace
from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog
from parrot.knowledge.contracts.temporal import ContractTemporalPublisher
from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence
async def main():
    catalog = PostgresContractCatalog(dsn=os.environ['GRAPHINDEX_PG_DSN'], tenant_id='troc', schema=os.environ['CONTRACTS_CRASH_SCHEMA'])
    persistence = PostgresPersistence(dsn=os.environ['GRAPHINDEX_PG_DSN'], schema=os.environ['CONTRACTS_CRASH_GRAPH_SCHEMA'])
    original = persistence.apply_update
    async def crash(ctx, update):
        await original(ctx, update)
        os._exit(97)
    persistence.apply_update = crash
    await ContractTemporalPublisher(catalog=catalog, persistence=persistence).drain(SimpleNamespace(tenant_id='troc'))
asyncio.run(main())
"""
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", script, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await asyncio.wait_for(child.communicate(), timeout=30)
        assert child.returncode == 97, stderr.decode()
        pending = await catalog.pending_publications(target="temporal")
        assert len(pending) == 1 and pending[0].state == "pending"
        publisher = ContractTemporalPublisher(catalog=catalog, persistence=persistence)
        report = await publisher.drain(make_ctx())
        assert report.recovered == ["acme-msa"]
        assert len(await persistence.list_commits(make_ctx(), run_id=revision_run_id("acme-msa", 1, 1))) == 1
        assert await catalog.pending_publications(target="temporal") == []
    finally:
        async with await catalog._connection() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await catalog.close()


@requires_pg
@pytest.mark.asyncio
async def test_new_worker_reclaims_a_legacy_in_flight_claim(live_plane):
    from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog

    persistence, _ = live_plane
    schema = f"contracts_claim_{uuid.uuid4().hex[:8]}"
    catalog = PostgresContractCatalog(dsn=PG_DSN, tenant_id="troc", schema=schema)
    await catalog.setup()
    try:
        await catalog.upsert(card())
        assert len(await catalog.claim_publication(target="temporal")) == 1
        assert await catalog.pending_publications(target="temporal") == []
        report = await ContractTemporalPublisher(catalog=catalog, persistence=persistence).drain(make_ctx())
        assert report.published == ["acme-msa"]
        assert await catalog.pending_publications(target="temporal") == []
    finally:
        async with await catalog._connection() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await catalog.close()


@requires_pg
@pytest.mark.asyncio
@pytest.mark.parametrize("same_tenant", [True, False])
async def test_concurrent_publishers_do_not_starve_a_shared_two_connection_pool(same_tenant):
    import asyncio

    import asyncpg
    from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog
    from parrot.knowledge.graphindex.persist_postgres import PostgresPersistence

    pool = await asyncpg.create_pool(dsn=PG_DSN, min_size=2, max_size=2)
    schema = f"contracts_parallel_{uuid.uuid4().hex[:8]}"
    graph_schema = f"gi_parallel_{uuid.uuid4().hex[:8]}"
    first = PostgresContractCatalog(pool=pool, tenant_id="troc", schema=schema)
    second_schema = schema if same_tenant else f"contracts_other_{uuid.uuid4().hex[:8]}"
    second = PostgresContractCatalog(pool=pool, tenant_id="troc" if same_tenant else "other", schema=second_schema)
    persistence = PostgresPersistence(pool=pool, schema=graph_schema)
    entered, release = asyncio.Event(), asyncio.Event()
    task = None
    try:
        await first.setup()
        await second.setup()
        await persistence.list_commits(make_ctx())
        await first.upsert(card())
        if not same_tenant:
            await second.upsert(card())
        apply = persistence.apply_update

        async def paused(ctx, update):
            entered.set()
            await release.wait()
            return await apply(ctx, update)

        persistence.apply_update = paused
        task = asyncio.create_task(ContractTemporalPublisher(catalog=first, persistence=persistence).drain(make_ctx()))
        await asyncio.wait_for(entered.wait(), timeout=5)
        competing = await asyncio.wait_for(
            ContractTemporalPublisher(catalog=second, persistence=persistence).drain(make_ctx()), timeout=5
        )
        assert competing.claimed == 0
        release.set()
        report = await asyncio.wait_for(task, timeout=5)
        assert report.published == ["acme-msa"]
        assert len(await persistence.list_commits(make_ctx())) == 1
    finally:
        release.set()
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            await conn.execute(f"DROP SCHEMA IF EXISTS {graph_schema} CASCADE")
            if not same_tenant:
                await conn.execute(f"DROP SCHEMA IF EXISTS {second_schema} CASCADE")
        await pool.close()
