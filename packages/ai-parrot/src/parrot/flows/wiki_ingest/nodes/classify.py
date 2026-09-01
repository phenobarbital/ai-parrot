"""Summary-first classification node (FEAT-481, spec Module 7, contract §15).

The first **semantic** node in the pipeline — the only LLM call is
``strong_client.invoke(output_type=Classification)`` (rule #7: use the
Fireflies summary first). Deterministic Python decides *whether* a second,
transcript-informed classification pass is needed (§15.4's fallback
ladder) and what ``processing_mode``/``review_required`` follow from the
result (§15.3/§15.5) — the LLM never decides those bookkeeping fields
itself.

**Scope boundary.** This node does not move raw files or write pages: a
low-confidence result is reported via
:attr:`ClassificationResult.review_required` +
:attr:`ClassificationResult.review_item` (a draft for Module 12's Review
Queue writer) — the bundle simply stays at whichever ``Raw/Processed/``
location Module 3 already placed it (``Uncategorized/`` by default,
spec Module 3 sequencing note); a resolved classification's
client/project relocation (``raw_bundle.reclassify_move``) is the
orchestrator's job (spec Module 6), not this node's.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient

from ..models import Classification
from .fetch_gate import GatedMeeting

logger = logging.getLogger(__name__)

#: §15.4 — meeting content that always triggers the transcript fallback,
#: regardless of the summary-only confidence.
_HIGH_IMPACT_KEYWORDS = (
    "hr",
    "human resources",
    "legal",
    "security",
    "compliance",
    "financial",
    "finance",
    "lawsuit",
    "termination",
    "salary",
    "harassment",
)

_SYSTEM_PROMPT = (
    "You are classifying a meeting for a governed knowledge base. Identify the "
    "primary client/project, additional related projects, key people, products, "
    "concepts, and your confidence in this classification. Match existing "
    "projects/entities/concepts before proposing new ones (rule #6). Never "
    "invent a project or client when evidence is insufficient — set the field "
    "to null/empty and let confidence reflect the uncertainty (rule #12)."
)


class ExistingContext(BaseModel):
    """§15.1 — existing-knowledge context read before classification.

    Every field is optional/best-effort: this node's own dependency
    chain (spec Module 7 depends on Modules 3/5) does not require the
    GraphIndex retrieval plane (spec Module 13) to exist yet — when it
    is available, the orchestrator passes richer candidate lists here.

    Attributes:
        index_summary: A short excerpt/summary of ``Wiki/index.md``.
        overview_summary: A short excerpt/summary of ``Wiki/overview.md``.
        candidate_projects: Known project names/aliases to match against.
        candidate_clients: Known client/company names/aliases.
        candidate_people: Known person names/aliases.
        candidate_products: Known product names/aliases.
        candidate_concepts: Known concept names/aliases.
    """

    index_summary: str = ""
    overview_summary: str = ""
    candidate_projects: list[str] = Field(default_factory=list)
    candidate_clients: list[str] = Field(default_factory=list)
    candidate_people: list[str] = Field(default_factory=list)
    candidate_products: list[str] = Field(default_factory=list)
    candidate_concepts: list[str] = Field(default_factory=list)


class ReviewItemDraft(BaseModel):
    """A draft §26 Review Queue entry — written by Module 12, not here."""

    review_type: str = "classification"
    source_id: str
    issue: str
    evidence: str


class ClassificationResult(BaseModel):
    """The classify node's full result.

    Attributes:
        classification: The validated :class:`Classification`.
        processing_mode: ``"summary-only"`` or ``"summary-and-transcript"``
            (§15.4) — set here, never guessed by the LLM.
        transcript_read: Whether the transcript fallback fired.
        review_required: ``True`` when confidence is still ``"low"`` after
            the fallback (§15.5).
        review_item: A draft Review Queue entry when ``review_required``.
    """

    classification: Classification
    processing_mode: str
    transcript_read: bool
    review_required: bool
    review_item: ReviewItemDraft | None = None


def _deterministic_fallback_trigger(meeting: GatedMeeting, *, force_transcript: bool) -> bool:
    """§15.4 — the fallback triggers decidable without an LLM call.

    Args:
        meeting: The :class:`~.fetch_gate.GatedMeeting` being classified.
        force_transcript: ``True`` when the user explicitly requested
            full-transcript processing.

    Returns:
        ``True`` if a deterministic trigger fires (high-impact content or
        an explicit request) — confidence-based triggers are checked
        separately, after the first LLM pass.
    """
    if force_transcript:
        return True
    haystack = meeting.title.lower()
    return any(keyword in haystack for keyword in _HIGH_IMPACT_KEYWORDS)


def _build_prompt(meeting: GatedMeeting, context: ExistingContext, *, include_transcript: bool) -> str:
    """Build the classification prompt (summary-first, rule #7).

    Args:
        meeting: The meeting being classified.
        context: The §15.1 existing-knowledge context.
        include_transcript: Append the full transcript (§15.4 fallback).

    Returns:
        The prompt text.
    """
    parts = [
        f"Meeting title: {meeting.title}",
        f"Meeting date: {meeting.meeting_date}",
        f"Participants: {', '.join(meeting.participants) or 'Unknown'}",
        "",
        "Existing Wiki index summary:",
        context.index_summary or "(none)",
        "",
        "Existing Wiki overview summary:",
        context.overview_summary or "(none)",
        "",
        f"Known projects: {', '.join(context.candidate_projects) or '(none)'}",
        f"Known clients: {', '.join(context.candidate_clients) or '(none)'}",
        f"Known people: {', '.join(context.candidate_people) or '(none)'}",
        f"Known products: {', '.join(context.candidate_products) or '(none)'}",
        f"Known concepts: {', '.join(context.candidate_concepts) or '(none)'}",
        "",
        "Fireflies summary:",
        meeting.summary_text or "(no summary available)",
    ]
    if include_transcript:
        parts += ["", "Full transcript:", meeting.transcript_text or "(no transcript available)"]
    return "\n".join(parts)


async def run_classify(
    strong_client: AbstractClient,
    meeting: GatedMeeting,
    *,
    context: ExistingContext | None = None,
    force_transcript: bool = False,
) -> ClassificationResult:
    """Classify one meeting: summary-first, confidence, transcript fallback.

    Args:
        strong_client: The strong-tier :class:`AbstractClient` (spec G7 —
            reconciliation/ambiguous-classification tier).
        meeting: The :class:`~.fetch_gate.GatedMeeting` to classify
            (``outcome == "fetch"``).
        context: The §15.1 existing-knowledge context (best-effort —
            defaults to empty when the GraphIndex retrieval plane, spec
            Module 13, is not yet available).
        force_transcript: User-requested full-transcript processing
            (§15.4 — "the user explicitly requests full-transcript
            processing").

    Returns:
        The :class:`ClassificationResult`.
    """
    context = context or ExistingContext()

    deterministic_trigger = _deterministic_fallback_trigger(meeting, force_transcript=force_transcript)

    prompt = _build_prompt(meeting, context, include_transcript=deterministic_trigger)
    result = await strong_client.invoke(
        prompt, output_type=Classification, system_prompt=_SYSTEM_PROMPT, temperature=0.0
    )
    classification: Classification = result.output
    transcript_read = deterministic_trigger

    if not transcript_read and classification.confidence in ("medium", "low"):
        # §15.4 — confidence-triggered fallback: reclassify with the
        # transcript included.
        prompt = _build_prompt(meeting, context, include_transcript=True)
        result = await strong_client.invoke(
            prompt, output_type=Classification, system_prompt=_SYSTEM_PROMPT, temperature=0.0
        )
        classification = result.output
        transcript_read = True

    processing_mode = "summary-and-transcript" if transcript_read else "summary-only"

    review_required = classification.confidence == "low"
    review_item = None
    if review_required:
        review_item = ReviewItemDraft(
            source_id=meeting.source_id,
            issue=f"Classification remained low-confidence for {meeting.title!r} after transcript fallback",
            evidence=classification.transcript_fallback_reason or "Insufficient evidence to resolve project/client",
        )

    return ClassificationResult(
        classification=classification,
        processing_mode=processing_mode,
        transcript_read=transcript_read,
        review_required=review_required,
        review_item=review_item,
    )
