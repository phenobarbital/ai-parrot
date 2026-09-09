"""Unit tests for the FEAT-539 contract models (TASK-3025)."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from parrot.knowledge.contracts.models import (
    MAX_QUOTE_CHARS,
    AnswerRecord,
    AuthorizationOutcome,
    Citation,
    ContractAnswer,
    ContractCard,
    ContractHeaderDraft,
    ContractRelation,
    ContractVersion,
    Evidence,
    Extracted,
    FieldProvenance,
    HandoffBrief,
    IngestItemReport,
    IngestReport,
    IngestResult,
    Obligation,
    Party,
    PublicationRecord,
    RelationJudgement,
    Signatory,
    SourceItem,
    TermSpec,
    card_snapshot_payload,
    derive_provenance,
)

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)


def _card(**overrides) -> ContractCard:
    """Build a minimal valid card with optional overrides."""
    payload = {
        "contract_id": "acme-msa",
        "title": "Master Services Agreement",
        "contract_type": "msa",
        "source_uri": "sharepoint://legal/acme-msa.pdf",
        "source_sha256": "a" * 64,
        "source_format": "pdf",
        "parties": [
            Party(party_id="party-us", name="Troc Global", role="us", is_us=True),
            Party(party_id="party-acme", name="ACME Inc.", role="customer"),
        ],
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


# --------------------------------------------------------------------------
# 1. JSON round trips preserve typed dates and nested evidence
# --------------------------------------------------------------------------


def test_card_json_round_trip_preserves_typed_dates_and_evidence():
    card = _card(
        term=TermSpec(
            effective_date=date(2026, 1, 1),
            expiration_date=date(2027, 1, 1),
            initial_term_months=12,
            auto_renew=True,
            renewal_period_months=12,
            notice_days=60,
            notice_deadline=date(2026, 11, 2),
            next_renewal_date=date(2027, 1, 1),
        ),
        signatories=[
            Signatory(
                person_id="p-1",
                name="Jane Doe",
                party_id="party-acme",
                title="CFO",
                signed_on=date(2025, 12, 20),
            )
        ],
        obligations=[
            Obligation(
                obligation_id="acme-msa-ob-1",
                contract_id="acme-msa",
                kind="compliance",
                obligor="counterparty",
                text="Vendor shall maintain SOC 2 Type II certification.",
                node_id="0007",
                page=12,
                standard_id="soc2",
                provenance=FieldProvenance(
                    origin="llm",
                    node_id="0007",
                    quote="Vendor shall maintain SOC 2 Type II certification.",
                    confidence=0.9,
                ),
            )
        ],
        field_provenance={
            "term.effective_date": FieldProvenance(
                origin="llm",
                node_id="0002",
                page=1,
                quote="This Agreement is effective as of January 1, 2026.",
                confidence=0.95,
            ),
            "term.notice_deadline": FieldProvenance(
                origin="rule",
                derived_from=["term.expiration_date", "term.notice_days"],
            ),
        },
    )

    raw = card.model_dump_json()
    restored = ContractCard.model_validate_json(raw)

    assert restored == card
    assert restored.term.effective_date == date(2026, 1, 1)
    assert restored.signatories[0].signed_on == date(2025, 12, 20)
    assert restored.added_at == FROZEN_NOW
    assert restored.field_provenance["term.effective_date"].page == 1
    assert restored.field_provenance["term.notice_deadline"].derived_from == [
        "term.expiration_date",
        "term.notice_days",
    ]
    assert restored.obligations[0].provenance.confidence == pytest.approx(0.9)


def test_extracted_generic_round_trip_keeps_value_type():
    extracted = Extracted[date](
        value=date(2026, 1, 1),
        evidence=Evidence(node_id="0002", quote="effective as of January 1, 2026", page=1),
        confidence=0.9,
    )
    restored = Extracted[date].model_validate_json(extracted.model_dump_json())
    assert restored.value == date(2026, 1, 1)
    assert restored.evidence.page == 1
    assert restored.substantiated is True


def test_header_draft_carries_no_derived_fields():
    fields = set(ContractHeaderDraft.model_fields)
    assert not fields & {
        "status",
        "notice_deadline",
        "next_renewal_date",
        "parent_contract_id",
    }


# --------------------------------------------------------------------------
# 2. Invalid taxonomy / confidence / quote / references fail validation
# --------------------------------------------------------------------------


def test_invalid_contract_type_is_rejected():
    with pytest.raises(ValidationError):
        _card(contract_type="framework_agreement")


def test_invalid_obligation_kind_is_rejected():
    with pytest.raises(ValidationError):
        Obligation(
            obligation_id="o1",
            contract_id="acme-msa",
            kind="tax",
            text="…",
            node_id="0001",
        )


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_outside_unit_interval_is_rejected(confidence):
    with pytest.raises(ValidationError):
        Extracted[str](value="x", confidence=confidence)


def test_quote_longer_than_cap_is_rejected():
    with pytest.raises(ValidationError):
        Evidence(node_id="0001", quote="x" * (MAX_QUOTE_CHARS + 1))


def test_blank_quote_caps_confidence_and_never_substantiates():
    extracted = Extracted[str](value="ACME", evidence=Evidence(node_id="0001", quote="  "), confidence=0.99)
    assert extracted.confidence == pytest.approx(0.5)
    assert extracted.substantiated is False

    provenance = FieldProvenance(origin="llm", node_id="0001", quote=None, confidence=0.95)
    assert provenance.confidence == pytest.approx(0.5)
    assert provenance.substantiates is False


def test_signatory_must_reference_a_card_party():
    with pytest.raises(ValidationError, match="unknown party"):
        _card(
            signatories=[
                Signatory(person_id="p-9", name="Ghost", party_id="party-unknown")
            ]
        )


def test_multiple_us_parties_are_rejected():
    with pytest.raises(ValidationError, match="at most one is_us party"):
        _card(
            parties=[
                Party(party_id="a", name="Troc Global", role="us", is_us=True),
                Party(party_id="b", name="Troc LLC", role="us", is_us=True),
            ]
        )


def test_duplicate_party_ids_are_rejected():
    with pytest.raises(ValidationError, match="unique"):
        _card(
            parties=[
                Party(party_id="a", name="Troc Global"),
                Party(party_id="a", name="ACME Inc."),
            ]
        )


def test_card_and_tree_identity_must_match():
    with pytest.raises(ValidationError, match="same slug"):
        _card(tree_name="another-tree")


def test_tree_name_defaults_to_contract_id():
    assert _card().tree_name == "acme-msa"


def test_obligation_must_belong_to_its_card():
    with pytest.raises(ValidationError, match="belongs to contract"):
        _card(
            obligations=[
                Obligation(
                    obligation_id="x",
                    contract_id="other-contract",
                    text="…",
                    node_id="0001",
                )
            ]
        )


def test_recursive_version_snapshot_is_rejected():
    with pytest.raises(ValidationError, match="omit its own 'versions'"):
        ContractVersion(
            n=1,
            card_snapshot={"contract_id": "acme-msa", "versions": [{"n": 1}]},
        )


def test_card_snapshot_payload_drops_versions():
    card = _card(
        versions=[ContractVersion(n=1, source_sha256="a" * 64, recorded_at=FROZEN_NOW)]
    )
    snapshot = card_snapshot_payload(card)
    assert "versions" not in snapshot
    version = ContractVersion(n=2, card_snapshot=snapshot, recorded_at=FROZEN_NOW)
    assert version.card_snapshot["contract_id"] == "acme-msa"


def test_verified_provenance_requires_actor_and_timestamp():
    with pytest.raises(ValidationError, match="verified_by and verified_at"):
        FieldProvenance(origin="manual", verification="verified")

    ok = FieldProvenance(
        origin="manual",
        verification="verified",
        verified_by="bob@troc",
        verified_at=FROZEN_NOW,
    )
    assert ok.verification == "verified"


def test_rule_origin_must_declare_its_inputs():
    with pytest.raises(ValidationError, match="derived_from"):
        FieldProvenance(origin="rule")


def test_verified_card_requires_actor_and_timestamp():
    with pytest.raises(ValidationError, match="verified_by and verified_at"):
        _card(verification="verified")


def test_confirmed_termination_requires_a_date():
    with pytest.raises(ValidationError, match="terminated_on"):
        _card(termination_confirmed=True)


def test_negative_term_periods_are_rejected():
    with pytest.raises(ValidationError):
        TermSpec(initial_term_months=-1)
    with pytest.raises(ValidationError):
        TermSpec(notice_days=-5)
    with pytest.raises(ValidationError):
        TermSpec(renewal_period_months=0)


def test_version_interval_must_be_half_open():
    with pytest.raises(ValidationError, match="after valid_from"):
        ContractVersion(n=1, valid_from=date(2026, 1, 1), valid_to=date(2026, 1, 1))


def test_version_in_force_requires_a_known_start():
    unresolved = ContractVersion(n=1)
    assert unresolved.in_force(date(2026, 6, 1)) is False

    version = ContractVersion(n=1, valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1))
    assert version.in_force(date(2026, 1, 1)) is True
    assert version.in_force(date(2027, 1, 1)) is False


# --------------------------------------------------------------------------
# 3. Answer-kind invariants
# --------------------------------------------------------------------------


def _citation(**overrides) -> Citation:
    payload = {
        "contract_id": "acme-msa",
        "title": "Master Services Agreement",
        "node_id": "0007",
        "quote": "Vendor shall maintain SOC 2 Type II certification.",
        "version_n": 1,
        "source_sha256": "a" * 64,
    }
    payload.update(overrides)
    return Citation(**payload)


def test_lookup_requires_answer_and_citation():
    with pytest.raises(ValidationError, match="requires answer text"):
        ContractAnswer(answer_kind="lookup", citations=[_citation()])
    with pytest.raises(ValidationError, match="at least one citation"):
        ContractAnswer(answer_kind="lookup", answer="Yes, SOC 2 is required.")

    answer = ContractAnswer(
        answer_kind="lookup",
        answer="Yes, SOC 2 is required.",
        citations=[_citation()],
    )
    assert answer.provenance == "extracted"


def test_interpretation_required_needs_a_handoff_and_no_judgment():
    handoff = HandoffBrief(question="Can we accept the redline?", why_judgment="legal call")
    with pytest.raises(ValidationError, match="requires a handoff"):
        ContractAnswer(answer_kind="interpretation_required")
    with pytest.raises(ValidationError, match="must not carry a judgment answer"):
        ContractAnswer(
            answer_kind="interpretation_required",
            answer="You may accept it.",
            handoff=handoff,
        )
    assert ContractAnswer(answer_kind="interpretation_required", handoff=handoff).answer is None


@pytest.mark.parametrize("kind", ["not_found", "out_of_scope", "denied"])
def test_empty_kinds_carry_no_answer_or_evidence(kind):
    with pytest.raises(ValidationError, match="must not carry answer text"):
        ContractAnswer(answer_kind=kind, answer="something")
    with pytest.raises(ValidationError, match="must not carry citations"):
        ContractAnswer(answer_kind=kind, citations=[_citation()])
    assert ContractAnswer(answer_kind=kind).provenance == "extracted"


def test_provenance_is_derived_from_citations():
    verified = _citation(verification="verified")
    stale = _citation(node_id="0009", verification="stale")

    assert derive_provenance([]) == "extracted"
    assert derive_provenance([verified]) == "verified"
    assert derive_provenance([verified, stale]) == "mixed"
    assert derive_provenance([stale]) == "extracted"

    answer = ContractAnswer(
        answer_kind="lookup",
        answer="Yes.",
        citations=[verified, stale],
        provenance="verified",
    )
    assert answer.provenance == "mixed"


def test_citation_quote_cannot_be_blank():
    with pytest.raises(ValidationError):
        _citation(quote="   ")


def test_citation_key_is_contract_and_node():
    assert _citation().key == ("acme-msa", "0007")


# --------------------------------------------------------------------------
# Audit, publication, source and relation records
# --------------------------------------------------------------------------


def test_answer_record_round_trip_and_retirement_flag():
    record = AnswerRecord(
        answer_id="ans-1",
        asked_at=FROZEN_NOW,
        user="bob@troc",
        question="Which contracts require SOC 2?",
        answer_kind="lookup",
        pattern="contracts_requiring_standard",
        answer="ACME MSA.",
        citations=[_citation()],
        authorization=AuthorizationOutcome(allowed=True, principal="bob@troc", matched_rule="contract_reader"),
    )
    restored = AnswerRecord.model_validate_json(record.model_dump_json())
    assert restored.retired is False
    assert restored.authorization.allowed is True

    retired = record.model_copy(
        update={"retired_at": FROZEN_NOW, "retired_by": "bob@troc", "retirement_reason": "wrong clause"}
    )
    assert retired.retired is True


def test_publication_record_key_is_tenant_scoped():
    record = PublicationRecord(
        tenant_id="troc",
        contract_id="acme-msa",
        version_n=2,
        revision=3,
        target="temporal",
        run_id="acme-msa:2:3",
    )
    assert record.key == ("troc", "acme-msa", 2, 3, "temporal")
    assert record.state == "pending"


def test_source_item_tracks_identity_and_tombstone():
    item = SourceItem(
        source="sharepoint://legal",
        drive_id="drive-1",
        item_id="item-1",
        current_uri="sharepoint://legal/acme-msa.pdf",
        contract_id="acme-msa",
        deleted=True,
    )
    assert item.deleted is True
    assert SourceItem.model_validate_json(item.model_dump_json()) == item


def test_relation_judgement_rejects_self_endpoints():
    with pytest.raises(ValidationError, match="itself"):
        RelationJudgement(
            judgement_id="j1",
            source_contract_id="acme-msa",
            target_contract_id="acme-msa",
        )


def test_symmetric_conflicts_relation_is_canonicalized():
    relation = ContractRelation(
        source_contract_id="zeta-nda",
        target_contract_id="acme-msa",
        kind="conflicts_with",
    )
    assert (relation.source_contract_id, relation.target_contract_id) == ("acme-msa", "zeta-nda")

    directed = ContractRelation(
        source_contract_id="zeta-nda",
        target_contract_id="acme-msa",
        kind="references_obligation",
    )
    assert directed.source_contract_id == "zeta-nda"


# --------------------------------------------------------------------------
# Ingestion reporting
# --------------------------------------------------------------------------


def test_ingest_result_requires_card_or_reason():
    with pytest.raises(ValidationError, match="must carry a card"):
        IngestResult(outcome="added")
    with pytest.raises(ValidationError, match="explicit reason"):
        IngestResult(outcome="skipped")

    skipped = IngestResult(outcome="skipped", reason="unchanged sha256", source_uri="x://y")
    assert skipped.card is None

    added = IngestResult(outcome="added", card=_card())
    assert added.source_uri == "sharepoint://legal/acme-msa.pdf"


def test_ingest_report_counts_every_outcome():
    report = IngestReport(
        items=[
            IngestItemReport.from_result(IngestResult(outcome="added", card=_card())),
            IngestItemReport(source_uri="x://b", outcome="updated", contract_id="b"),
            IngestItemReport(source_uri="x://c", outcome="skipped", reason="no extractable text"),
            IngestItemReport(source_uri="x://d", outcome="error", reason="download failed"),
        ]
    )
    assert report.summary() == {"added": 1, "updated": 1, "skipped": 1, "errors": 1}
    assert report.items[0].contract_id == "acme-msa"


def test_card_brief_is_bounded():
    card = _card(summary="First line.\nSecond line.")
    brief = card.brief()
    assert brief["summary"] == "First line."
    assert brief["counterparties"] == ["ACME Inc."]
    assert "toc" not in brief and "field_provenance" not in brief
