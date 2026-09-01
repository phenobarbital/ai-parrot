"""Project page reconciler (§19, diff-guarded) + new-project creation (§16)
(FEAT-481, spec Module 9 — the highest-risk node).

**Typed section-merge, never free-form regeneration** (§3.1): the
existing project page is parsed into a structured
:class:`~..render.project.ProjectState`
(:func:`~..render.project.parse_project_page`, since we control our own
render format exactly), the strong-tier client proposes typed updates to
the mutable sections only, and the **Q2 diff-guard**
(:func:`_apply_diff_guard`) deterministically verifies — in Python, not
by trusting the LLM — that no currently-tracked, source-linked claim
silently disappeared. A dropped claim is reinserted, never trusted away.

**Chronological supersession (§19 rule 10).** A late-arriving meeting
OLDER than the project's current ``last_meeting`` never reaches the LLM
merge at all — it is applied as historical context only
(:func:`_chronological_historical_update`), so it structurally cannot
overwrite newer current-state fields.

**Locked pages (§9/§19 rule 9).** The caller passes ``locked`` (read from
the page's raw frontmatter dict — the typed :class:`ProjectFrontmatter`
schema, frozen in Module 5, does not itself carry this ad-hoc flag) — a
locked page is never edited; the update is queued instead.
"""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient

from ..models import Classification, MeetingExtraction, ProjectFrontmatter
from ..naming import now_iso, title_case_name
from ..render.project import (
    ProjectState,
    SourcedClaim,
    parse_project_page,
    render_project_page,
)
from .classify import ReviewItemDraft
from .fetch_gate import GatedMeeting

logger = logging.getLogger(__name__)

_NEW_PROJECT_SYSTEM_PROMPT = (
    "Decide whether this meeting justifies creating a NEW project page (contract "
    "§16). Create a project ONLY for an ongoing body of work with a distinct "
    "objective, scope, stakeholder group, deliverable, implementation, or decision "
    "stream. Do NOT justify a project for: a passing topic, a single isolated "
    "question, a company mention without active work, a concept (belongs under "
    "Concepts), or a product (belongs under Products)."
)

_RECONCILE_SYSTEM_PROMPT = (
    "You are reconciling a project's canonical current-state page with a new "
    "meeting (contract §19). Merge new SUPPORTED information into the correct "
    "section; update statuses instead of duplicating rows; mark explicitly "
    "superseded decisions as superseded (never delete them); every requirement, "
    "decision, risk, or workstream you list must be something this meeting "
    "actually supports. Never invent a decision, owner, or date — reuse "
    "'Unknown'/'Not established'/'Requires review' when evidence is insufficient "
    "(rule #12). You are proposing sections only — the caller decides what is "
    "kept from the prior state."
)


class NewProjectJustification(BaseModel):
    """§16 new-project creation decision."""

    justified: bool
    reason: str


class ProjectUpdateProposal(BaseModel):
    """The strong-tier client's typed §19 section-merge proposal.

    A **proposal**, not the final state — :func:`run_project_reconcile`
    applies the Q2 diff-guard against it before it becomes the page's new
    :class:`~..render.project.ProjectState`.
    """

    executive_summary: str
    current_status: str
    objectives: list[str] = Field(default_factory=list)
    scope_in: list[str] = Field(default_factory=list)
    scope_out: list[str] = Field(default_factory=list)
    current_requirements: list[SourcedClaim] = Field(default_factory=list)
    current_decisions: list[SourcedClaim] = Field(default_factory=list)
    risks: list[SourcedClaim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    timeline: list[str] = Field(default_factory=list)
    change_summary: str


class ProjectReconcileResult(BaseModel):
    """Result of one project reconcile/create operation.

    Attributes:
        action: ``"created"`` (§16 new project), ``"updated"`` (full
            merge), ``"chronological_supersede_only"`` (§19 rule 10 — an
            older late-arriving meeting, historical-context only),
            ``"not_created"`` (§16 negative criteria — correctly did
            nothing), or ``"queued"`` (locked page — not edited).
        frontmatter: The project's frontmatter, when a page was
            created/updated.
        content: The rendered page, when a page was created/updated.
        vault_path: ``Projects/<Name>/<Name>.md``, when applicable.
        diff_guard_violations: Claim texts the Q2 diff-guard reinserted
            because the proposal silently dropped a still-live-sourced
            claim — feeds
            :attr:`~..validation.ValidationContext.diff_guard_violations`.
        review_item: A draft Review Queue entry (``locked-page-update``
            when queued).
    """

    action: Literal["created", "updated", "chronological_supersede_only", "not_created", "queued"]
    frontmatter: ProjectFrontmatter | None = None
    content: str | None = None
    vault_path: str | None = None
    diff_guard_violations: list[str] = Field(default_factory=list)
    review_item: ReviewItemDraft | None = None


def _apply_diff_guard(
    existing_claims: list[SourcedClaim], proposed_claims: list[SourcedClaim]
) -> tuple[list[SourcedClaim], list[str]]:
    """Q2 — never drop a claim while a live source still supports it.

    A claim is identified by its exact ``text``. Anything the proposal
    kept (verbatim, or with ``superseded`` flipped) passes through
    unchanged; anything the existing state had that vanished from the
    proposal is reinserted, not trusted away.

    Args:
        existing_claims: The parsed current page's claims for one section.
        proposed_claims: The LLM's proposed claims for the same section.

    Returns:
        ``(merged, violations)`` — ``violations`` lists the claim texts
        that had to be reinserted (feeds §34 validation).
    """
    proposed_texts = {c.text for c in proposed_claims}
    violations: list[str] = []
    merged = list(proposed_claims)
    for claim in existing_claims:
        if claim.text not in proposed_texts:
            violations.append(claim.text)
            merged.append(claim)
    return merged, violations


def _merge_unique(existing: list[str], proposed: list[str]) -> list[str]:
    """Union-preserve: keep every existing item, append new proposed ones."""
    merged = list(existing)
    for item in proposed:
        if item not in merged:
            merged.append(item)
    return merged


async def should_create_project(
    strong_client: AbstractClient,
    meeting: GatedMeeting,
    meeting_extraction: MeetingExtraction,
    classification: Classification,
) -> NewProjectJustification:
    """§16 — decide whether this meeting justifies a NEW project page.

    Args:
        strong_client: The strong-tier :class:`AbstractClient`.
        meeting: The meeting under consideration.
        meeting_extraction: The Module 8 :class:`MeetingExtraction`.
        classification: The Module 7 :class:`Classification`.

    Returns:
        The :class:`NewProjectJustification`.
    """
    prompt = "\n".join(
        [
            f"Meeting title: {meeting.title}",
            f"Candidate project name: {classification.primary_project or 'Unknown'}",
            f"Decisions: {'; '.join(meeting_extraction.decisions) or '(none)'}",
            f"Requirements: {'; '.join(meeting_extraction.requirements) or '(none)'}",
            f"Additional projects mentioned: {', '.join(classification.additional_projects) or '(none)'}",
        ]
    )
    result = await strong_client.invoke(
        prompt, output_type=NewProjectJustification, system_prompt=_NEW_PROJECT_SYSTEM_PROMPT, temperature=0.0
    )
    return result.output


def _fresh_state_from_extraction(
    meeting_extraction: MeetingExtraction,
    classification: Classification,
    *,
    meeting_source_link: str,
) -> ProjectState:
    """Seed a brand-new project's :class:`ProjectState` from one meeting.

    Args:
        meeting_extraction: The Module 8 :class:`MeetingExtraction`.
        classification: The Module 7 :class:`Classification`.
        meeting_source_link: Wikilink target of the meeting source page.

    Returns:
        The seeded :class:`ProjectState`.
    """
    return ProjectState(
        current_requirements=[
            SourcedClaim(text=r, source=meeting_source_link) for r in meeting_extraction.requirements
        ],
        current_decisions=[SourcedClaim(text=d, source=meeting_source_link) for d in meeting_extraction.decisions],
        risks=[SourcedClaim(text=r, source=meeting_source_link) for r in meeting_extraction.risks],
        open_questions=list(meeting_extraction.open_questions),
        clients=[classification.primary_client] if classification.primary_client else [],
        products=list(classification.products),
        concepts=list(classification.concepts),
        recent_source_updates=[f"{meeting_source_link} - project created"],
    )


def _chronological_historical_update(
    state: ProjectState,
    *,
    meeting: GatedMeeting,
    meeting_source_link: str,
) -> ProjectState:
    """§19 rule 10 — integrate an older, late-arriving meeting as
    historical context only. Never touches current-state fields.

    Args:
        state: The parsed current :class:`ProjectState`.
        meeting: The (older) meeting being integrated.
        meeting_source_link: Wikilink target of its meeting source page.

    Returns:
        A copy of ``state`` with one additional
        ``recent_source_updates`` entry — nothing else changed.
    """
    updated = state.model_copy(deep=True)
    updated.recent_source_updates = _merge_unique(
        updated.recent_source_updates,
        [f"{meeting.meeting_date} - [[{meeting_source_link}]] - integrated as historical context (older meeting)"],
    )
    return updated


async def run_project_reconcile(
    strong_client: AbstractClient,
    *,
    existing_content: str | None,
    existing_frontmatter: ProjectFrontmatter | None,
    locked: bool,
    project_name: str,
    meeting: GatedMeeting,
    meeting_extraction: MeetingExtraction,
    meeting_source_link: str,
    classification: Classification,
) -> ProjectReconcileResult:
    """Reconcile (or create) one project page for one meeting (§16/§19).

    Args:
        strong_client: The strong-tier :class:`AbstractClient` (spec G7).
        existing_content: The project page's current full Markdown, or
            ``None`` when the project does not exist yet.
        existing_frontmatter: The project's current frontmatter, or
            ``None`` for a new project.
        locked: Whether the existing page is ``locked: true`` (read from
            the raw frontmatter by the caller — §9/§19 rule 9).
        project_name: The (candidate or existing) project's Title-Case
            name.
        meeting: The meeting driving this reconcile.
        meeting_extraction: The Module 8 :class:`MeetingExtraction`.
        meeting_source_link: Wikilink target of the meeting source page.
        classification: The Module 7 :class:`Classification`.

    Returns:
        The :class:`ProjectReconcileResult`.
    """
    project_name = title_case_name(project_name)
    vault_path = f"Projects/{project_name}/{project_name}.md"
    now = now_iso()

    if existing_content is not None and locked:
        return ProjectReconcileResult(
            action="queued",
            review_item=ReviewItemDraft(
                review_type="locked-page-update",
                source_id=meeting.source_id,
                issue=f"{project_name} is locked; update from {meeting.title!r} requires human action",
                evidence=meeting_source_link,
            ),
        )

    if existing_content is None:
        justification = await should_create_project(strong_client, meeting, meeting_extraction, classification)
        if not justification.justified:
            return ProjectReconcileResult(action="not_created")

        state = _fresh_state_from_extraction(meeting_extraction, classification, meeting_source_link=meeting_source_link)
        frontmatter = ProjectFrontmatter(
            id=f"project:{project_name.lower().replace(' ', '-')}",
            title=project_name,
            status="active",
            clients=state.clients,
            people=[],
            products=state.products,
            concepts=state.concepts,
            source_pages=[meeting_source_link],
            last_meeting=meeting.meeting_date,
            created=now,
            updated=now,
        )
        content = render_project_page(frontmatter, state)
        return ProjectReconcileResult(action="created", frontmatter=frontmatter, content=content, vault_path=vault_path)

    existing_state = parse_project_page(existing_content)
    assert existing_frontmatter is not None  # existing_content implies a frontmatter was read alongside it

    last_meeting = existing_frontmatter.last_meeting
    is_older = last_meeting is not None and meeting.meeting_date < last_meeting
    if is_older:
        updated_state = _chronological_historical_update(
            existing_state, meeting=meeting, meeting_source_link=meeting_source_link
        )
        frontmatter = existing_frontmatter.model_copy(update={"updated": now})
        content = render_project_page(frontmatter, updated_state)
        return ProjectReconcileResult(
            action="chronological_supersede_only", frontmatter=frontmatter, content=content, vault_path=vault_path
        )

    prompt = "\n".join(
        [
            f"Project: {project_name}",
            f"Existing executive summary: {existing_state.executive_summary or '(none)'}",
            f"Existing current status: {existing_state.current_status or '(none)'}",
            f"Existing requirements: {[c.text for c in existing_state.current_requirements]}",
            f"Existing decisions: {[c.text for c in existing_state.current_decisions]}",
            f"Existing risks: {[c.text for c in existing_state.risks]}",
            f"Existing open questions: {existing_state.open_questions}",
            "",
            f"New meeting ({meeting.meeting_date}) source: [[{meeting_source_link}]]",
            f"New decisions: {meeting_extraction.decisions}",
            f"New requirements: {meeting_extraction.requirements}",
            f"New risks: {meeting_extraction.risks}",
            f"New open questions: {meeting_extraction.open_questions}",
        ]
    )
    result = await strong_client.invoke(
        prompt, output_type=ProjectUpdateProposal, system_prompt=_RECONCILE_SYSTEM_PROMPT, temperature=0.0
    )
    proposal: ProjectUpdateProposal = result.output

    merged_requirements, req_violations = _apply_diff_guard(
        existing_state.current_requirements, proposal.current_requirements
    )
    merged_decisions, dec_violations = _apply_diff_guard(existing_state.current_decisions, proposal.current_decisions)
    merged_risks, risk_violations = _apply_diff_guard(existing_state.risks, proposal.risks)

    updated_state = existing_state.model_copy(
        update={
            "executive_summary": proposal.executive_summary or existing_state.executive_summary,
            "current_status": proposal.current_status or existing_state.current_status,
            "objectives": _merge_unique(existing_state.objectives, proposal.objectives),
            "scope_in": _merge_unique(existing_state.scope_in, proposal.scope_in),
            "scope_out": _merge_unique(existing_state.scope_out, proposal.scope_out),
            "current_requirements": merged_requirements,
            "current_decisions": merged_decisions,
            "risks": merged_risks,
            "open_questions": _merge_unique(existing_state.open_questions, proposal.open_questions),
            "timeline": _merge_unique(existing_state.timeline, proposal.timeline),
            "clients": _merge_unique(
                existing_state.clients, [classification.primary_client] if classification.primary_client else []
            ),
            "products": _merge_unique(existing_state.products, classification.products),
            "concepts": _merge_unique(existing_state.concepts, classification.concepts),
            "recent_source_updates": _merge_unique(
                existing_state.recent_source_updates,
                [f"{meeting.meeting_date} - [[{meeting_source_link}]] - {proposal.change_summary}"],
            ),
        }
    )

    frontmatter = existing_frontmatter.model_copy(
        update={
            "last_meeting": meeting.meeting_date,
            "updated": now,
            "clients": updated_state.clients,
            "products": updated_state.products,
            "concepts": updated_state.concepts,
            "source_pages": _merge_unique(existing_frontmatter.source_pages, [meeting_source_link]),
        }
    )
    content = render_project_page(frontmatter, updated_state)

    return ProjectReconcileResult(
        action="updated",
        frontmatter=frontmatter,
        content=content,
        vault_path=vault_path,
        diff_guard_violations=[*req_violations, *dec_violations, *risk_violations],
    )
