"""Citation and claim verification tests (TASK-3044)."""

from __future__ import annotations

import ast
import inspect
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from parrot.knowledge.contracts.evidence import EvidenceArchive
from parrot.knowledge.contracts.models import (
    AnswerRecord,
    AuthorizationOutcome,
    Citation,
    ContractVersion,
    HandoffBrief,
)
from parrot_tools.contracts.verifier import (
    AnswerDraft,
    CitationVerifier,
    Claim,
)

from .test_retrieval import FROZEN_NOW, FakeCatalog, make_card

CLAUSE = "Vendor shall maintain SOC 2 Type II certification."
INSURANCE = "Vendor shall carry cyber liability insurance."


@pytest.fixture()
async def verifier(tmp_path):
    """A verifier over one archived card with two evidenced clauses."""
    catalog = FakeCatalog()
    card = make_card()
    await catalog.upsert(card)

    archive = EvidenceArchive(tmp_path / "evidence", tenant_id="troc")
    for version in card.versions:
        await archive.archive(
            archive.reference(
                card.contract_id,
                version_n=version.n,
                revision=version.revision,
                source_sha256=version.source_sha256,
            ),
            {"0005": f"4. Compliance. {CLAUSE}", "0008": f"7. Insurance. {INSURANCE}"},
            pages={"0005": 12, "0008": 18},
        )
    return CitationVerifier(catalog=catalog, evidence=archive)


def citation(**overrides) -> Citation:
    """A citation to version 1 of the ACME MSA compliance clause."""
    payload = {
        "contract_id": "acme-msa",
        "title": "whatever the model claimed",
        "node_id": "0005",
        "quote": CLAUSE,
        "page": 12,
        "version_n": 1,
        "source_sha256": "sha-acme-msa",
        "verification": "verified",
    }
    payload.update(overrides)
    return Citation(**payload)


async def dossier_of(verifier) -> list:
    return await verifier.catalog.list_cards()


# --------------------------------------------------------------------------
# 1. Rejection cases
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_valid_citation_is_released_with_derived_metadata(verifier):
    draft = AnswerDraft(claims=[Claim(text="ACME must hold SOC 2.", citations=[citation()])])
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier), pattern="x")

    assert outcome.answer.answer_kind == "lookup"
    assert outcome.answer.answer == "ACME must hold SOC 2."
    assert outcome.rejected == []
    released = outcome.released_citations[0]
    assert released.title == "acme-msa agreement", "the title comes from the card"
    assert released.page == 12, "the page comes from the archived manifest"
    assert released.verification == "extracted", "derived from the obligation, not the model"


@pytest.mark.asyncio
async def test_a_citation_outside_the_authorized_dossier_is_rejected(verifier):
    draft = AnswerDraft(
        claims=[Claim(text="Foreign contract says so.", citations=[citation(contract_id="zeta-nda")])]
    )
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier))

    assert outcome.answer.answer_kind == "not_found"
    assert outcome.rejected[0].reason == "citation is outside this request's authorized dossier"


@pytest.mark.asyncio
async def test_an_unknown_node_is_rejected(verifier):
    draft = AnswerDraft(claims=[Claim(text="c", citations=[citation(node_id="9999")])])
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier))
    assert "not in this version" in outcome.rejected[0].reason


@pytest.mark.asyncio
async def test_a_wrong_version_or_hash_is_rejected(verifier):
    version = await verifier.verify(
        AnswerDraft(claims=[Claim(text="c", citations=[citation(version_n=9)])]),
        dossier=await dossier_of(verifier),
    )
    assert version.answer.answer_kind == "not_found"

    hashed = await verifier.verify(
        AnswerDraft(claims=[Claim(text="c", citations=[citation(source_sha256="forged")])]),
        dossier=await dossier_of(verifier),
    )
    assert "source hash" in hashed.rejected[0].reason


@pytest.mark.asyncio
async def test_a_wrong_page_is_rejected(verifier):
    outcome = await verifier.verify(
        AnswerDraft(claims=[Claim(text="c", citations=[citation(page=99)])]),
        dossier=await dossier_of(verifier),
    )
    assert "page does not match" in outcome.rejected[0].reason


@pytest.mark.asyncio
async def test_empty_and_mismatched_quotes_are_rejected(verifier):
    with pytest.raises(Exception):
        citation(quote="   ")  # the model cannot even construct it

    mismatched = await verifier.verify(
        AnswerDraft(
            claims=[Claim(text="c", citations=[citation(quote="Vendor shall donate a pony.")])]
        ),
        dossier=await dossier_of(verifier),
    )
    assert "not verbatim" in mismatched.rejected[0].reason


@pytest.mark.asyncio
async def test_retired_evidence_is_rejected(verifier):
    await verifier.catalog.record_answer(
        AnswerRecord(
            answer_id="ans-1",
            asked_at=FROZEN_NOW,
            user="bob@troc",
            question="q",
            answer_kind="lookup",
            answer="a",
            citations=[citation()],
            authorization=AuthorizationOutcome(allowed=True),
        )
    )
    await verifier.catalog.retire_answer("ans-1", user="bob@troc", reason="wrong clause")

    outcome = await verifier.verify(
        AnswerDraft(claims=[Claim(text="c", citations=[citation()])]),
        dossier=await dossier_of(verifier),
    )
    assert outcome.answer.answer_kind == "not_found"
    assert outcome.rejected[0].reason == "evidence was retired"


@pytest.mark.asyncio
async def test_retirement_survives_renumbering_of_an_unchanged_excerpt(verifier, tmp_path):
    """A refresh that moves the clause to a new version cannot evade retirement."""
    await verifier.catalog.record_answer(
        AnswerRecord(
            answer_id="ans-1",
            asked_at=FROZEN_NOW,
            user="bob@troc",
            question="q",
            answer_kind="lookup",
            answer="a",
            citations=[citation()],
            authorization=AuthorizationOutcome(allowed=True),
        )
    )
    await verifier.catalog.retire_answer("ans-1", user="bob@troc", reason="wrong clause")

    # Same node, same excerpt, later version — still suppressed.
    outcome = await verifier.verify(
        AnswerDraft(claims=[Claim(text="c", citations=[citation(version_n=2)])]),
        dossier=await dossier_of(verifier),
    )
    assert outcome.rejected[0].reason == "evidence was retired"


# --------------------------------------------------------------------------
# 2. Claim support
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_orphan_claim_is_dropped_even_when_another_citation_passes(verifier):
    draft = AnswerDraft(
        claims=[
            Claim(text="ACME must hold SOC 2.", citations=[citation()]),
            Claim(
                text="ACME must also indemnify us without limit.",
                citations=[citation(node_id="9999", quote="Vendor shall indemnify without limit.")],
            ),
        ]
    )
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier))

    assert outcome.answer.answer == "ACME must hold SOC 2."
    assert "indemnify" not in (outcome.answer.answer or "")
    assert outcome.dropped_claims == ["ACME must also indemnify us without limit."]
    assert len(outcome.released_citations) == 1


@pytest.mark.asyncio
async def test_unrelated_surviving_evidence_cannot_rescue_free_prose(verifier):
    draft = AnswerDraft(
        claims=[
            Claim(text="Insurance is required.", citations=[citation(node_id="0008", quote=INSURANCE, page=18)]),
            Claim(text="We may terminate at will.", citations=[]),
        ]
    )
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier))

    assert outcome.answer.answer == "Insurance is required."
    assert outcome.dropped_claims == ["We may terminate at will."]


@pytest.mark.asyncio
async def test_zero_surviving_citations_becomes_not_found(verifier):
    draft = AnswerDraft(
        claims=[Claim(text="Everything is fine.", citations=[citation(node_id="9999")])]
    )
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier))

    assert outcome.answer.answer_kind == "not_found"
    assert outcome.answer.answer is None
    assert outcome.answer.citations == []
    assert outcome.answer.reason


@pytest.mark.asyncio
async def test_duplicate_citations_are_released_once(verifier):
    draft = AnswerDraft(
        claims=[
            Claim(text="First.", citations=[citation()]),
            Claim(text="Second.", citations=[citation()]),
        ]
    )
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier))
    assert len(outcome.released_citations) == 1
    assert outcome.answer.answer == "First. Second."


# --------------------------------------------------------------------------
# 3. Provenance, handoffs and kinds
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provenance_is_derived_from_surviving_citations(verifier, tmp_path):
    card = (await verifier.catalog.get("acme-msa")).model_copy(
        update={
            "obligations": [
                obligation.model_copy(update={"verification": "verified"})
                if obligation.node_id == "0005"
                else obligation.model_copy(update={"verification": "stale"})
                for obligation in (await verifier.catalog.get("acme-msa")).obligations
            ]
        }
    )
    await verifier.catalog.upsert(card)

    verified_only = await verifier.verify(
        AnswerDraft(claims=[Claim(text="a", citations=[citation()])]),
        dossier=await dossier_of(verifier),
    )
    assert verified_only.answer.provenance == "verified"

    mixed = await verifier.verify(
        AnswerDraft(
            claims=[
                Claim(text="a", citations=[citation()]),
                Claim(
                    text="b",
                    citations=[citation(node_id="0008", quote=INSURANCE, page=18)],
                ),
            ]
        ),
        dossier=await dossier_of(verifier),
    )
    assert mixed.answer.provenance == "mixed"
    assert [c.verification for c in mixed.answer.citations] == ["verified", "stale"]


@pytest.mark.asyncio
async def test_handoff_evidence_is_verified_the_same_way(verifier):
    draft = AnswerDraft(
        answer_kind="interpretation_required",
        handoff=HandoffBrief(
            question="Should we accept the redline?",
            why_judgment="a commercial decision",
            located_clauses=[citation(), citation(node_id="9999")],
        ),
    )
    outcome = await verifier.verify(draft, dossier=await dossier_of(verifier))

    assert outcome.answer.answer_kind == "interpretation_required"
    assert outcome.answer.answer is None
    assert len(outcome.answer.handoff.located_clauses) == 1
    assert outcome.rejected[0].node_id == "9999"


@pytest.mark.asyncio
async def test_denied_and_out_of_scope_carry_no_evidence(verifier):
    for kind in ("denied", "out_of_scope"):
        outcome = await verifier.verify(
            AnswerDraft(
                answer_kind=kind,
                claims=[Claim(text="should not be released", citations=[citation()])],
                reason="not permitted",
            ),
            dossier=await dossier_of(verifier),
        )
        assert outcome.answer.answer_kind == kind
        assert outcome.answer.answer is None
        assert outcome.answer.citations == []


@pytest.mark.asyncio
async def test_an_interpretation_draft_without_a_handoff_is_refused(verifier):
    with pytest.raises(ValueError, match="handoff"):
        await verifier.verify(
            AnswerDraft(answer_kind="interpretation_required"),
            dossier=await dossier_of(verifier),
        )


def test_the_verifier_never_calls_a_model():
    source = Path(inspect.getfile(CitationVerifier)).read_text()
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    for forbidden in ("ask", "ask_structured", "invoke", "completion"):
        assert forbidden not in called, forbidden
    signature = inspect.signature(CitationVerifier.__init__)
    assert not {"adapter", "client", "llm"} & set(signature.parameters)
