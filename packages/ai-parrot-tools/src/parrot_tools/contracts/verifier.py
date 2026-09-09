"""Versioned citation and claim verification gate (FEAT-539 M10).

The single gate both answer producers pass through. It is deterministic and
LLM-free: it takes a draft (claims plus the citations the draft attached to
each claim) and the **dossier this request was authorized to see**, and it
releases only what survives verification.

A citation survives when *all* of the following hold:

* it belongs to this request's authorized dossier — a model cannot cite a
  contract the caller never had access to;
* its ``(contract_id, node_id)`` pair is not retired;
* the version and source hash match the archived evidence, and the quote is
  nonempty and appears verbatim in **that version's** body;
* the recorded page matches.

Claim-to-citation support is explicit: a claim whose citations were all
rejected is dropped, and unrelated surviving evidence cannot rescue it.
Zero surviving citations turns a lookup into ``not_found``.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.contracts.evidence import EvidenceArchive, EvidenceRef, normalize_quote
from parrot.knowledge.contracts.models import (
    Citation,
    ContractAnswer,
    ContractCard,
    HandoffBrief,
    derive_provenance,
)

__all__ = (
    "Claim",
    "AnswerDraft",
    "RejectedCitation",
    "VerificationOutcome",
    "CitationVerifier",
)

logger = logging.getLogger(__name__)


class Claim(BaseModel):
    """One sentence of a draft answer and the citations it rests on.

    Support is explicit precisely so an unsupported claim can be removed
    without taking the rest of the answer with it.

    Args:
        text: The claim as drafted.
        citations: Citations the draft attached to *this* claim.
    """

    text: str = Field(..., min_length=1)
    citations: list[Citation] = Field(default_factory=list)


class AnswerDraft(BaseModel):
    """A model's proposed answer, before verification.

    Args:
        answer_kind: The kind the producer proposes.
        claims: The claims making up the answer.
        handoff: Handoff brief for an interpretation request.
        pattern: The retrieval pattern that produced the dossier.
        reason: Optional explanation for empty kinds.
    """

    answer_kind: str = "lookup"
    claims: list[Claim] = Field(default_factory=list)
    handoff: Optional[HandoffBrief] = None
    pattern: Optional[str] = None
    reason: Optional[str] = None


class RejectedCitation(BaseModel):
    """One citation that did not survive, with the reason it failed."""

    contract_id: str
    node_id: str
    reason: str


class VerificationOutcome(BaseModel):
    """The released answer plus everything that was removed on the way."""

    answer: ContractAnswer
    rejected: list[RejectedCitation] = Field(default_factory=list)
    dropped_claims: list[str] = Field(default_factory=list)

    @property
    def released_citations(self) -> list[Citation]:
        """Citations that survived verification."""
        return list(self.answer.citations)


class CitationVerifier:
    """Verify a draft against archived evidence and release an answer.

    Args:
        catalog: The tenant-bound catalog (retirement suppressions).
        evidence: The tenant-bound immutable evidence archive.
    """

    def __init__(self, *, catalog: Any, evidence: EvidenceArchive) -> None:
        self.catalog = catalog
        self.evidence = evidence

    async def verify(
        self,
        draft: AnswerDraft,
        *,
        dossier: Sequence[ContractCard],
        pattern: Optional[str] = None,
    ) -> VerificationOutcome:
        """Verify a draft and build the answer that may be released.

        Args:
            draft: The producer's proposed answer.
            dossier: The cards this request was authorized to read.
            pattern: The retrieval pattern, recorded on the answer.

        Returns:
            A :class:`VerificationOutcome`. Only kinds and citations that
            survive every check reach the returned answer.
        """
        kind = draft.answer_kind
        if kind in ("denied", "out_of_scope"):
            return VerificationOutcome(
                answer=ContractAnswer(
                    answer_kind=kind, pattern=pattern or draft.pattern, reason=draft.reason
                )
            )
        if kind == "interpretation_required":
            handoff, rejected = await self._verify_handoff(draft.handoff, dossier)
            return VerificationOutcome(
                answer=ContractAnswer(
                    answer_kind="interpretation_required",
                    handoff=handoff,
                    pattern=pattern or draft.pattern,
                ),
                rejected=rejected,
            )

        allowed = {card.contract_id: card for card in dossier}
        retired = await self.catalog.retired_citations()

        surviving: list[Citation] = []
        rejected: list[RejectedCitation] = []
        dropped: list[str] = []
        kept_claims: list[str] = []

        for claim in draft.claims:
            claim_citations: list[Citation] = []
            for citation in claim.citations:
                verified, reason = await self._verify_citation(citation, allowed, retired)
                if verified is None:
                    rejected.append(
                        RejectedCitation(
                            contract_id=citation.contract_id,
                            node_id=citation.node_id,
                            reason=reason,
                        )
                    )
                    continue
                claim_citations.append(verified)
            if not claim_citations:
                # An unsupported claim is removed. Another claim's surviving
                # citation must never rescue free prose.
                dropped.append(claim.text)
                continue
            kept_claims.append(claim.text)
            for citation in claim_citations:
                if not any(
                    existing.contract_id == citation.contract_id
                    and existing.node_id == citation.node_id
                    and existing.quote == citation.quote
                    for existing in surviving
                ):
                    surviving.append(citation)

        if not surviving:
            return VerificationOutcome(
                answer=ContractAnswer(
                    answer_kind="not_found",
                    pattern=pattern or draft.pattern,
                    reason="no citation survived verification",
                ),
                rejected=rejected,
                dropped_claims=dropped + kept_claims,
            )

        answer = ContractAnswer(
            answer_kind="lookup",
            answer=" ".join(kept_claims).strip(),
            citations=surviving,
            provenance=derive_provenance(surviving),
            pattern=pattern or draft.pattern,
        )
        return VerificationOutcome(answer=answer, rejected=rejected, dropped_claims=dropped)

    async def _verify_handoff(
        self,
        handoff: Optional[HandoffBrief],
        dossier: Sequence[ContractCard],
    ) -> tuple[HandoffBrief, list[RejectedCitation]]:
        """Apply the same evidence checks to a handoff's located clauses."""
        if handoff is None:
            raise ValueError("interpretation_required requires a handoff brief")
        allowed = {card.contract_id: card for card in dossier}
        retired = await self.catalog.retired_citations()
        surviving: list[Citation] = []
        rejected: list[RejectedCitation] = []
        for citation in handoff.located_clauses:
            verified, reason = await self._verify_citation(citation, allowed, retired)
            if verified is None:
                rejected.append(
                    RejectedCitation(
                        contract_id=citation.contract_id,
                        node_id=citation.node_id,
                        reason=reason,
                    )
                )
                continue
            surviving.append(verified)
        return handoff.model_copy(update={"located_clauses": surviving}), rejected

    async def _verify_citation(
        self,
        citation: Citation,
        allowed: dict[str, ContractCard],
        retired: set[tuple[str, str]],
    ) -> tuple[Optional[Citation], str]:
        """Verify one citation against the archive.

        Returns:
            ``(citation, "")`` when it survives — with title, page and
            verification derived from the evidence rather than trusted from
            the model — or ``(None, reason)``.
        """
        card = allowed.get(citation.contract_id)
        if card is None:
            return None, "citation is outside this request's authorized dossier"
        if citation.key in retired:
            return None, "evidence was retired"
        if not normalize_quote(citation.quote):
            return None, "empty quotes never prove evidence"

        version = next(
            (item for item in card.versions if item.n == citation.version_n), None
        )
        source_sha256 = version.source_sha256 if version else card.source_sha256
        revision = version.revision if version else card.revision
        ref = EvidenceRef(
            tenant_id=self.evidence.tenant_id,
            contract_id=card.contract_id,
            version_n=citation.version_n,
            revision=revision,
            source_sha256=source_sha256,
        )
        lookup = await self.evidence.resolve(citation, ref)
        if not lookup.found:
            return None, lookup.reason or "evidence could not be resolved"

        obligation = next(
            (
                item
                for item in card.obligations
                if item.node_id == citation.node_id
                and normalize_quote(item.text) == normalize_quote(citation.quote)
            ),
            None,
        )
        verification = obligation.verification if obligation else card.verification
        return (
            citation.model_copy(
                update={
                    # Title, page and verification come from the evidence and
                    # the card, never from the model's output.
                    "title": card.title,
                    "page": lookup.page if lookup.page is not None else citation.page,
                    "verification": verification,
                    "source_sha256": source_sha256,
                }
            ),
            "",
        )
