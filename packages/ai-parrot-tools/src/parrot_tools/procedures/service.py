"""The single release path for procedure answers (FEAT-601 M10, U4).

authorize -> plan -> execute -> assemble -> (draft prose) -> verify (blocking) -> audit -> presign -> release.
Pattern -> answer kind: procedure_steps/procedure_in_force => procedure; step_detail => step;
procedure_prerequisites => prerequisites; anything else => lookup (served in full by the toolkit tools,
TASK-3724) and, here, folded into a "lookup"/"not_found" answer built from the PageIndex fallback search
or, when the graph itself returns rows for those patterns but no procedure can be assembled from them,
from :meth:`ProcedureRetrieval.fallback_lookup` directly.

Deviation from the task's Implementation Blueprint (documented, not silent): ``ProcedureAnswer.media`` is
projected as ``MediaView`` (no ``storage_key``/``uri`` -- G4 never lets a released answer carry a raw
storage key). Presigning therefore needs the *raw* ``MediaRef`` rows the manual card carries
(``ManualCard.figures``), looked up by ``media_id`` the same way ``assembly._media`` already does. ``_release``
and ``_presign_media`` accept an extra ``figures`` argument carrying that lookup; every other name and
signature the task fixes (``AnswerProducer``, ``ServiceUnavailable``, ``AnswerOutcome``, ``answer``,
``stream_answer``) is unchanged.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Optional, Protocol, Sequence

from pydantic import BaseModel, Field

from parrot.knowledge.manuals.catalog import AnswerRecord, ManualCatalogStore
from parrot.knowledge.manuals.figures import MediaUnavailable, presign
from parrot.knowledge.manuals.models import ManualVersion, MediaRef, ProcedureAnswer, ProcedureCitation
from parrot_tools.procedures.assembly import AssembledProcedure, assemble_procedure
from parrot_tools.procedures.retrieval import (
    AuthorizationDenied,
    Clarification,
    ProcedureRetrieval,
    RequestContext,
    RetrievalResult,
)
from parrot_tools.procedures.verifier import ProcedureVerifier

logger = logging.getLogger(__name__)

_KIND_BY_PATTERN: dict[str, str] = {
    "procedure_steps": "procedure",
    "procedure_in_force": "procedure",
    "step_detail": "step",
    "procedure_prerequisites": "prerequisites",
}
NOT_VERIFIED_LINE = "This is a manual excerpt, not a verified procedure."
_LOOKUP_QUOTE_MAX_CHARS = 500


class AnswerProducer(Protocol):
    """Drafts optional intro prose -- the only model-authored text."""

    async def draft(self, question: str, assembled: AssembledProcedure, *, context: RequestContext) -> str: ...


class ServiceUnavailable(RuntimeError):
    """A dependency the release path requires (the audit store) failed; nothing was released."""


class AnswerOutcome(BaseModel):
    """A released answer, its audit id and the per-answer media URLs."""

    answer: ProcedureAnswer
    audit_id: str
    image_urls: list[str] = Field(default_factory=list)
    media_urls: list[str] = Field(default_factory=list)


class ProceduresAnswerService:
    """One authorization, verification and audit gate for every channel."""

    def __init__(
        self,
        *,
        retrieval: ProcedureRetrieval,
        verifier_factory: Callable[[ManualVersion], ProcedureVerifier],
        catalog: ManualCatalogStore,
        file_manager: Any,
        presign_expiry: int = 900,
        producer: Optional[AnswerProducer] = None,
    ) -> None:
        self.retrieval = retrieval
        self.verifier_factory = verifier_factory
        self.catalog = catalog
        self.file_manager = file_manager
        self.presign_expiry = presign_expiry
        self.producer = producer
        self.logger = logging.getLogger(__name__)

    async def answer(
        self, question: str, *, request_context: RequestContext, producer: Optional[AnswerProducer] = None
    ) -> AnswerOutcome | Clarification:
        """Answer ``question`` or explain why not. Raw producer output never leaves this method.

        Raises:
            ServiceUnavailable: When the outcome could not be audited (nothing is released).
        """
        selected = producer if producer is not None else self.producer
        try:
            plan = await self.retrieval.plan(question, request_context)
            if isinstance(plan, Clarification):
                return plan
            kind = _KIND_BY_PATTERN.get(plan.pattern, "lookup")
            if kind == "lookup":
                fallback = await self.retrieval.fallback_lookup(question, plan.manual_id or "", request_context)
                released = self._lookup_answer(fallback, pattern=plan.pattern)
                figures = fallback.manual.figures if fallback.manual else []
                return await self._release(
                    released, question=question, context=request_context, allowed=True, figures=figures
                )
            result = await self.retrieval.execute(plan, request_context)
            if not result.rows:
                fallback = await self.retrieval.fallback_lookup(question, plan.manual_id or "", request_context)
                released = self._lookup_answer(fallback, pattern=plan.pattern)
                figures = fallback.manual.figures if fallback.manual else []
                return await self._release(
                    released, question=question, context=request_context, allowed=True, figures=figures
                )
            assembled = assemble_procedure(result, kind=kind, step_order=plan.step_order, context=request_context)
            if assembled.needs_serial:
                return Clarification(reason="equipment_serial_required", pattern=plan.pattern)
            prose = ""
            if selected is not None and not (assembled.missing_required or assembled.unsupported_fields):
                prose = await selected.draft(question, assembled, context=request_context)
            outcome = await self.verifier_factory(assembled.revision).verify(
                assembled, draft_prose=prose, kind=kind, pattern=plan.pattern
            )
            released = outcome.answer
        except AuthorizationDenied as exc:
            denied = ProcedureAnswer(answer_kind="denied", answer="", reason=exc.reason, pattern=exc.pattern)
            return await self._release(denied, question=question, context=request_context, allowed=False, figures=[])
        figures = result.manual.figures if result.manual else []
        return await self._release(released, question=question, context=request_context, allowed=True, figures=figures)

    async def stream_answer(
        self, question: str, *, request_context: RequestContext, producer: Optional[AnswerProducer] = None
    ) -> AsyncIterator[str]:
        """Yield nothing until :meth:`answer` has released (contracts service.py:214-232)."""
        outcome = await self.answer(question, request_context=request_context, producer=producer)
        if isinstance(outcome, Clarification):
            yield outcome.reason
            return
        if outcome.answer.answer:
            yield outcome.answer.answer

    def _lookup_answer(self, result: RetrievalResult, *, pattern: str | None) -> ProcedureAnswer:
        """Build a ``lookup`` (or ``not_found``) answer from a PageIndex fallback search.

        Args:
            result: The output of :meth:`ProcedureRetrieval.fallback_lookup`.
            pattern: The originally classified pattern, kept for audit context.

        Returns:
            A ``lookup`` answer citing every usable excerpt, or ``not_found`` when none resolved.
        """
        manual_id = result.manual.manual_id if result.manual else None
        citations: list[ProcedureCitation] = []
        lines = [NOT_VERIFIED_LINE]
        for section in result.fallback_sections:
            node_id = section.get("node_id")
            text = section.get("excerpt") or section.get("text") or section.get("title")
            if not node_id or not text:
                continue
            quote = str(text).strip()[:_LOOKUP_QUOTE_MAX_CHARS]
            if not quote:
                continue
            citations.append(ProcedureCitation(manual_id=manual_id or "unknown", node_id=str(node_id), quote=quote))
            lines.append(quote)
        if not citations:
            return ProcedureAnswer(answer_kind="not_found", answer="", pattern=pattern)
        return ProcedureAnswer(answer_kind="lookup", answer="\n".join(lines), citations=citations, pattern=pattern)

    async def _release(
        self,
        answer: ProcedureAnswer,
        *,
        question: str,
        context: RequestContext,
        allowed: bool,
        figures: Sequence[MediaRef] = (),
    ) -> AnswerOutcome:
        """Audit first; only then presign media and release."""
        audit_id = f"proc-{uuid.uuid4().hex[:12]}"
        record = AnswerRecord(
            answer_id=audit_id,
            asked_at=datetime.now(timezone.utc),
            user=context.user_id or "anonymous",
            question=question,
            answer_kind=answer.answer_kind,
            pattern=answer.pattern,
            manual_id=answer.procedure.manual_id if answer.procedure else None,
            manual_revision=answer.manual_revision,
            citations=[citation.model_dump() for citation in answer.citations],
            allowed=allowed,
            reason=answer.reason if answer.answer_kind == "denied" else None,
            blocked_reason=answer.reason if answer.answer_kind == "incomplete" else None,
        )
        try:
            await self.catalog.record_answer(record)
        except Exception as exc:  # noqa: BLE001 - never release unaudited
            self.logger.error("Answer audit failed; refusing to release: %s", exc)
            raise ServiceUnavailable(f"the answer could not be audited and was not released: {exc}") from exc
        image_urls, media_urls = await self._presign_media(answer, figures)
        return AnswerOutcome(answer=answer, audit_id=audit_id, image_urls=image_urls, media_urls=media_urls)

    async def _presign_media(
        self, answer: ProcedureAnswer, figures: Sequence[MediaRef] = ()
    ) -> tuple[list[str], list[str]]:
        """Presign released figures/photos; deep-link released video segments."""
        figures_by_id = {figure.media_id: figure for figure in figures}
        images: list[str] = []
        videos: list[str] = []
        for media in answer.media:
            figure = figures_by_id.get(media.media_id)
            if media.kind == "video_segment":
                if figure is None or not figure.uri:
                    continue
                uri = figure.uri
                if "?" not in uri:
                    t_start = media.t_start if media.t_start is not None else 0.0
                    uri = f"{uri}?t={int(t_start)}s"
                videos.append(uri)
                continue
            if figure is None or not figure.storage_key:
                continue
            try:
                url = await presign(self.file_manager, figure.storage_key, expiry=self.presign_expiry)
            except MediaUnavailable as exc:
                self.logger.warning("Presign skipped for media %s: %s", media.media_id, exc)
                continue
            images.append(url)
        return images, videos
