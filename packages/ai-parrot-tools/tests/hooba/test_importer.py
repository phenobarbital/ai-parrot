"""FEAT-602 TASK-3741 — BBVA importer."""

import itertools

import pytest

from parrot_tools.hooba.bank import load_manifest, parse_bbva_statement
from parrot_tools.hooba.importer import BbvaImporter
from parrot_tools.hooba.models import ContactMatch, DraftReceipt
from parrot_tools.hooba.rules import RuleEngine

from .fixtures.make_bbva_fixture import build_bbva_workbook


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    """Keep manifests isolated for each test."""
    monkeypatch.setenv("PARROT_STATE_DIR", str(tmp_path / "state"))


def _receipt(draft, identifier):
    """Return a draft receipt matching the submitted draft."""
    return DraftReceipt(
        kind="purchase_invoice",
        id=identifier,
        state="draft",
        correlation_key=draft.correlation_key,
    )


async def test_importer_plan_dry_run_idempotent(tmp_path):
    """Planning is pure, skips transfers, and links a qualifying contact."""
    statement = await parse_bbva_statement(build_bbva_workbook(tmp_path / "bbva.xlsx"))

    async def find_contact(concept):
        if concept == "MOVISTAR":
            return [ContactMatch(contact_id=10, legal_name="Movistar", score=0.90)]
        return []

    async def create_draft(draft):
        return _receipt(draft, 1)

    importer = BbvaImporter(RuleEngine.load(), find_contact, create_draft)
    first_planned, first_manifest, first_skipped = await importer.plan(statement, period="2026-09")
    second_planned, second_manifest, second_skipped = await importer.plan(statement, period="2026-09")

    assert [item.row.row_id for item in first_planned] == [item.row.row_id for item in second_planned]
    assert len(first_planned) == 4
    assert first_manifest.completed == second_manifest.completed == {}
    assert first_skipped == second_skipped == [{"row_id": statement.rows[-1].row_id, "reason": "rule.skip"}]
    movistar = next(item for item in first_planned if item.row.concept == "MOVISTAR")
    assert movistar.draft.contact_id == 10


async def test_importer_contact_threshold(tmp_path):
    """Contacts below the threshold remain unlinked while exact threshold matches link."""
    statement = await parse_bbva_statement(build_bbva_workbook(tmp_path / "bbva.xlsx"))

    async def below_threshold(concept):
        return [ContactMatch(contact_id=10, legal_name=concept, score=0.84)]

    async def at_threshold(concept):
        return [ContactMatch(contact_id=11, legal_name=concept, score=0.85)]

    async def create_draft(draft):
        return _receipt(draft, 1)

    below_planned, _, _ = await BbvaImporter(RuleEngine.load(), below_threshold, create_draft).plan(
        statement, period="2026-09"
    )
    at_planned, _, _ = await BbvaImporter(RuleEngine.load(), at_threshold, create_draft).plan(statement, period="2026-09")

    assert all(item.draft.contact_id is None for item in below_planned)
    assert all("contact: none (no match ≥ 0.85)" in item.draft.notes for item in below_planned)
    assert all(item.draft.contact_id == 11 for item in at_planned)


async def test_importer_apply_resumes_after_failure(tmp_path):
    """Only receipt-confirmed rows are checkpointed and retried after a failure."""
    statement = await parse_bbva_statement(build_bbva_workbook(tmp_path / "bbva.xlsx"))
    calls = itertools.count(1)

    async def find_contact(concept):
        return []

    async def create_draft(draft):
        call = next(calls)
        if call == 3:
            raise RuntimeError("draft creation failed")
        return _receipt(draft, call)

    importer = BbvaImporter(RuleEngine.load(), find_contact, create_draft)
    planned, manifest, _ = await importer.plan(statement, period="2026-09")
    with pytest.raises(RuntimeError, match="draft creation failed"):
        await importer.apply(planned, manifest)

    persisted = load_manifest(statement.digest)
    assert persisted is not None
    assert len(persisted.completed) == 2

    resumed, resumed_manifest, _ = await importer.plan(statement, period="2026-09")
    receipts = await importer.apply(resumed, resumed_manifest)

    assert len(resumed) == len(receipts) == 2
    assert len(resumed_manifest.completed) == 4
    assert next(calls) == 6


async def test_drafts_carry_row_id_as_correlation_key(tmp_path):
    """Every planned draft uses its bank-row identifier as its idempotency key."""
    statement = await parse_bbva_statement(build_bbva_workbook(tmp_path / "bbva.xlsx"))

    async def find_contact(concept):
        return []

    async def create_draft(draft):
        return _receipt(draft, 1)

    planned, _, _ = await BbvaImporter(RuleEngine.load(), find_contact, create_draft).plan(statement, period="2026-09")

    assert all(item.draft.correlation_key == item.row.row_id for item in planned)
