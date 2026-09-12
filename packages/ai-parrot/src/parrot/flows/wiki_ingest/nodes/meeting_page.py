"""Canonical meeting source page extraction node (FEAT-481, spec Module 8,
contract §17).

Extracts typed fields with the **cheap tier** client
(``cheap_client.invoke(output_type=...)``) and hands them to
:mod:`~parrot.flows.wiki_ingest.render.meeting` for verbatim, deterministic
rendering (§3.1) — the LLM never emits page markdown.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal, cast

from pydantic import BaseModel

from parrot.clients.base import AbstractClient

from ..models import MeetingExtraction, MeetingSourceFrontmatter
from ..naming import meeting_source_filename, now_iso
from ..render.meeting import render_meeting_page
from .classify import ClassificationResult
from .fetch_gate import GatedMeeting

logger = logging.getLogger(__name__)

#: Placeholder used when classification could not resolve a project
#: (rule #12 — never fabricate; D2's self-membership invariant still
#: holds because "Unknown" then also appears in ``projects``).
_UNKNOWN_PROJECT = "Unknown"

_SYSTEM_PROMPT = (
    "You are extracting structured content for a canonical meeting page. "
    "Write a concise executive summary and purpose, plus decisions, "
    "requirements, action items (owner/due date/status/confidence), risks, "
    "open questions, and potential contradictions. Never invent a name, "
    "date, owner, or decision that is not supported by the source text — "
    "use 'Unknown', 'Not established', or 'Requires review' when evidence "
    "is insufficient (rule #12). Never include a direct quote here."
)


class MeetingPageExtraction(MeetingExtraction):
    """§17 extraction contract — extends :class:`MeetingExtraction` with
    the page's narrative fields (executive summary, purpose).

    A superset, not a replacement: every :class:`MeetingExtraction` field
    the spec names for this node's ``invoke()`` call (decisions,
    requirements, action_items, risks, open_questions,
    potential_contradictions) is inherited unchanged; this class only
    adds the two free-text fields the §17 template also needs that
    Module 5's frozen schema does not carry (Executive Summary, Purpose).
    """

    executive_summary: str
    purpose: str


class MeetingPageResult(BaseModel):
    """Result of rendering one canonical meeting source page.

    Attributes:
        frontmatter: The validated §10.1 frontmatter.
        filename: The §8.2 filename (meeting's original-tz date).
        content: The full rendered Markdown page.
        vault_path: ``Wiki/Sources/Meetings/<filename>``.
    """

    frontmatter: MeetingSourceFrontmatter
    filename: str
    content: str
    vault_path: str


def _project_and_client_names(classification_result: ClassificationResult) -> tuple[list[str], list[str], str]:
    """Resolve the frontmatter's ``primary_project``/``projects``/``clients``.

    Args:
        classification_result: The Module 7 :class:`ClassificationResult`.

    Returns:
        ``(projects, clients, primary_project_value)`` — ``projects``
        always contains ``primary_project_value`` (D2).
    """
    classification = classification_result.classification
    if classification.primary_project:
        primary = f"[[Projects/{classification.primary_project}/{classification.primary_project}]]"
        projects = [primary] + [f"[[Projects/{p}/{p}]]" for p in classification.additional_projects]
    else:
        primary = _UNKNOWN_PROJECT
        projects = [_UNKNOWN_PROJECT]

    clients = [classification.primary_client] if classification.primary_client else []
    return projects, clients, primary


async def run_meeting_page(
    cheap_client: AbstractClient,
    meeting: GatedMeeting,
    classification_result: ClassificationResult,
    *,
    raw_summary_path: str,
    raw_transcript_path: str,
    summary_sha256: str,
    transcript_sha256: str,
    meeting_date_local: str | None = None,
    contradictions: list[str] | None = None,
) -> MeetingPageResult:
    """Extract + render the canonical §17 meeting source page.

    Args:
        cheap_client: The cheap-tier :class:`AbstractClient` (spec G7 —
            bulk extraction, summary-first reads).
        meeting: The :class:`~.fetch_gate.GatedMeeting`
            (``outcome == "fetch"``).
        classification_result: The Module 7 :class:`ClassificationResult`.
        raw_summary_path: Plain relative path to the immutable raw summary
            (D1 — never a wikilink).
        raw_transcript_path: Plain relative path to the immutable raw
            transcript (D1).
        summary_sha256: The raw summary's SHA-256 (§14.2).
        transcript_sha256: The raw transcript's SHA-256 (§14.2).
        meeting_date_local: The meeting's date in its ORIGINAL timezone
            (§8.4) for the filename — defaults to ``meeting.meeting_date``
            when the caller has not resolved the original-tz date (e.g.
            no ``meeting_date_iso`` was available).
        contradictions: Bare titles of contradiction pages this meeting's
            own detection pass created/updated (Module 11) — linked into
            ``## Contradictions`` per contract §22 rule 6.

    Returns:
        The :class:`MeetingPageResult`.
    """
    transcript_read = classification_result.transcript_read
    prompt = _build_prompt(meeting, transcript_read=transcript_read)
    result = await cheap_client.invoke(
        prompt, output_type=MeetingPageExtraction, system_prompt=_SYSTEM_PROMPT, temperature=0.0
    )
    extraction: MeetingPageExtraction = result.output

    projects, clients, primary_project = _project_and_client_names(classification_result)
    classification = classification_result.classification

    now = now_iso()

    local_date = meeting_date_local or meeting.meeting_date
    filename = meeting_source_filename(
        meeting_date_local=date.fromisoformat(local_date),
        title=meeting.title,
        source_id=meeting.source_id,
    )

    frontmatter = MeetingSourceFrontmatter(
        id=f"source:{meeting.source_id}",
        title=meeting.title,
        source_id=meeting.source_id,
        meeting_date=meeting.meeting_date,
        processed_at=now,
        processing_mode=cast(
            'Literal["summary-only", "summary-and-transcript"]', classification_result.processing_mode
        ),
        classification_confidence=classification.confidence,
        review_required=classification_result.review_required,
        raw_summary=raw_summary_path,
        raw_transcript=raw_transcript_path,
        summary_sha256=summary_sha256,
        transcript_sha256=transcript_sha256,
        primary_project=primary_project,
        projects=projects,
        clients=clients,
        people=classification.people,
        products=classification.products,
        concepts=classification.concepts,
        created=now,
        updated=now,
    )

    participants = [(_display_name(p), "Unknown") for p in meeting.participants]
    verified_quotes: list[str] | None = [] if transcript_read else None

    content = render_meeting_page(
        frontmatter,
        extraction,
        executive_summary=extraction.executive_summary,
        purpose=extraction.purpose,
        participants=participants,
        projects=(
            [classification.primary_project] + classification.additional_projects
            if classification.primary_project
            else []
        ),
        clients=clients,
        concepts=classification.concepts,
        contradictions=contradictions,
        verified_quotes=verified_quotes,
    )

    return MeetingPageResult(
        frontmatter=frontmatter,
        filename=filename,
        content=content,
        vault_path=f"Wiki/Sources/Meetings/{filename}",
    )


def _display_name(email: str) -> str:
    """Best-effort human-readable name from a participant email.

    Entity resolution (spec Module 10) has not run yet at this pipeline
    step — this is a display fallback only, never persisted as a
    canonical entity name.

    Args:
        email: A participant's email address.

    Returns:
        The email's local-part, title-cased with separators replaced by
        spaces (e.g. ``"jane.doe@x.com"`` → ``"Jane Doe"``), or the raw
        email if it does not look like ``local@domain``.
    """
    local = email.split("@", 1)[0] if "@" in email else email
    return local.replace(".", " ").replace("_", " ").title()


def _build_prompt(meeting: GatedMeeting, *, transcript_read: bool) -> str:
    """Build the extraction prompt (summary always included; transcript
    only when it was actually read for this meeting).

    Args:
        meeting: The meeting being extracted.
        transcript_read: Whether the transcript-fallback fired for this
            meeting (spec Module 7).

    Returns:
        The prompt text.
    """
    parts = [
        f"Meeting title: {meeting.title}",
        f"Meeting date: {meeting.meeting_date}",
        "",
        "Fireflies summary:",
        meeting.summary_text or "(no summary available)",
    ]
    if transcript_read:
        parts += ["", "Full transcript:", meeting.transcript_text or "(no transcript available)"]
    return "\n".join(parts)
