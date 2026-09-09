"""Deterministic renewal and obligation report tests (TASK-3050)."""

from __future__ import annotations

import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from parrot.knowledge.contracts.evidence import EvidenceArchive
from parrot.knowledge.contracts.models import (
    FieldProvenance,
    Obligation,
    TermSpec,
)
from parrot_tools.contracts.flow import ContractsAnswerFlow, ContractsDraftProducer
from parrot_tools.contracts.jobs import (
    RECOGNISED_RECURRENCE,
    RENEWAL_BUCKETS,
    obligations_digest,
    renewals_report,
)
from parrot_tools.contracts.retrieval import (
    AuthorizationDenied,
    ContractRetrieval,
    RequestContext,
)
from parrot_tools.contracts.service import ContractsAnswerService
from parrot_tools.contracts.verifier import CitationVerifier

from .test_retrieval import TODAY, FakeCatalog, make_card

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
CLAUSE = "Vendor shall maintain SOC 2 Type II certification."


def principal(**overrides) -> RequestContext:
    """The configured service principal these jobs run as."""
    payload = {
        "user_id": "svc-contracts",
        "roles": ("contract_reader",),
        "tenant_id": "troc",
        "employee_id": "svc",
    }
    payload.update(overrides)
    return RequestContext(**payload)


def term(**overrides) -> TermSpec:
    return TermSpec(**overrides)


@pytest.fixture()
async def retrieval() -> ContractRetrieval:
    """A catalog spanning every renewal bucket plus edge cases."""
    catalog = FakeCatalog()
    # Bucket boundaries measured from 2026-09-09.
    await catalog.upsert(make_card("day-0", term=term(expiration_date=TODAY, notice_deadline=TODAY)))
    await catalog.upsert(
        make_card(
            "day-30",
            term=term(
                expiration_date=TODAY + timedelta(days=90),
                notice_deadline=TODAY + timedelta(days=30),
            ),
        )
    )
    await catalog.upsert(
        make_card(
            "day-31",
            term=term(
                expiration_date=TODAY + timedelta(days=91),
                notice_deadline=TODAY + timedelta(days=31),
            ),
        )
    )
    await catalog.upsert(
        make_card(
            "day-90",
            term=term(
                expiration_date=TODAY + timedelta(days=150),
                notice_deadline=TODAY + timedelta(days=90),
            ),
        )
    )
    await catalog.upsert(make_card("day-91", term=term(notice_deadline=TODAY + timedelta(days=91))))
    # No notice period: the expiration date is the fallback.
    await catalog.upsert(make_card("fallback", term=term(expiration_date=TODAY + timedelta(days=45))))
    # No dates at all: omitted entirely.
    await catalog.upsert(make_card("undated", term=term()))
    return ContractRetrieval(catalog=catalog, today=lambda: TODAY)


# --------------------------------------------------------------------------
# 1. Renewals: deterministic, inclusive, non-overlapping buckets
# --------------------------------------------------------------------------


def test_the_buckets_are_the_documented_windows():
    assert RENEWAL_BUCKETS == (("0-30", 0, 30), ("31-60", 31, 60), ("61-90", 61, 90))


@pytest.mark.asyncio
async def test_buckets_are_inclusive_non_overlapping_and_deterministic(retrieval):
    report = await renewals_report(retrieval=retrieval, principal=principal(), today=TODAY)

    by_label = {bucket.label: bucket for bucket in report.buckets}
    assert [bucket.label for bucket in report.buckets] == ["0-30", "31-60", "61-90"]

    first = {row["contract_id"] for row in by_label["0-30"].contracts}
    second = {row["contract_id"] for row in by_label["31-60"].contracts}
    third = {row["contract_id"] for row in by_label["61-90"].contracts}

    assert "day-0" in first and "day-30" in first, "both boundaries are inclusive"
    assert "day-31" in second
    assert "fallback" in second, "no notice period falls back to expiration"
    assert "day-90" in third
    assert not (first & second) and not (second & third), "buckets never overlap"
    assert "day-91" not in first | second | third, "outside the 90-day radar"
    assert "undated" not in first | second | third, "null dates are omitted"

    again = await renewals_report(retrieval=retrieval, principal=principal(), today=TODAY)
    assert again.model_dump() == report.model_dump()


@pytest.mark.asyncio
async def test_the_expiration_key_ignores_notice_deadlines(retrieval):
    report = await renewals_report(retrieval=retrieval, principal=principal(), today=TODAY, key="expiration_date")
    first = {row["contract_id"] for row in report.buckets[0].contracts}
    assert "day-0" in first
    assert "day-30" not in first, "its expiration is 90 days out"


@pytest.mark.asyncio
async def test_recipient_scope_excludes_unauthorized_contracts(retrieval):
    """A self-service principal only sees the contracts it owns."""
    await retrieval.catalog.upsert(
        make_card(
            "someone-elses",
            owner_employee_id="emp-9",
            term=term(notice_deadline=TODAY + timedelta(days=5)),
        )
    )
    scoped = RequestContext(
        user_id="carol@troc",
        roles=(),
        tenant_id="troc",
        employee_id="emp-1",
        employee_graph_id="employees/emp-1",
    )
    report = await renewals_report(retrieval=retrieval, principal=scoped, today=TODAY)
    covered = {row["contract_id"] for bucket in report.buckets for row in bucket.contracts}
    assert "someone-elses" not in covered
    assert "day-0" in covered, "its own contracts are still covered"


@pytest.mark.asyncio
async def test_an_unauthenticated_principal_is_refused(retrieval):
    with pytest.raises(AuthorizationDenied):
        await renewals_report(retrieval=retrieval, principal=RequestContext(), today=TODAY)


@pytest.mark.asyncio
async def test_the_renewals_report_needs_no_graph_and_no_model(retrieval):
    assert retrieval.graph_store is None
    report = await renewals_report(retrieval=retrieval, principal=principal(), today=TODAY)
    assert report.total > 0
    assert report.prose is None, "prose is opt-in"


# --------------------------------------------------------------------------
# 2. Obligations digest
# --------------------------------------------------------------------------


@pytest.fixture()
async def obligations_retrieval() -> ContractRetrieval:
    catalog = FakeCatalog()
    await catalog.upsert(
        make_card(
            "acme-msa",
            obligations=[
                Obligation(
                    obligation_id="ob-due",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="Vendor shall report quarterly.",
                    node_id="0003",
                    due_date=TODAY + timedelta(days=3),
                ),
                Obligation(
                    obligation_id="ob-later",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="Vendor shall report annually.",
                    node_id="0004",
                    due_date=TODAY + timedelta(days=60),
                ),
                Obligation(
                    obligation_id="ob-anchored",
                    contract_id="acme-msa",
                    kind="audit_right",
                    text="Vendor shall permit an annual audit.",
                    node_id="0005",
                    recurrence="annually",
                    provenance=FieldProvenance(
                        origin="manual",
                        verification="verified",
                        verified_by="bob@troc",
                        verified_at=FROZEN_NOW,
                    ),
                ),
                Obligation(
                    obligation_id="ob-unanchored",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="Vendor shall report periodically.",
                    node_id="0006",
                    recurrence="quarterly",
                ),
                Obligation(
                    obligation_id="ob-unknown",
                    contract_id="acme-msa",
                    kind="reporting",
                    text="Vendor shall report when convenient.",
                    node_id="0007",
                    recurrence="whenever the moon is full",
                ),
            ],
        )
    )
    return ContractRetrieval(catalog=catalog, today=lambda: TODAY)


@pytest.mark.asyncio
async def test_fixed_dates_recurrences_and_review_cases_are_separated(obligations_retrieval):
    digest = await obligations_digest(retrieval=obligations_retrieval, principal=principal(), today=TODAY, days=7)

    assert [row["obligation_id"] for row in digest.due] == ["ob-due"]
    assert [row["obligation_id"] for row in digest.recurring] == ["ob-anchored"]
    assert digest.recurring[0]["next_due"] == FROZEN_NOW.date().isoformat()

    review = {row["obligation_id"]: row["review_reason"] for row in digest.needs_review}
    assert "ob-unanchored" in review and "anchor" in review["ob-unanchored"]
    assert "ob-unknown" in review and "unrecognised" in review["ob-unknown"]
    assert "ob-later" not in {row["obligation_id"] for row in digest.due}


def test_the_recognised_recurrences_are_a_closed_set():
    assert "annually" in RECOGNISED_RECURRENCE
    assert "quarterly" in RECOGNISED_RECURRENCE
    assert "whenever the moon is full" not in RECOGNISED_RECURRENCE


@pytest.mark.asyncio
async def test_the_digest_window_and_kind_filters_are_deterministic(obligations_retrieval):
    wide = await obligations_digest(retrieval=obligations_retrieval, principal=principal(), today=TODAY, days=90)
    assert {row["obligation_id"] for row in wide.due} == {"ob-due", "ob-later"}

    audits = await obligations_digest(
        retrieval=obligations_retrieval,
        principal=principal(),
        today=TODAY,
        days=90,
        kinds=["audit_right"],
    )
    assert audits.due == []
    assert [row["obligation_id"] for row in audits.recurring] == ["ob-anchored"]

    assert (
        await obligations_digest(retrieval=obligations_retrieval, principal=principal(), today=TODAY, days=90)
    ).model_dump() == wide.model_dump()


@pytest.mark.asyncio
async def test_the_digest_respects_recipient_scope(obligations_retrieval):
    await obligations_retrieval.catalog.upsert(
        make_card(
            "hidden",
            owner_employee_id="emp-9",
            obligations=[
                Obligation(
                    obligation_id="hidden-ob",
                    contract_id="hidden",
                    kind="reporting",
                    text="Secret obligation.",
                    node_id="0001",
                    due_date=TODAY + timedelta(days=1),
                )
            ],
        )
    )
    scoped = RequestContext(
        user_id="carol@troc",
        roles=(),
        tenant_id="troc",
        employee_id="emp-1",
        employee_graph_id="employees/emp-1",
    )
    digest = await obligations_digest(retrieval=obligations_retrieval, principal=scoped, today=TODAY, days=30)
    assert "hidden-ob" not in {row["obligation_id"] for row in digest.due}


# --------------------------------------------------------------------------
# 3. Optional prose passes the shared gate; nothing is ever sent
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_optional_prose_goes_through_the_shared_gate(tmp_path, obligations_retrieval):
    catalog = obligations_retrieval.catalog
    card = await catalog.get("acme-msa")
    archive = EvidenceArchive(tmp_path / "evidence", tenant_id="troc")
    for version in card.versions:
        await archive.archive(
            archive.reference(
                "acme-msa",
                version_n=version.n,
                revision=version.revision,
                source_sha256=version.source_sha256,
            ),
            {"0003": "Vendor shall report quarterly."},
        )
    service = ContractsAnswerService(
        retrieval=obligations_retrieval,
        verifier=CitationVerifier(catalog=catalog, evidence=archive),
    )
    flow = ContractsAnswerFlow(service=service, producer=ContractsDraftProducer(adapter=None))

    digest = await obligations_digest(
        retrieval=obligations_retrieval,
        principal=principal(),
        today=TODAY,
        days=30,
        flow=flow,
        prose_question="What obligations does acme-msa carry?",
    )

    assert digest.prose is not None
    assert digest.prose["answer_kind"] in {"lookup", "not_found"}
    assert digest.prose["answer_id"], "the prose paragraph is audited like any answer"
    assert await catalog.get_answer(digest.prose["answer_id"]) is not None


@pytest.mark.asyncio
async def test_reports_never_deliver_anything(obligations_retrieval):
    digest = await obligations_digest(retrieval=obligations_retrieval, principal=principal(), today=TODAY)
    renewals = await renewals_report(retrieval=obligations_retrieval, principal=principal(), today=TODAY)
    # The jobs return data; the deploying agent decides what to do with it.
    assert hasattr(digest, "due") and hasattr(renewals, "buckets")
    assert digest.prose is None and renewals.prose is None


def test_neither_job_imports_a_scheduler_or_a_transport():
    source = (Path(__file__).resolve().parents[2] / "src" / "parrot_tools" / "contracts" / "jobs.py").read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("scheduler" in name for name in imported)
    assert not any(name.startswith(("aiohttp", "smtplib", "requests", "parrot.server")) for name in imported)
    decorators = {
        ast.unparse(decorator)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in node.decorator_list
    }
    assert not any("schedule" in decorator for decorator in decorators), decorators
