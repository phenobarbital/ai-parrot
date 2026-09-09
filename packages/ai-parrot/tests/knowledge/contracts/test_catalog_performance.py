"""Catalog query performance on a 100-card fixture (TASK-3055).

Measures **warm** p95 latency for the operator-facing SQL operations —
search, verification queue and the two date windows — against a real
Postgres on a temporary schema. LLM and network-generation time is
excluded by construction: none of these paths touch a model.

Run it explicitly::

    GRAPHINDEX_PG_DSN=postgresql://... \\
      python -m pytest packages/ai-parrot/tests/knowledge/contracts/test_catalog_performance.py -q -s

Results are appended to ``artifacts/logs/task-3055.log`` and summarised in
``docs/knowledge/contracts-performance.md``.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

import pytest

from parrot.knowledge.contracts.catalog import ObligationWindow
from parrot.knowledge.contracts.catalog_postgres import PostgresContractCatalog
from parrot.knowledge.contracts.models import (
    ContractCard,
    FieldProvenance,
    Obligation,
    Party,
    Signatory,
    TermSpec,
)

from .conftest import FROZEN_NOW, TODAY, requires_pg

pytestmark = pytest.mark.asyncio

#: Fixture size mandated by spec AC14.
CARD_COUNT = 100

#: Warm samples per operation (after the warmup round).
SAMPLES = 30

#: Warmup iterations, excluded from the statistics.
WARMUP = 5

#: The acceptance threshold from spec AC14.
P95_BUDGET_SECONDS = 1.0

_STATUSES = ("active", "active", "active", "expired", "draft")
_TYPES = ("msa", "sow", "nda", "dpa", "amendment")
_STANDARDS = ("soc2", "iso27001", "gdpr", "hipaa", "pci_dss", None)


def synthetic_card(index: int) -> ContractCard:
    """Build card ``index`` of the deterministic 100-card fixture."""
    contract_id = f"perf-{index:03d}"
    party = f"party-{index % 17:02d}"
    expiration = TODAY + timedelta(days=(index * 7) % 400 - 30)
    standard = _STANDARDS[index % len(_STANDARDS)]
    return ContractCard(
        contract_id=contract_id,
        title=f"{contract_id} master services agreement with Counterparty {index % 17}",
        summary=(
            "Security, compliance and reporting obligations for counterparty "
            f"{index % 17}. Covers audits, insurance and data protection."
        ),
        toc_digest="1 Term (pp. 1-2)\n2 Compliance (pp. 3-4)\n3 Signatures (pp. 5-5)",
        topics=["security", "compliance", "reporting"],
        contract_type=_TYPES[index % len(_TYPES)],
        status=_STATUSES[index % len(_STATUSES)],
        source_uri=f"sharepoint://legal/{contract_id}.pdf",
        source_sha256=f"sha-{contract_id}",
        source_format="pdf",
        owner_employee_id=f"emp-{index % 9}",
        department="legal" if index % 2 else "finance",
        parties=[
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id=party, name=f"Counterparty {index % 17} Inc.", role="customer"),
        ],
        signatories=[
            Signatory(
                person_id=f"{contract_id}-person",
                name=f"Signer {index}",
                party_id=party,
                signed_on=TODAY - timedelta(days=index),
            )
        ],
        term=TermSpec(
            effective_date=TODAY - timedelta(days=365),
            expiration_date=expiration,
            notice_days=60,
            notice_deadline=expiration - timedelta(days=60),
            auto_renew=index % 3 == 0,
        ),
        obligations=[
            Obligation(
                obligation_id=f"{contract_id}-ob-{position:03d}",
                contract_id=contract_id,
                kind="compliance" if standard else "reporting",
                text=(
                    f"Vendor shall maintain {standard or 'quarterly reporting'} "
                    f"for the duration of contract {contract_id}."
                ),
                node_id=f"{position:04d}",
                page=position,
                standard_id=standard,
                due_date=TODAY + timedelta(days=(index + position) % 180),
            )
            for position in range(1, 4)
        ],
        field_provenance={
            "title": FieldProvenance(
                origin="llm",
                node_id="0001",
                quote=f"{contract_id} agreement",
                confidence=0.4 if index % 4 == 0 else 0.9,
            ),
            "term.expiration_date": FieldProvenance(origin="llm", node_id="0002"),
        },
        stale_fields=["governing_law"] if index % 5 == 0 else [],
        added_at=FROZEN_NOW,
        updated_at=FROZEN_NOW,
    )


async def measure(name: str, operation: Callable[[], Any]) -> dict[str, Any]:
    """Warm up, then time ``SAMPLES`` runs of one operation.

    Returns:
        A record with p50/p95/max in seconds and the row count observed.
    """
    for _ in range(WARMUP):
        await operation()

    timings: list[float] = []
    rows = 0
    for _ in range(SAMPLES):
        started = time.perf_counter()
        result = await operation()
        timings.append(time.perf_counter() - started)
        rows = len(result) if hasattr(result, "__len__") else rows

    ordered = sorted(timings)
    index = max(0, int(round(0.95 * len(ordered))) - 1)
    return {
        "operation": name,
        "samples": SAMPLES,
        "warmup": WARMUP,
        "rows": rows,
        "p50_s": round(statistics.median(ordered), 6),
        "p95_s": round(ordered[index], 6),
        "max_s": round(ordered[-1], 6),
    }


@requires_pg
async def test_catalog_operations_meet_the_warm_p95_budget(pg_pool, temp_schema):
    """Measure warm p95 for search, queue and both date windows."""
    catalog = PostgresContractCatalog(pool=pg_pool, tenant_id="troc", schema=temp_schema, now=lambda: FROZEN_NOW)
    await catalog.setup()

    load_started = time.perf_counter()
    for index in range(CARD_COUNT):
        await catalog.upsert(synthetic_card(index))
    load_seconds = time.perf_counter() - load_started
    assert len(await catalog.list_cards(active_only=False)) == CARD_COUNT

    until = TODAY + timedelta(days=90)
    measurements = [
        await measure("search", lambda: catalog.search("compliance obligations", top_k=8)),
        await measure("verification_queue", lambda: catalog.verification_queue(limit=50)),
        await measure(
            "expiring_within",
            lambda: catalog.expiring(until=until, key="expiration_date", since=TODAY),
        ),
        await measure(
            "notice_deadlines_within",
            lambda: catalog.expiring(until=until, key="notice_deadline", since=TODAY),
        ),
        await measure("list_cards", lambda: catalog.list_cards(status="active")),
        await measure(
            "obligations_due",
            lambda: catalog.obligations_due(ObligationWindow(until=until, limit=200)),
        ),
    ]

    environment = {
        "cards": CARD_COUNT,
        "obligations": CARD_COUNT * 3,
        "load_seconds": round(load_seconds, 3),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "processor": platform.processor() or platform.machine(),
        "cpu_count": os.cpu_count(),
        "postgres_dsn_host": (os.environ.get("GRAPHINDEX_PG_DSN") or "").split("@")[-1],
    }

    report = {"environment": environment, "measurements": measurements}
    # Anchored on the repo root so the log lands in artifacts/logs/
    # regardless of pytest's rootdir or the shell's working directory.
    repo_root = Path(__file__).resolve().parents[5]
    log = repo_root / "artifacts" / "logs" / "task-3055.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))  # noqa: T201 - benchmark output

    # Every measured operation must return real rows: a p95 measured over an
    # empty result set would prove nothing.
    for record in measurements:
        assert record["rows"] > 0, record

    breaches = [record for record in measurements if record["p95_s"] >= P95_BUDGET_SECONDS]
    assert not breaches, (
        "warm p95 budget exceeded; diagnose the query plan rather than relaxing " f"the threshold: {breaches}"
    )


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_the_fixture_is_deterministic_and_covers_the_query_mix():
    """The 100-card fixture is reproducible and exercises every filter."""
    first = [synthetic_card(index) for index in range(CARD_COUNT)]
    second = [synthetic_card(index) for index in range(CARD_COUNT)]
    assert [card.model_dump() for card in first] == [card.model_dump() for card in second]

    assert len({card.contract_id for card in first}) == CARD_COUNT
    assert {card.status for card in first} >= {"active", "expired", "draft"}
    assert {card.contract_type for card in first} >= {"msa", "sow", "nda"}
    assert any(card.stale_fields for card in first)
    assert any((provenance.confidence or 1.0) < 0.6 for card in first for provenance in card.field_provenance.values())
    assert sum(len(card.obligations) for card in first) == CARD_COUNT * 3
    assert any(obligation.standard_id == "soc2" for card in first for obligation in card.obligations)
    # Dates span both sides of today, so the windows are non-trivial.
    expirations = [card.term.expiration_date for card in first]
    assert min(expirations) < TODAY < max(expirations)
