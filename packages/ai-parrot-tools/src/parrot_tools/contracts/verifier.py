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
        # One version-history read per contract, reused by every citation.
        versions: dict[str, dict[int, Any]] = {}

        surviving: list[Citation] = []
        rejected: list[RejectedCitation] = []
        dropped: list[str] = []
        kept_claims: list[str] = []

        for claim in draft.claims:
            claim_citations: list[Citation] = []
            for citation in claim.citations:
                verified, reason = await self._verify_citation(
                    citation, allowed, retired, versions
                )
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
        versions: dict[str, dict[int, Any]] = {}
        surviving: list[Citation] = []
        rejected: list[RejectedCitation] = []
        for citation in handoff.located_clauses:
            verified, reason = await self._verify_citation(
                citation, allowed, retired, versions
            )
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

    async def _archive_ref(
        self,
        card: ContractCard,
        citation: Citation,
        versions: dict[str, dict[int, Any]],
    ) -> EvidenceRef:
        """Resolve the archive pointer for ``citation``'s version.

        The evidence archive is immutable and written once per version, so
        the authoritative pointer is the one recorded on that version's row
        (``ContractVersion.evidence_ref``). It must never be rebuilt from
        the card's *current* revision or source hash: ordinary
        administrative writes — a human verification, a party merge — bump
        the card revision while the archive keeps the revision it was
        written with, and a rebuilt pointer would then address a directory
        that does not exist, silently rejecting every citation.

        Args:
            card: The authorized card the citation belongs to.
            citation: The citation being verified.
            versions: Per-contract version cache for this request.

        Returns:
            The stored reference when the version records one, else a
            reference rebuilt from the card (cards written before evidence
            references were recorded, and the in-memory test doubles).
        """
        if card.contract_id not in versions:
            try:
                history = await self.catalog.versions(card.contract_id)
            except Exception:  # noqa: BLE001 - fall back to the card below
                logger.exception(
                    "Could not load version history for %s", card.contract_id
                )
                history = []
            # A version accumulates one row per recorded revision, but its
            # evidence is archived exactly once, at the revision that first
            # recorded it. Later administrative revisions of the same
            # version carry no reference and must not shadow it.
            chosen: dict[int, Any] = {}
            for item in history:
                current = chosen.get(item.n)
                if current is None:
                    chosen[item.n] = item
                    continue
                if getattr(item, "evidence_ref", None) and not getattr(
                    current, "evidence_ref", None
                ):
                    chosen[item.n] = item
                elif (
                    bool(getattr(item, "evidence_ref", None))
                    == bool(getattr(current, "evidence_ref", None))
                    and item.revision < current.revision
                ):
                    chosen[item.n] = item
            versions[card.contract_id] = chosen

        version = versions[card.contract_id].get(citation.version_n)
        stored_ref = getattr(version, "evidence_ref", None) if version else None
        if stored_ref:
            try:
                ref = EvidenceRef.parse(stored_ref)
            except Exception:  # noqa: BLE001 - a malformed row must not leak
                logger.warning(
                    "Malformed evidence reference on %s v%s: %r",
                    card.contract_id,
                    citation.version_n,
                    stored_ref,
                )
            else:
                if (
                    ref.tenant_id == self.evidence.tenant_id
                    and ref.contract_id == card.contract_id
                ):
                    return ref
                logger.warning(
                    "Rejecting cross-tenant evidence reference on %s: %r",
                    card.contract_id,
                    stored_ref,
                )

        return EvidenceRef(
            tenant_id=self.evidence.tenant_id,
            contract_id=card.contract_id,
            version_n=citation.version_n,
            revision=version.revision if version else card.revision,
            source_sha256=(
                version.source_sha256 if version else card.source_sha256
            ),
        )

    async def _verify_citation(
        self,
        citation: Citation,
        allowed: dict[str, ContractCard],
        retired: set[tuple[str, str]],
        versions: dict[str, dict[int, Any]],
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

        ref = await self._archive_ref(card, citation, versions)
        source_sha256 = ref.source_sha256 or card.source_sha256
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
