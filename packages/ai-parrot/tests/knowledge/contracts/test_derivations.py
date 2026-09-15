"""Deterministic assembly, status and parent-resolution tests (TASK-3031)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from parrot.knowledge.contracts.carding import (
    PARENT_SIMILARITY_THRESHOLD,
    CardingDraft,
    assemble_card,
    derive_next_renewal_date,
    derive_notice_deadline,
    derive_status,
    normalize_party_name,
    resolve_parent,
    similarity,
)
from parrot.knowledge.contracts.models import (
    ContractCard,
    ContractHeaderDraft,
    Evidence,
    Extracted,
    ObligationClauseDraft,
    ObligationsDraft,
    Party,
    PartyDraft,
    SignatoryDraft,
    TermSpec,
    TocEntry,
)

TODAY = date(2026, 9, 9)
FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def evidence(node_id: str = "0001", quote: str = "quoted text") -> Evidence:
    """A substantiating evidence stub."""
    return Evidence(node_id=node_id, quote=quote)


def header(**overrides) -> ContractHeaderDraft:
    """An evidenced header draft with sensible defaults."""
    payload = {
        "title": Extracted[str](value="ACME Master Services Agreement", evidence=evidence(), confidence=0.9),
        "contract_type": Extracted[str](value="msa", evidence=evidence(), confidence=0.9),
        "parties": [
            PartyDraft(name="Troc Global Inc.", role="us", is_us=True, evidence=evidence(), confidence=0.9),
            PartyDraft(name="ACME, Inc.", role="customer", evidence=evidence(), confidence=0.9),
        ],
        "signatories": [
            SignatoryDraft(
                name="Jane Doe",
                party_name="ACME Incorporated",
                title="CFO",
                signed_on=date(2025, 12, 20),
                evidence=evidence("0007"),
                confidence=0.8,
            )
        ],
        "summary": "Master services agreement.",
        "topics": ["security"],
    }
    payload.update(overrides)
    return ContractHeaderDraft(**payload)


def draft(**overrides) -> CardingDraft:
    """A carding draft ready for assembly."""
    payload = {"header": header(), "origin": "llm", "llm_calls": 2}
    payload.update(overrides)
    return CardingDraft(**payload)


def assemble(carding: CardingDraft | None = None, **overrides) -> ContractCard:
    """Assemble a card with test defaults."""
    kwargs = {
        "contract_id": "acme-msa",
        "source_uri": "sharepoint://legal/acme-msa.pdf",
        "source_sha256": "sha-acme",
        "source_format": "pdf",
        "today": TODAY,
        "added_at": FROZEN_NOW,
    }
    kwargs.update(overrides)
    return assemble_card(carding or draft(), **kwargs)


def existing(contract_id: str, title: str, contract_type: str = "msa", party: str = "ACME, Inc."):
    """An existing card used as a parent candidate."""
    return ContractCard(
        contract_id=contract_id,
        title=title,
        contract_type=contract_type,
        source_uri=f"x://{contract_id}",
        parties=[
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id=f"party-{contract_id}", name=party, role="customer"),
        ],
    )


# --------------------------------------------------------------------------
# 1. Date derivations and status precedence
# --------------------------------------------------------------------------


def test_notice_deadline_is_expiration_minus_notice_days():
    assert derive_notice_deadline(date(2026, 12, 31), 60) == date(2026, 11, 1)
    assert derive_notice_deadline(date(2026, 12, 31), 0) == date(2026, 12, 31)


@pytest.mark.parametrize(
    ("expiration", "notice"),
    [(None, 60), (date(2026, 12, 31), None), (None, None)],
)
def test_notice_deadline_needs_both_inputs(expiration, notice):
    assert derive_notice_deadline(expiration, notice) is None


def test_next_renewal_date_only_when_auto_renewing():
    assert derive_next_renewal_date(date(2026, 12, 31), True) == date(2026, 12, 31)
    assert derive_next_renewal_date(date(2026, 12, 31), False) is None
    assert derive_next_renewal_date(None, True) is None


def test_status_supersession_wins_over_everything():
    term = TermSpec(effective_date=date(2026, 1, 1), expiration_date=date(2026, 12, 31))
    assert derive_status(term=term, today=TODAY, signed=True, superseded=True) == "superseded"
    assert (
        derive_status(
            term=term,
            today=TODAY,
            signed=True,
            superseded=True,
            termination_confirmed=True,
            terminated_on=date(2026, 3, 1),
        )
        == "superseded"
    )


def test_status_termination_requires_human_confirmation_and_an_elapsed_date():
    term = TermSpec(effective_date=date(2026, 1, 1), expiration_date=date(2026, 12, 31))
    # A termination *clause* alone never terminates a contract.
    assert derive_status(term=term, today=TODAY, signed=True) == "active"
    assert (
        derive_status(term=term, today=TODAY, signed=True, termination_confirmed=True) == "active"
    ), "confirmed termination without a date does not terminate"
    assert (
        derive_status(
            term=term,
            today=TODAY,
            signed=True,
            termination_confirmed=True,
            terminated_on=date(2026, 12, 1),
        )
        == "active"
    ), "a future termination date has not elapsed yet"
    assert (
        derive_status(
            term=term,
            today=TODAY,
            signed=True,
            termination_confirmed=True,
            terminated_on=TODAY,
        )
        == "terminated"
    )


def test_status_expired_only_for_non_renewing_terms():
    expired = TermSpec(effective_date=date(2024, 1, 1), expiration_date=date(2025, 12, 31))
    assert derive_status(term=expired, today=TODAY, signed=True) == "expired"

    renewing = expired.model_copy(update={"auto_renew": True})
    assert derive_status(term=renewing, today=TODAY, signed=True) == "active"


def test_status_exact_expiration_boundary_is_still_active():
    boundary = TermSpec(effective_date=date(2026, 1, 1), expiration_date=TODAY)
    assert derive_status(term=boundary, today=TODAY, signed=True) == "active"

    day_after = TermSpec(effective_date=date(2026, 1, 1), expiration_date=date(2026, 9, 8))
    assert derive_status(term=day_after, today=TODAY, signed=True) == "expired"


def test_status_effective_date_boundary():
    starts_today = TermSpec(effective_date=TODAY)
    assert derive_status(term=starts_today, today=TODAY, signed=True) == "active"

    starts_tomorrow = TermSpec(effective_date=date(2026, 9, 10))
    assert derive_status(term=starts_tomorrow, today=TODAY, signed=True) == "unknown"
    assert derive_status(term=starts_tomorrow, today=TODAY, signed=False) == "draft"


def test_status_unsigned_is_draft_and_unknown_dates_stay_unknown():
    assert derive_status(term=TermSpec(), today=TODAY, signed=False) == "draft"
    assert derive_status(term=TermSpec(), today=TODAY, signed=True) == "unknown"


# --------------------------------------------------------------------------
# 2. Parent resolution
# --------------------------------------------------------------------------


def test_normalized_names_ignore_legal_suffixes_and_punctuation():
    assert normalize_party_name("ACME, Inc.") == "acme"
    assert normalize_party_name("Acme Incorporated") == "acme"
    assert normalize_party_name("ACME Holdings Ltd") == "acme"
    assert normalize_party_name("") == ""


def test_similarity_is_normalized_to_the_unit_interval():
    assert similarity("acme msa", "acme msa") == 1.0
    assert 0.0 <= similarity("acme master services agreement", "zeta nda") < 0.85
    assert similarity("", "acme") == 0.0


def test_sow_resolves_to_a_single_matching_msa():
    resolution = resolve_parent(
        contract_type="sow",
        counterparties=["acme"],
        parent_title="ACME Master Services Agreement",
        candidates=[existing("acme-msa", "ACME Master Services Agreement")],
    )
    assert resolution.parent_contract_id == "acme-msa"
    assert resolution.ambiguous is False
    assert resolution.score >= PARENT_SIMILARITY_THRESHOLD


def test_amendment_resolves_to_its_referenced_base():
    resolution = resolve_parent(
        contract_type="amendment",
        counterparties=["acme"],
        parent_title="ACME Statement of Work 3",
        candidates=[
            existing("acme-sow-3", "ACME Statement of Work 3", contract_type="sow"),
            existing("acme-msa", "ACME Master Services Agreement"),
        ],
    )
    assert resolution.parent_contract_id == "acme-sow-3"


def test_incompatible_type_never_becomes_a_parent():
    resolution = resolve_parent(
        contract_type="sow",
        counterparties=["acme"],
        parent_title="ACME Mutual NDA",
        candidates=[existing("acme-nda", "ACME Mutual NDA", contract_type="nda")],
    )
    assert resolution.parent_contract_id is None
    assert "similarity threshold" in resolution.reason


def test_a_different_counterparty_never_becomes_a_parent():
    resolution = resolve_parent(
        contract_type="sow",
        counterparties=["zeta"],
        parent_title="ACME Master Services Agreement",
        candidates=[existing("acme-msa", "ACME Master Services Agreement")],
    )
    assert resolution.parent_contract_id is None


def test_below_threshold_similarity_is_refused():
    resolution = resolve_parent(
        contract_type="sow",
        counterparties=["acme"],
        parent_title="Completely Different Document Name",
        candidates=[existing("acme-msa", "ACME Master Services Agreement")],
    )
    assert resolution.parent_contract_id is None
    assert resolution.score == 0.0


def test_exact_threshold_qualifies():
    resolution = resolve_parent(
        contract_type="sow",
        counterparties=["acme"],
        parent_title="ACME Master Services Agreement",
        candidates=[existing("acme-msa", "ACME Master Services Agreement")],
        threshold=1.0,
    )
    assert resolution.parent_contract_id == "acme-msa"
    assert resolution.score == 1.0


def test_ambiguous_candidates_leave_the_parent_null():
    resolution = resolve_parent(
        contract_type="sow",
        counterparties=["acme"],
        parent_title="ACME Master Services Agreement",
        candidates=[
            existing("acme-msa-2024", "ACME Master Services Agreement"),
            existing("acme-msa-2026", "ACME Master Services Agreement"),
        ],
    )
    assert resolution.parent_contract_id is None
    assert resolution.ambiguous is True
    assert resolution.candidates == ["acme-msa-2024", "acme-msa-2026"]


def test_missing_referenced_title_refuses_to_guess():
    resolution = resolve_parent(
        contract_type="sow",
        counterparties=["acme"],
        parent_title=None,
        candidates=[existing("acme-msa", "ACME Master Services Agreement")],
    )
    assert resolution.parent_contract_id is None
    assert "no referenced parent title" in resolution.reason


def test_types_without_a_parent_rule_are_never_linked():
    resolution = resolve_parent(
        contract_type="msa",
        counterparties=["acme"],
        parent_title="ACME Master Services Agreement",
        candidates=[existing("acme-msa", "ACME Master Services Agreement")],
    )
    assert resolution.parent_contract_id is None
    assert "no v1 parent rule" in resolution.reason


# --------------------------------------------------------------------------
# 3. Assembly: ids, provenance and staleness
# --------------------------------------------------------------------------


def test_assembly_builds_stable_ids_and_resolves_aliases():
    card = assemble(party_aliases={"acme": "party-acme-canonical"})

    assert card.contract_id == card.tree_name == "acme-msa"
    assert [party.party_id for party in card.parties] == [
        "party-troc-global",
        "party-acme-canonical",
    ]
    assert card.signatories[0].person_id == "acme-msa-person-jane-doe"
    assert card.signatories[0].party_id == "party-acme-canonical"
    assert sum(1 for party in card.parties if party.is_us) == 1

    again = assemble(party_aliases={"acme": "party-acme-canonical"})
    assert again.model_dump() == card.model_dump()


def test_assembly_numbers_obligations_and_resolves_standards():
    carding = draft(
        obligations=ObligationsDraft(
            clauses=[
                ObligationClauseDraft(
                    excerpt="Vendor shall maintain SOC 2 Type II certification.",
                    node_id="0005",
                    kind="compliance",
                    standard_name="SOC 2 Type II",
                    confidence=0.9,
                ),
                ObligationClauseDraft(
                    excerpt="Vendor shall carry cyber liability insurance.",
                    node_id="0008",
                    kind="insurance",
                    standard_name="cyber liability insurance",
                    confidence=0.8,
                ),
                ObligationClauseDraft(
                    excerpt="Vendor shall be nice.",
                    node_id="0009",
                    kind="other",
                    standard_name="Some Unknown Framework",
                    confidence=0.5,
                ),
            ]
        )
    )
    card = assemble(carding)

    assert [ob.obligation_id for ob in card.obligations] == [
        "acme-msa-ob-001",
        "acme-msa-ob-002",
        "acme-msa-ob-003",
    ]
    assert [ob.standard_id for ob in card.obligations] == ["soc2", "cyber_insurance", None]
    assert all(ob.contract_id == "acme-msa" for ob in card.obligations)
    assert card.obligations[0].provenance.quote.startswith("Vendor shall maintain")


def test_derived_fields_declare_their_input_paths():
    carding = draft(
        header=header(
            expiration_date=Extracted[date](value=date(2026, 12, 31), evidence=evidence("0003"), confidence=0.9),
            notice_days=Extracted[int](value=60, evidence=evidence("0004"), confidence=0.9),
            auto_renew=Extracted[bool](value=True, evidence=evidence("0004"), confidence=0.9),
            effective_date=Extracted[date](value=date(2026, 1, 1), evidence=evidence("0003"), confidence=0.9),
        )
    )
    card = assemble(carding)

    assert card.term.notice_deadline == date(2026, 11, 1)
    assert card.term.next_renewal_date == date(2026, 12, 31)

    notice = card.field_provenance["term.notice_deadline"]
    assert notice.origin == "rule"
    assert notice.derived_from == ["term.expiration_date", "term.notice_days"]

    renewal = card.field_provenance["term.next_renewal_date"]
    assert renewal.derived_from == ["term.expiration_date", "term.auto_renew"]

    status = card.field_provenance["status"]
    assert status.origin == "rule"
    assert "term.effective_date" in status.derived_from
    assert card.status == "active"


def test_extracted_provenance_keeps_the_quote_and_confidence():
    card = assemble()
    title = card.field_provenance["title"]
    assert title.origin == "llm"
    assert title.quote == "quoted text"
    assert title.confidence == pytest.approx(0.9)
    assert card.field_provenance["parties.party-acme.name"].node_id == "0001"


def test_assembly_never_elevates_unsupported_draft_evidence():
    carding = draft(
        header=header(
            title=Extracted[str](value="Unsupported title", confidence=0.99),
            governing_law=Extracted[str](value="Delaware", confidence=0.95),
        )
    )
    card = assemble(carding)

    title = card.field_provenance["title"]
    assert title.quote is None
    assert title.confidence == pytest.approx(0.5)
    assert "title" in card.stale_fields
    assert "governing_law" in card.stale_fields
    assert card.verification == "extracted"


def test_ambiguous_parent_leaves_the_field_null_and_stale():
    carding = draft(
        header=header(
            contract_type=Extracted[str](value="sow", evidence=evidence(), confidence=0.9),
            parent_contract_title=Extracted[str](
                value="ACME Master Services Agreement", evidence=evidence(), confidence=0.9
            ),
        )
    )
    card = assemble(
        carding,
        contract_id="acme-sow-1",
        candidates=[
            existing("acme-msa-2024", "ACME Master Services Agreement"),
            existing("acme-msa-2026", "ACME Master Services Agreement"),
        ],
    )
    assert card.parent_contract_id is None
    assert "parent_contract_id" in card.stale_fields


def test_resolved_parent_records_rule_provenance():
    carding = draft(
        header=header(
            contract_type=Extracted[str](value="sow", evidence=evidence(), confidence=0.9),
            parent_contract_title=Extracted[str](
                value="ACME Master Services Agreement", evidence=evidence(), confidence=0.9
            ),
        )
    )
    card = assemble(
        carding,
        contract_id="acme-sow-1",
        candidates=[existing("acme-msa", "ACME Master Services Agreement")],
    )
    assert card.parent_contract_id == "acme-msa"
    assert card.field_provenance["parent_contract_id"].origin == "rule"
    assert "parent_contract_id" not in card.stale_fields


def test_signatory_without_a_resolvable_party_is_dropped_and_marked_stale():
    carding = draft(
        header=header(
            signatories=[
                SignatoryDraft(
                    name="Ghost Signer",
                    party_name="Unrelated Corp",
                    evidence=evidence("0007"),
                    confidence=0.8,
                )
            ]
        )
    )
    card = assemble(carding)
    assert card.signatories == []
    assert "signatories.0.party_id" in card.stale_fields
    assert card.status == "draft", "no signatory means an unsigned draft"


def test_assembly_carries_source_toc_and_owner_metadata():
    toc = [TocEntry(node_id="0001", title="Cover", depth=1, start_page=1)]
    card = assemble(
        toc=toc,
        toc_digest="1 Cover (pp. 1-2)",
        page_count=14,
        source_path="/tmp/staging/acme.pdf",
        owner_employee_id="emp-42",
        department="legal",
    )
    assert card.toc == toc
    assert card.toc_digest == "1 Cover (pp. 1-2)"
    assert card.page_count == 14
    assert card.source_path == "/tmp/staging/acme.pdf"
    assert card.owner_employee_id == "emp-42"
    assert card.department == "legal"
    assert card.added_at == card.updated_at == FROZEN_NOW


def test_fallback_origin_is_preserved_through_assembly():
    card = assemble(draft(origin="fallback", llm_calls=0, header=header()))
    assert card.card_origin == "fallback"


def test_superseded_flag_reaches_the_status_precedence():
    card = assemble(superseded=True)
    assert card.status == "superseded"


def test_today_is_injected_not_read_from_the_clock():
    carding = draft(
        header=header(
            effective_date=Extracted[date](value=date(2020, 1, 1), evidence=evidence(), confidence=0.9),
            expiration_date=Extracted[date](value=date(2021, 1, 1), evidence=evidence(), confidence=0.9),
        )
    )
    assert assemble(carding, today=date(2020, 6, 1)).status == "active"
    assert assemble(carding, today=date(2026, 9, 9)).status == "expired"
