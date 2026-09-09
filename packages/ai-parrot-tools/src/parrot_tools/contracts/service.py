"""The shared contracts answer service (FEAT-539 M10).

Both answer producers — the ReAct agent and the fixed flow — go through
this one service, so there is a single place where authorization, evidence
verification and audit happen. A producer only ever supplies a *draft*; it
never releases anything itself.

Order of operations, and why:

1. **Closed-set pre-triage** on the question alone. Evaluative/deontic
   requests become ``interpretation_required`` before any retrieval, and an
   unclassifiable question fails closed with a typed clarification.
2. **Authorize**, then retrieve — the gate runs before any protected read,
   including the located clauses a handoff will carry.
3. **Draft** from the enumerated, bounded dossier.
4. **Verify** every citation and claim against archived evidence.
5. **Audit**, and only then release. If the audit write fails, the request
   fails: an unaudited answer is never returned. Streaming buffers the
   substantive answer until this whole chain has succeeded.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.contracts.models import (
    AnswerRecord,
    AuthorizationOutcome,
    Citation,
    ContractAnswer,
    ContractCard,
    HandoffBrief,
)

from .retrieval import (
    AuthorizationDenied,
    Clarification,
    ContractRetrieval,
    RequestContext,
    RetrievalResult,
    is_interpretation,
)
from .verifier import AnswerDraft, CitationVerifier, VerificationOutcome

__all__ = (
    "MAX_DOSSIER_CARDS",
    "MAX_HANDOFF_CLAUSES",
    "AnswerProducer",
    "ServiceUnavailable",
    "ConfirmationRequired",
    "AnswerOutcome",
    "ContractsAnswerService",
)

logger = logging.getLogger(__name__)

#: Hard bound on the dossier handed to a producer.
MAX_DOSSIER_CARDS = 20

#: Hard bound on clauses located for a handoff brief.
MAX_HANDOFF_CLAUSES = 5


class AnswerProducer(Protocol):
    """What the service needs from an answer producer.

    A producer receives the enumerated dossier and returns a draft. It has
    no access to the release path.
    """

    async def draft(
        self,
        question: str,
        result: RetrievalResult,
        dossier: Sequence[ContractCard],
    ) -> AnswerDraft:
        ...


class ServiceUnavailable(RuntimeError):
    """A dependency the release path requires was unavailable.

    Raised — rather than answering — when the audit store cannot record the
    outcome, because an unaudited answer must never be released.
    """


class ConfirmationRequired(PermissionError):
    """A write operation needs an explicit human confirmation."""


class AnswerOutcome(BaseModel):
    """A released answer plus its audit identity."""

    answer: ContractAnswer
    answer_id: str
    audited: bool = True
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    dropped_claims: list[str] = Field(default_factory=list)


class ContractsAnswerService:
    """One authorization, evidence and audit gate for every answer path.

    Args:
        retrieval: The deterministic authorized retrieval.
        verifier: The citation/claim verification gate.
        producer: The draft producer (agent or fixed flow).
        library: Optional contract library for owner-only write operations.
        triage: Optional structured pre-triage adapter. It sees the
            question **only**, cannot generate AQL and cannot widen
            permissions.
        now: Injectable clock.
    """

    def __init__(
        self,
        *,
        retrieval: ContractRetrieval,
        verifier: CitationVerifier,
        producer: Optional[AnswerProducer] = None,
        library: Any = None,
        triage: Any = None,
        now: Any = None,
    ) -> None:
        self.retrieval = retrieval
        self.verifier = verifier
        self.producer = producer
        self.library = library
        self.triage = triage
        self._now = now or (lambda: datetime.now(tz=timezone.utc))
        #: Answer ids invalidated by a retirement, for transport caches.
        self.invalidated: set[str] = set()

    @property
    def catalog(self) -> Any:
        """The tenant-bound catalog behind the retrieval layer."""
        return self.retrieval.catalog

    # -- answering ---------------------------------------------------------

    async def answer(
        self,
        question: str,
        *,
        request_context: RequestContext,
        parameters: Optional[dict[str, Any]] = None,
    ) -> AnswerOutcome | Clarification:
        """Answer a question, or explain why it cannot be answered.

        Args:
            question: The user's question.
            request_context: The trusted request context.
            parameters: Optional explicit pattern parameters.

        Returns:
            An :class:`AnswerOutcome`, or a typed :class:`Clarification`.

        Raises:
            ServiceUnavailable: When the outcome could not be audited.
        """
        asked_at = self._now()

        # 1. Closed-set pre-triage on the question alone.
        if await self._triage_is_interpretation(question):
            return await self._interpretation(question, request_context, asked_at)

        # 2. Authorize, then retrieve.
        try:
            result = await self.retrieval.retrieve(question, request_context)
        except AuthorizationDenied as exc:
            return await self._release(
                ContractAnswer(answer_kind="denied", reason=exc.reason),
                question=question,
                context=request_context,
                asked_at=asked_at,
                allowed=False,
                reason=exc.reason,
            )
        if isinstance(result, Clarification):
            # A clarification is not an answer: it carries no evidence and
            # invents no new answer kind.
            return result
        if result.pattern == "interpretation":
            return await self._interpretation(question, request_context, asked_at)

        # 3. Enumerate a bounded dossier and draft from it.
        dossier = list(result.cards)[:MAX_DOSSIER_CARDS]
        if self.producer is None:
            raise ServiceUnavailable("no answer producer configured")
        draft = await self.producer.draft(question, result, dossier)

        # 4. Verify, then 5. audit and release.
        outcome = await self.verifier.verify(draft, dossier=dossier, pattern=result.pattern)
        return await self._release(
            outcome.answer,
            question=question,
            context=request_context,
            asked_at=asked_at,
            allowed=True,
            verification=outcome,
        )

    async def stream_answer(
        self,
        question: str,
        *,
        request_context: RequestContext,
    ) -> AsyncIterator[str]:
        """Stream an answer, buffering everything substantive.

        Nothing is yielded until authorization, verification and audit have
        all succeeded — a raw model draft can never reach a transport.
        """
        outcome = await self.answer(question, request_context=request_context)
        if isinstance(outcome, Clarification):
            yield outcome.reason
            return
        if outcome.answer.answer:
            yield outcome.answer.answer

    async def _triage_is_interpretation(self, question: str) -> bool:
        """Rule-based triage, optionally confirmed by a structured call."""
        if is_interpretation(question):
            return True
        if self.triage is None:
            return False
        verdict = await self.triage.classify(question)
        return bool(getattr(verdict, "interpretation_required", verdict is True))

    async def _interpretation(
        self,
        question: str,
        context: RequestContext,
        asked_at: datetime,
    ) -> AnswerOutcome | Clarification:
        """Build an audited handoff without adjudicating anything."""
        try:
            self.retrieval.authorize(context, pattern="interpretation")
        except AuthorizationDenied as exc:
            return await self._release(
                ContractAnswer(answer_kind="denied", reason=exc.reason),
                question=question,
                context=context,
                asked_at=asked_at,
                allowed=False,
                reason=exc.reason,
            )

        located: list[Citation] = []
        dossier: list[ContractCard] = []
        resolved = await self.retrieval.resolve_contract(question, context)
        if isinstance(resolved, str):
            # Clauses may be LOCATED after authorization to populate the
            # handoff — locating is not adjudicating, and each one still
            # has to survive the citation gate below.
            card = await self.retrieval._authorized_card(resolved, context)
            dossier = [card]
            version_n = card.versions[-1].n if card.versions else 1
            source_sha256 = (
                card.versions[-1].source_sha256 if card.versions else card.source_sha256
            )
            located = [
                Citation(
                    contract_id=card.contract_id,
                    title=card.title,
                    node_id=obligation.node_id,
                    quote=obligation.text[:300],
                    page=obligation.page,
                    verification=obligation.verification,
                    version_n=version_n,
                    source_sha256=source_sha256,
                )
                for obligation in card.obligations
                if obligation.active and obligation.text.strip()
            ][:MAX_HANDOFF_CLAUSES]

        handoff = HandoffBrief(
            question=question,
            why_judgment=(
                "the question asks for a judgement about what we should do; "
                "the contracts layer locates clauses but never adjudicates"
            ),
            located_clauses=located,
            related_contracts=[card.contract_id for card in dossier],
            suggested_owner=dossier[0].owner_employee_id if dossier else None,
        )
        draft = AnswerDraft(answer_kind="interpretation_required", handoff=handoff)
        outcome = await self.verifier.verify(draft, dossier=dossier, pattern="interpretation")
        return await self._release(
            outcome.answer,
            question=question,
            context=context,
            asked_at=asked_at,
            allowed=True,
            verification=outcome,
        )

    async def _release(
        self,
        answer: ContractAnswer,
        *,
        question: str,
        context: RequestContext,
        asked_at: datetime,
        allowed: bool,
        reason: Optional[str] = None,
        verification: Optional[VerificationOutcome] = None,
    ) -> AnswerOutcome:
        """Persist every outcome — including denials — before releasing it.

        Raises:
            ServiceUnavailable: When the audit write fails.
        """
        answer_id = f"ans-{uuid.uuid4().hex[:12]}"
        record = AnswerRecord(
            answer_id=answer_id,
            asked_at=asked_at,
            user=context.user_id or "anonymous",
            question=question,
            answer_kind=answer.answer_kind,
            pattern=answer.pattern,
            answer=answer.answer,
            citations=list(answer.citations),
            authorization=AuthorizationOutcome(
                allowed=allowed,
                principal=context.user_id,
                matched_rule=next(
                    (role for role in context.roles if role.startswith("contract_")), None
                ),
                reason=reason,
            ),
        )
        try:
            await self.catalog.record_answer(record)
        except Exception as exc:  # noqa: BLE001 - never release unaudited
            logger.error("Answer audit failed; refusing to release: %s", exc)
            raise ServiceUnavailable(
                f"the answer could not be audited and was not released: {exc}"
            ) from exc

        return AnswerOutcome(
            answer=answer,
            answer_id=answer_id,
            rejected=[item.model_dump() for item in (verification.rejected if verification else [])],
            dropped_claims=list(verification.dropped_claims) if verification else [],
        )

    # -- owner-only operations --------------------------------------------

    def _require_owner(self, context: RequestContext, *, operation: str) -> None:
        """Require the owner role **and** a trusted transport confirmation.

        Raises:
            AuthorizationDenied: Without an authenticated owner.
            ConfirmationRequired: Without an explicit confirmation.
        """
        self.retrieval.authorize(context, owner_only=True)
        if not context.confirmed:
            raise ConfirmationRequired(
                f"{operation} requires an explicit confirmation from the transport"
            )

    async def retire_answer(
        self,
        answer_id: str,
        *,
        request_context: RequestContext,
        reason: str,
    ) -> AnswerRecord:
        """Retire an answer and suppress its evidence.

        Args:
            answer_id: The audited answer to retire.
            request_context: Trusted context of an authenticated owner.
            reason: Why it is being retired (recorded).

        Returns:
            The retired :class:`AnswerRecord`.

        Raises:
            AuthorizationDenied: Without the owner role.
            ConfirmationRequired: Without transport confirmation.
        """
        self._require_owner(request_context, operation="retire_answer")
        record = await self.catalog.retire_answer(
            answer_id, user=request_context.user_id, reason=reason
        )
        # Any cached answer citing suppressed evidence is now invalid.
        self.invalidated.add(answer_id)
        logger.info("Answer %s retired by %s", answer_id, request_context.user_id)
        return record

    async def verify_card(
        self,
        contract_id: str,
        fields: Optional[dict[str, Any]] = None,
        *,
        request_context: RequestContext,
        expected_revision: Optional[int] = None,
    ) -> Any:
        """Verify/correct card fields on behalf of an authenticated owner.

        Raises:
            AuthorizationDenied / ConfirmationRequired: As above.
            ServiceUnavailable: When no library is configured.
        """
        self._require_owner(request_context, operation="verify_card")
        if self.library is None:
            raise ServiceUnavailable("no contract library configured for write operations")
        return await self.library.verify_card(
            contract_id,
            fields,
            user=request_context.user_id,
            expected_revision=expected_revision,
        )

    async def merge_parties(
        self,
        keep_party_id: str,
        merge_party_id: str,
        *,
        request_context: RequestContext,
    ) -> Any:
        """Merge two party identities on behalf of an authenticated owner."""
        self._require_owner(request_context, operation="merge_parties")
        return await self.catalog.merge_parties(
            keep_party_id, merge_party_id, user=request_context.user_id
        )
