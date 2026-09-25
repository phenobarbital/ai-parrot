"""Blocking completeness + evidence verification for procedure answers (FEAT-601 M10, R2).

Unlike the contracts ``CitationVerifier`` (which drops unsupported claims), a missing required step,
an unsupported critical field or an unresolvable citation BLOCKS release: ``answer_kind="incomplete"``.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional, Protocol

from pydantic import BaseModel, Field

from parrot.knowledge.common.validation import normalize_whitespace
from parrot.knowledge.manuals.models import ManualVersion, ProcedureAnswer, ProcedureAnswerKind, ProcedureCitation
from parrot_tools.procedures.assembly import AssembledProcedure

logger = logging.getLogger(__name__)

_STEP_NUM_RE = re.compile(r"\b(?:step|paso)\s+(\d{1,3})\b", re.I)
_VALUE_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:n·m|nm|n-m|min|mm|kg)\b", re.I)


class EvidenceReader(Protocol):
    """Reads one archived section of a manual revision (satisfied by ``ManualLibrary``, TASK-3713)."""

    async def load_section(self, manual_id: str, version_n: int, node_id: str) -> Optional[str]: ...


class RejectedCitation(BaseModel):
    """One citation that did not resolve, and why."""

    manual_id: str
    node_id: str
    reason: str


class VerificationOutcome(BaseModel):
    """The answer that may be released, plus everything that blocked or was dropped."""

    answer: ProcedureAnswer
    rejected: list[RejectedCitation] = Field(default_factory=list)
    blocked_reason: str | None = None
    dropped_claims: list[str] = Field(default_factory=list)


class ProcedureVerifier:
    """Verify an assembled procedure against the archived revision; block on any gap.

    Args:
        catalog: The tenant-bound manual catalog (kept for parity with contracts; card lookups only).
        evidence: An :class:`EvidenceReader` (e.g. ``ManualLibrary``) over the archived revisions.
        allowed_revision: The only revision citations may come from.
    """

    def __init__(self, *, catalog: Any, evidence: Any, allowed_revision: ManualVersion) -> None:
        self.catalog = catalog
        self.evidence = evidence
        self.allowed_revision = allowed_revision
        self.logger = logging.getLogger(__name__)

    async def verify(
        self, assembled: AssembledProcedure, *, draft_prose: str, kind: ProcedureAnswerKind, pattern: str | None
    ) -> VerificationOutcome:
        """Return a released answer or an ``incomplete`` one with no steps.

        Raises:
            ValueError: When ``kind`` is not one this gate handles (procedure/step/prerequisites).
        """
        if kind not in ("procedure", "step", "prerequisites"):
            raise ValueError(f"{kind!r} is not verified here")
        rejected = [r for r in [await self._resolve(c) for c in assembled.citations] if r is not None]
        if assembled.missing_required or assembled.unsupported_fields or rejected:
            reason = self._reason(assembled, rejected)
            self.logger.warning("procedure answer blocked: %s", reason)
            answer = ProcedureAnswer(
                answer_kind="incomplete",
                answer="",
                reason=reason,
                steps=[],
                citations=[],
                procedure=assembled.procedure,
                manual_revision=self.allowed_revision.revision,
                pattern=pattern,
            )
            return VerificationOutcome(answer=answer, rejected=rejected, blocked_reason=reason)
        prose, dropped = self._check_prose(draft_prose, assembled)
        answer = self._release(assembled, kind=kind, prose=prose, pattern=pattern)
        return VerificationOutcome(answer=answer, rejected=rejected, dropped_claims=dropped)

    def _release(
        self, assembled: AssembledProcedure, *, kind: ProcedureAnswerKind, prose: str, pattern: str | None
    ) -> ProcedureAnswer:
        """Build the released ``ProcedureAnswer`` for ``kind`` from a complete assembly."""
        common: dict[str, Any] = {
            "answer": prose,
            "procedure": assembled.procedure,
            "citations": assembled.citations,
            "pattern": pattern,
            "manual_revision": self.allowed_revision.revision,
        }
        if kind == "procedure":
            return ProcedureAnswer(
                answer_kind="procedure",
                steps=assembled.steps,
                prerequisites=assembled.prerequisites,
                hazards=assembled.hazards,
                media=assembled.media,
                tips=assembled.tips,
                **common,
            )
        if kind == "step":
            return ProcedureAnswer(
                answer_kind="step",
                steps=assembled.steps,
                hazards=assembled.hazards,
                media=assembled.media,
                tips=assembled.tips,
                **common,
            )
        return ProcedureAnswer(
            answer_kind="prerequisites",
            prerequisites=assembled.prerequisites,
            hazards=assembled.hazards,
            **common,
        )

    async def _resolve(self, citation: ProcedureCitation) -> Optional[RejectedCitation]:
        """Return ``None`` when the citation resolves verbatim, else the rejection in the archived section."""

        def reject(reason: str) -> RejectedCitation:
            return RejectedCitation(manual_id=citation.manual_id, node_id=citation.node_id, reason=reason)

        if citation.version_n != self.allowed_revision.n:
            return reject("citation version does not match the allowed revision")
        if citation.source_sha256 and not self.allowed_revision.source_sha256.startswith(citation.source_sha256[:16]):
            return reject("citation source hash does not match")
        quote = normalize_whitespace(citation.quote)
        if not quote:
            return reject("empty quotes never prove evidence")
        body = await self.evidence.load_section(citation.manual_id, citation.version_n, citation.node_id)
        if body is None:
            return reject(f"node {citation.node_id!r} is not in this revision")
        if quote not in normalize_whitespace(body):
            return reject("quote is not verbatim in the archived body")
        return None

    @staticmethod
    def _reason(assembled: AssembledProcedure, rejected: list[RejectedCitation]) -> str:
        """Human-readable reason naming every missing step/field and rejected node."""
        parts = []
        if assembled.missing_required:
            parts.append("missing: " + ", ".join(assembled.missing_required))
        if assembled.unsupported_fields:
            parts.append("unsupported: " + ", ".join(assembled.unsupported_fields))
        if rejected:
            parts.append("rejected: " + ", ".join(r.node_id for r in rejected))
        return "; ".join(parts)

    @staticmethod
    def _check_prose(prose: str, assembled: AssembledProcedure) -> tuple[str, list[str]]:
        """Drop prose that names a step number or value absent from the assembly."""
        allowed_orders = {str(step.order) for step in assembled.steps}
        allowed_values: set[str] = set()
        for step in assembled.steps:
            if step.torque:
                allowed_values.add(normalize_whitespace(step.torque).casefold())
            if step.duration_minutes is not None:
                allowed_values.add(normalize_whitespace(f"{step.duration_minutes} min").casefold())
            for part_id in step.part_ids:
                allowed_values.add(normalize_whitespace(part_id).casefold())

        hits: list[str] = []
        for match in _STEP_NUM_RE.finditer(prose):
            if match.group(1) not in allowed_orders:
                hits.append(match.group(0))
        for match in _VALUE_RE.finditer(prose):
            if normalize_whitespace(match.group(0)).casefold() not in allowed_values:
                hits.append(match.group(0))

        if hits:
            return "", hits
        return prose, []
