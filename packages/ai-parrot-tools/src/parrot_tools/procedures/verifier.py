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

_STEP_NUM_RE = re.compile(r"\b(?:step|paso)\s*#?\s*(\d{1,3})\b", re.I)
# Any number followed by a unit-like word suffix (e.g. "45 psi", "12 N·m", "20 volts") — deliberately
# NOT a fixed unit whitelist (that only ever covers units someone remembered to enumerate; the review
# finding this replaces showed a hallucinated ft-lb/psi/°C value slipping through unexamined). Any
# match is checked against ``allowed_values`` below, so widening this pattern only widens what gets
# *checked*, never what gets silently allowed.
_UNIT_VALUE_RE = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*°?([a-zA-Z][a-zA-Z·]{0,9})\b")
# A fully bare number with no unit at all ("torque it to 45") — the other gap the same finding raised.
_BARE_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
# Ordinary connector words that can immediately follow a number in plain prose ("step 3 at 30 N·m") —
# never real units, so a number+word match against one of these is not a value claim at all; it falls
# through to the bare-number check for the digits alone instead of being (mis)treated as a unit.
_UNIT_STOPWORDS = frozenset(
    {
        "at",
        "is",
        "are",
        "was",
        "were",
        "be",
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "in",
        "on",
        "of",
        "for",
        "with",
        "then",
        "before",
        "after",
        "than",
        "steps",
        "step",
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "en",
        "y",
        "o",
        "con",
        "para",
        "por",
        "es",
        "son",
        "al",
        "un",
        "una",
        "unos",
        "unas",
    }
)

# Word-form step references ("step three" / "paso tres", "the third step" / "el tercer paso") — English
# and Spanish (agent.py's system prompt answers in either language), 1-20 (manuals rarely exceed that
# many steps; anything higher is still caught by the digit form above).
_CARDINAL_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
}
_ORDINAL_WORDS: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
    "primero": 1,
    "primer": 1,
    "segundo": 2,
    "tercero": 3,
    "tercer": 3,
    "cuarto": 4,
    "quinto": 5,
    "sexto": 6,
    "septimo": 7,
    "séptimo": 7,
    "octavo": 8,
    "noveno": 9,
    "decimo": 10,
    "décimo": 10,
}


def _word_alternation(words: dict[str, int]) -> str:
    """Longest word first — regex alternation is first-match, not longest-match (prefix-shadowing lesson)."""
    return "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))


_STEP_WORD_AFTER_RE = re.compile(rf"\b(?:step|paso)\s+({_word_alternation(_CARDINAL_WORDS)})\b", re.I)
_STEP_WORD_BEFORE_RE = re.compile(rf"\b({_word_alternation(_ORDINAL_WORDS)})\s+(?:step|paso)\b", re.I)


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
        """Drop prose that names a step reference or value (with or without a unit) absent from the assembly.

        Default-deny, not a fixed allowlist of units: every number found in the prose — digit-form step
        references, word-form step references (English/Spanish, "step three"/"the third step"), a number
        with any unit-like suffix, or a fully bare number with no unit at all — is checked against what
        the assembly actually released. Anything not recognized drops the whole prose (never just the
        offending phrase), matching this module's "never fill, only record/drop" guarantee (R2).
        """
        allowed_orders = {str(step.order) for step in assembled.steps}
        allowed_values: set[str] = set()
        allowed_numbers: set[str] = set(allowed_orders)
        for step in assembled.steps:
            if step.torque:
                value = normalize_whitespace(step.torque).casefold()
                allowed_values.add(value)
                allowed_numbers.update(re.findall(r"\d+(?:[.,]\d+)?", value))
            if step.duration_minutes is not None:
                value = normalize_whitespace(f"{step.duration_minutes} min").casefold()
                allowed_values.add(value)
                allowed_numbers.add(str(step.duration_minutes))
            for part_id in step.part_ids:
                allowed_values.add(normalize_whitespace(part_id).casefold())

        hits: list[str] = []
        consumed: list[tuple[int, int]] = []

        for match in _STEP_NUM_RE.finditer(prose):
            if match.group(1) not in allowed_orders:
                hits.append(match.group(0))
            consumed.append(match.span())
        for match in _STEP_WORD_AFTER_RE.finditer(prose):
            if str(_CARDINAL_WORDS[match.group(1).lower()]) not in allowed_orders:
                hits.append(match.group(0))
            consumed.append(match.span())
        for match in _STEP_WORD_BEFORE_RE.finditer(prose):
            if str(_ORDINAL_WORDS[match.group(1).lower()]) not in allowed_orders:
                hits.append(match.group(0))
            consumed.append(match.span())
        for match in _UNIT_VALUE_RE.finditer(prose):
            if match.group(2).lower() in _UNIT_STOPWORDS:
                continue  # not a unit at all — an ordinary word follows the number in plain prose
            if normalize_whitespace(match.group(0)).casefold() not in allowed_values:
                hits.append(match.group(0))
            consumed.append(match.span())
        for match in _BARE_NUMBER_RE.finditer(prose):
            span = match.span()
            if any(start <= span[0] and span[1] <= end for start, end in consumed):
                continue  # already examined above as part of a step or unit-value reference
            if match.group(0) not in allowed_numbers:
                hits.append(match.group(0))

        if hits:
            return "", hits
        return prose, []
