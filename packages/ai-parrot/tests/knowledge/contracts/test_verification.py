"""Verification and refresh tests — human decisions survive (TASK-3035)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from parrot.knowledge.contracts.catalog import CatalogConflictError, UnknownContractError
from parrot.knowledge.contracts.library import (
    ContractLibrary,
    get_card_field,
    merge_verified_fields,
    set_card_field,
)
from parrot.knowledge.contracts.models import (
    Citation,
    ContractCard,
    FieldProvenance,
    Party,
    TermSpec,
)

from .test_catalog_contract import InMemoryContractCatalog
from .test_ingestion import FakeIndexer, MSA_MARKDOWN, write

FROZEN_NOW = datetime(2026, 9, 9, 12, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 9, 9)


@pytest.fixture()
def library(tmp_path):
    """A no-LLM library over an in-memory catalog and fake indexer."""
    indexers: dict[Path, FakeIndexer] = {}
    catalog = InMemoryContractCatalog(now=FROZEN_NOW)
    return ContractLibrary(
        catalog=catalog,
        storage_root=tmp_path / "storage",
        evidence_root=tmp_path / "evidence",
        adapter=None,
        indexer_factory=lambda directory, adapter: indexers.setdefault(
            Path(directory), FakeIndexer(directory, adapter)
        ),
        now=lambda: FROZEN_NOW,
        today=lambda: TODAY,
    )


def card_with(**overrides) -> ContractCard:
    """Build a stored card directly, bypassing ingestion."""
    payload = {
        "contract_id": "acme-msa",
        "title": "ACME MSA",
        "contract_type": "msa",
        "status": "active",
        "source_uri": "sharepoint://legal/acme-msa.pdf",
        "source_sha256": "sha-v1",
        "source_format": "pdf",
        "parties": [Party(party_id="party-acme", name="ACME Inc.", role="customer")],
        "term": TermSpec(effective_date=date(2026, 1, 1), expiration_date=date(2026, 12, 31)),
        "field_provenance": {
            "title": FieldProvenance(
                origin="llm", node_id="0001", quote="ACME MSA", confidence=0.9
            ),
            "term.effective_date": FieldProvenance(
                origin="llm",
                node_id="0002",
                quote="effective as of January 1, 2026",
                confidence=0.9,
            ),
        },
        "added_at": FROZEN_NOW,
        "updated_at": FROZEN_NOW,
    }
    payload.update(overrides)
    return ContractCard(**payload)


def verified(quote: str, *, node_id: str = "0001", origin: str = "llm") -> FieldProvenance:
    """A verified provenance entry."""
    return FieldProvenance(
        origin=origin,
        verification="verified",
        node_id=node_id,
        quote=quote,
        confidence=0.9,
        verified_by="bob@troc",
        verified_at=FROZEN_NOW,
    )


# --------------------------------------------------------------------------
# Field addressing
# --------------------------------------------------------------------------


def test_paths_address_top_level_term_party_and_obligation_fields():
    card = card_with()
    assert get_card_field(card, "title") == "ACME MSA"
    assert get_card_field(card, "term.effective_date") == date(2026, 1, 1)
    assert get_card_field(card, "parties.party-acme.name") == "ACME Inc."

    updated = set_card_field(card, "term.notice_days", 60)
    assert updated.term.notice_days == 60
    assert set_card_field(card, "parties.party-acme.name", "ACME, Inc.").parties[0].name == (
        "ACME, Inc."
    )
    with pytest.raises(KeyError):
        get_card_field(card, "nonexistent")
    with pytest.raises(KeyError):
        set_card_field(card, "parties.ghost.name", "x")


# --------------------------------------------------------------------------
# verify_card
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirming_a_field_keeps_its_origin_and_stamps_the_actor(library):
    await library.catalog.upsert(card_with())
    result = await library.verify_card("acme-msa", {"title": None}, user="bob@troc")

    provenance = result.card.field_provenance["title"]
    assert result.verified == ["title"]
    assert result.corrected == []
    assert provenance.verification == "verified"
    assert provenance.origin == "llm", "confirming does not rewrite the origin"
    assert provenance.verified_by == "bob@troc"
    assert provenance.verified_at == FROZEN_NOW


@pytest.mark.asyncio
async def test_correcting_a_field_moves_the_origin_to_manual(library):
    await library.catalog.upsert(card_with())
    result = await library.verify_card(
        "acme-msa", {"title": "ACME Master Services Agreement"}, user="bob@troc"
    )

    assert result.corrected == ["title"]
    assert result.card.title == "ACME Master Services Agreement"
    provenance = result.card.field_provenance["title"]
    assert provenance.origin == "manual"
    assert provenance.verification == "verified"
    assert provenance.confidence == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_partial_verification_leaves_other_fields_untouched(library):
    await library.catalog.upsert(card_with())
    result = await library.verify_card("acme-msa", {"title": None}, user="bob@troc")

    assert result.card.field_provenance["term.effective_date"].verification == "extracted"
    assert result.card_verified is False
    assert any("term.effective_date" in blocker for blocker in result.blockers)


@pytest.mark.asyncio
async def test_whole_card_verification_requires_every_gap_to_be_resolved(library):
    await library.catalog.upsert(
        card_with(
            field_provenance={
                "title": FieldProvenance(origin="llm", node_id="0001"),  # no quote
                "governing_law": FieldProvenance(
                    origin="llm", node_id="0006", quote="Delaware law", confidence=0.4
                ),
            },
            stale_fields=["term.expiration_date"],
        )
    )
    blocked = await library.verify_card("acme-msa", user="bob@troc")
    assert blocked.card_verified is False
    assert blocked.blockers == ["term.expiration_date: stale"] or "stale" in " ".join(
        blocked.blockers
    )


@pytest.mark.asyncio
async def test_missing_evidence_and_low_confidence_are_reported_as_blockers(library):
    await library.catalog.upsert(
        card_with(
            field_provenance={
                "title": FieldProvenance(origin="llm", node_id="0001"),
                "governing_law": FieldProvenance(
                    origin="llm", node_id="0006", quote="Delaware law", confidence=0.4
                ),
            }
        )
    )
    card = await library.catalog.get("acme-msa")
    blockers = library._verification_blockers(card)
    assert "title: missing evidence" in blockers
    assert "governing_law: unresolved low confidence" in blockers


@pytest.mark.asyncio
async def test_verifying_everything_marks_the_card_verified(library):
    await library.catalog.upsert(
        card_with(
            field_provenance={
                "title": FieldProvenance(
                    origin="llm", node_id="0001", quote="ACME MSA", confidence=0.9
                )
            }
        )
    )
    result = await library.verify_card("acme-msa", user="bob@troc")

    assert result.card_verified is True
    assert result.card.verified_by == "bob@troc"
    assert result.card.verified_at == FROZEN_NOW
    assert result.card.field_provenance["title"].verification == "verified"


@pytest.mark.asyncio
async def test_rule_derived_fields_are_not_human_verified(library):
    await library.catalog.upsert(
        card_with(
            field_provenance={
                "status": FieldProvenance(origin="rule", derived_from=["term.effective_date"]),
                "title": FieldProvenance(
                    origin="llm", node_id="0001", quote="ACME MSA", confidence=0.9
                ),
            }
        )
    )
    result = await library.verify_card("acme-msa", user="bob@troc")
    assert result.card.field_provenance["status"].verification == "extracted"
    assert "status" not in result.verified
    assert result.card_verified is True


@pytest.mark.asyncio
async def test_correcting_a_term_field_recomputes_derived_values(library):
    await library.catalog.upsert(card_with())
    result = await library.verify_card(
        "acme-msa", {"term.notice_days": 60, "term.auto_renew": True}, user="bob@troc"
    )
    assert result.card.term.notice_deadline == date(2026, 11, 1)
    assert result.card.term.next_renewal_date == date(2026, 12, 31)


@pytest.mark.asyncio
async def test_manual_termination_confirmation_changes_the_status(library):
    await library.catalog.upsert(card_with())
    result = await library.verify_card(
        "acme-msa",
        {"termination_confirmed": True, "terminated_on": date(2026, 6, 1)},
        user="bob@troc",
    )
    assert result.card.status == "terminated"


@pytest.mark.asyncio
async def test_unknown_contract_and_unverifiable_paths_are_rejected(library):
    with pytest.raises(UnknownContractError):
        await library.verify_card("ghost", user="bob@troc")

    await library.catalog.upsert(card_with())
    with pytest.raises(KeyError, match="not a verifiable field"):
        await library.verify_card("acme-msa", {"revision": 99}, user="bob@troc")


@pytest.mark.asyncio
async def test_concurrent_verification_rejects_a_stale_revision(library):
    await library.catalog.upsert(card_with())
    await library.verify_card("acme-msa", {"title": None}, user="bob@troc", expected_revision=1)

    with pytest.raises(CatalogConflictError):
        await library.verify_card(
            "acme-msa", {"title": "Second writer"}, user="alice@troc", expected_revision=1
        )
    stored = await library.catalog.get("acme-msa")
    assert stored.title == "ACME MSA"
    assert stored.field_provenance["title"].verified_by == "bob@troc"


# --------------------------------------------------------------------------
# merge_verified_fields (refresh semantics)
# --------------------------------------------------------------------------


def test_unchanged_nonempty_quote_preserves_the_verified_value():
    previous = card_with(
        title="Corrected Title",
        field_provenance={"title": verified("ACME MSA", origin="manual")},
        verification="verified",
        verified_by="bob@troc",
        verified_at=FROZEN_NOW,
    )
    incoming = card_with(title="Model Guess")
    merged = merge_verified_fields(previous, incoming, {"0001": "Header: ACME MSA is here."})

    assert merged.title == "Corrected Title"
    assert merged.field_provenance["title"].verification == "verified"
    assert merged.field_provenance["title"].candidate is None
    assert merged.stale_fields == []
    assert merged.verification == "verified"


def test_moved_node_rebinds_the_evidence_without_losing_verification():
    previous = card_with(field_provenance={"title": verified("ACME MSA", node_id="0001")})
    incoming = card_with(title="Model Guess")
    merged = merge_verified_fields(previous, incoming, {"0007": "ACME MSA now lives here."})

    provenance = merged.field_provenance["title"]
    assert provenance.node_id == "0007"
    assert provenance.verification == "verified"
    assert merged.title == "ACME MSA"


def test_changed_evidence_keeps_the_prior_value_and_records_a_candidate():
    previous = card_with(field_provenance={"title": verified("ACME MSA")})
    incoming = card_with(title="ACME Master Services Agreement")
    merged = merge_verified_fields(previous, incoming, {"0001": "Completely different text."})

    assert merged.title == "ACME MSA", "the verified value survives"
    provenance = merged.field_provenance["title"]
    assert provenance.verification == "stale"
    assert provenance.candidate == "ACME Master Services Agreement"
    assert merged.stale_fields == ["title"]
    assert merged.verification == "stale"


def test_an_empty_quote_never_proves_unchanged_evidence():
    previous = card_with(
        field_provenance={
            "title": FieldProvenance(
                origin="llm",
                verification="verified",
                node_id="0001",
                quote="   ",
                verified_by="bob@troc",
                verified_at=FROZEN_NOW,
            )
        }
    )
    incoming = card_with(title="Model Guess")
    merged = merge_verified_fields(previous, incoming, {"0001": "ACME MSA"})

    assert merged.title == "ACME MSA " .strip() or merged.title == "ACME MSA"
    assert merged.field_provenance["title"].verification == "stale"
    assert "title" in merged.stale_fields


def test_changed_value_with_unchanged_evidence_keeps_the_human_decision():
    previous = card_with(
        term=TermSpec(effective_date=date(2026, 1, 1)),
        field_provenance={
            "term.effective_date": verified("effective as of January 1, 2026", node_id="0002")
        },
    )
    incoming = card_with(term=TermSpec(effective_date=date(2027, 5, 5)))
    merged = merge_verified_fields(
        previous, incoming, {"0002": "The Agreement is effective as of January 1, 2026."}
    )
    assert merged.term.effective_date == date(2026, 1, 1)
    assert merged.field_provenance["term.effective_date"].verification == "verified"


def test_unverified_fields_are_taken_from_the_refresh():
    previous = card_with(title="Old", field_provenance={"title": FieldProvenance(origin="llm")})
    incoming = card_with(title="New")
    merged = merge_verified_fields(previous, incoming, {"0001": "New"})
    assert merged.title == "New"


def test_manual_termination_confirmation_survives_a_refresh():
    previous = card_with(termination_confirmed=True, terminated_on=date(2026, 6, 1))
    incoming = card_with()
    merged = merge_verified_fields(previous, incoming, {})
    assert merged.termination_confirmed is True
    assert merged.terminated_on == date(2026, 6, 1)


# --------------------------------------------------------------------------
# refresh_card end to end
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_preserves_verified_values_and_historical_citations(library, tmp_path):
    path = write(tmp_path, "acme-msa.md")
    added = await library.add_contract(path)
    await library.verify_card(
        "acme-msa", {"title": "ACME Master Services Agreement"}, user="bob@troc"
    )
    version_one = (await library.catalog.versions("acme-msa"))[0]

    path.write_text(MSA_MARKDOWN.replace("twelve (12) months", "twenty-four (24) months"))
    refreshed = await library.refresh_card("acme-msa")

    assert refreshed.outcome == "updated"
    assert refreshed.card.title == "ACME Master Services Agreement"
    assert refreshed.card.field_provenance["title"].origin == "manual"

    # The citation released against version 1 still resolves.
    from parrot.knowledge.contracts.evidence import EvidenceRef

    citation = Citation(
        contract_id="acme-msa",
        node_id="0001",
        quote="twelve (12) months",
        version_n=1,
        source_sha256=added.card.source_sha256,
    )
    lookup = await library.evidence.resolve(citation, EvidenceRef.parse(version_one.evidence_ref))
    assert lookup.found is True


@pytest.mark.asyncio
async def test_refresh_of_unchanged_bytes_is_skipped(library, tmp_path):
    path = write(tmp_path, "acme-msa.md")
    await library.add_contract(path)
    result = await library.refresh_card("acme-msa")
    assert result.outcome == "skipped"
    assert "unchanged content" in result.reason


@pytest.mark.asyncio
async def test_refresh_of_an_unknown_contract_raises(library):
    with pytest.raises(UnknownContractError):
        await library.refresh_card("ghost")


# --------------------------------------------------------------------------
# Amendment effective history
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_amendment_records_an_interval_on_its_base(library):
    await library.catalog.upsert(card_with(contract_id="acme-msa"))
    await library.catalog.upsert(
        card_with(
            contract_id="acme-amd-1",
            contract_type="amendment",
            parent_contract_id="acme-msa",
            source_uri="sharepoint://legal/acme-amd-1.pdf",
            source_sha256="sha-amd",
            term=TermSpec(effective_date=date(2026, 7, 1)),
            field_provenance={
                "term.effective_date": verified("effective July 1, 2026", node_id="0002")
            },
        )
    )

    version = await library.apply_amendment_history("acme-amd-1", user="bob@troc")
    assert version is not None
    assert version.kind == "amendment"
    assert version.valid_from == date(2026, 7, 1)
    assert version.amended_by == "acme-amd-1"

    history = await library.catalog.versions("acme-msa")
    assert history[-1].amended_by == "acme-amd-1"
    # Re-applying is idempotent.
    assert await library.apply_amendment_history("acme-amd-1", user="bob@troc") is None


@pytest.mark.asyncio
async def test_unverified_or_unknown_effective_dates_create_no_interval(library):
    await library.catalog.upsert(card_with(contract_id="acme-msa"))
    await library.catalog.upsert(
        card_with(
            contract_id="acme-amd-2",
            contract_type="amendment",
            parent_contract_id="acme-msa",
            source_uri="sharepoint://legal/acme-amd-2.pdf",
            source_sha256="sha-amd-2",
            term=TermSpec(effective_date=date(2026, 7, 1)),
            field_provenance={
                "term.effective_date": FieldProvenance(
                    origin="llm", node_id="0002", quote="July 1, 2026", confidence=0.6
                )
            },
        )
    )
    assert await library.apply_amendment_history("acme-amd-2", user="bob@troc") is None

    await library.catalog.upsert(
        card_with(
            contract_id="acme-amd-3",
            contract_type="amendment",
            parent_contract_id="acme-msa",
            source_uri="sharepoint://legal/acme-amd-3.pdf",
            source_sha256="sha-amd-3",
            term=TermSpec(),
            field_provenance={"term.effective_date": verified("", node_id="0002")},
        )
    )
    assert await library.apply_amendment_history("acme-amd-3", user="bob@troc") is None
    assert len(await library.catalog.versions("acme-msa")) == 1


@pytest.mark.asyncio
async def test_amendment_without_a_resolved_parent_is_ignored(library):
    await library.catalog.upsert(
        card_with(
            contract_id="acme-amd-4",
            contract_type="amendment",
            source_uri="sharepoint://legal/acme-amd-4.pdf",
            source_sha256="sha-amd-4",
            term=TermSpec(effective_date=date(2026, 7, 1)),
            field_provenance={"term.effective_date": verified("effective July 1, 2026")},
        )
    )
    assert await library.apply_amendment_history("acme-amd-4", user="bob@troc") is None
