"""Concept resolver — match-before-create, material concepts only
(FEAT-481, spec Module 10, contract §21).

Reuses :func:`~.entities.find_matching_page` (the match-before-create
search is identical for entities and concepts, differing only in the
vault folder searched) — never creates a page for "every noun" (§21):
the strong-tier client's ``materially_relevant`` verdict gates creation.
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient
from parrot.tools.obsidian import ObsidianToolkit

from ..models import ConceptFrontmatter
from ..naming import now_iso, title_case_name
from ..render.concept import ConceptState, render_concept_page
from ..render.project import _parse_section
from .entities import find_matching_page

logger = logging.getLogger(__name__)

#: §4 — where concept pages live.
_CONCEPTS_FOLDER = "Wiki/Concepts"

_SYSTEM_PROMPT = (
    "You are drafting/updating a concept page for a governed knowledge base "
    "(contract §21). Only create/update a concept page when the idea is "
    "discussed materially, reused across sources, important to understanding "
    "a project, or likely to support future queries — set materially_relevant "
    "to false for a passing mention or 'every noun'. Ground the definition and "
    "significance in what the meeting actually supports (rule #12)."
)


class ConceptExtraction(BaseModel):
    """The strong-tier client's typed §21 content proposal.

    Attributes:
        materially_relevant: ``False`` when this concept is not material
            to the source (§21) — the caller must not create/update a page.
        definition: A source-grounded description.
        why_it_matters: Operational/technical/strategic significance.
        application_note: This meeting's usage note, if any.
        related_concepts: ``(concept_name, relationship)`` pairs.
    """

    materially_relevant: bool
    definition: str
    why_it_matters: str
    application_note: str | None = None
    related_concepts: list[tuple[str, str]] = Field(default_factory=list)


class ConceptResolveResult(BaseModel):
    """Result of resolving one concept candidate.

    Attributes:
        action: ``"created"``, ``"updated"``, or ``"not_created"`` (not
            material — §21).
        frontmatter: Set for ``"created"``/``"updated"``.
        content: The rendered page, for ``"created"``/``"updated"``.
        vault_path: The concept page's vault path.
    """

    action: Literal["created", "updated", "not_created"]
    frontmatter: ConceptFrontmatter | None = None
    content: str | None = None
    vault_path: str | None = None


async def run_concept_resolve(
    strong_client: AbstractClient,
    toolkit: ObsidianToolkit,
    candidate_name: str,
    *,
    project_name: str | None,
    meeting_source_link: str,
    meeting_summary: str,
) -> ConceptResolveResult:
    """Resolve (match/create/update) one concept page (§21).

    Args:
        strong_client: The strong-tier :class:`AbstractClient`.
        toolkit: This subsystem's own :class:`ObsidianToolkit`.
        candidate_name: The candidate concept name.
        project_name: The current meeting's primary project, for the
            ``## Application`` section (``None`` if unresolved).
        meeting_source_link: Wikilink target of the meeting source page.
        meeting_summary: The Fireflies summary text (extraction input).

    Returns:
        The :class:`ConceptResolveResult`.
    """
    match = await find_matching_page(toolkit, candidate_name, folder=_CONCEPTS_FOLDER)

    existing_state: ConceptState | None = None
    if match is not None:
        existing_note = await toolkit.read_note(match.path)
        existing_state = _parse_concept_body(existing_note["content"])

    prompt = "\n".join(
        [
            f"Concept name: {candidate_name}",
            f"Meeting: {meeting_source_link}",
            f"Fireflies summary: {meeting_summary}",
            f"Existing definition: {existing_state.definition if existing_state else '(new concept)'}",
        ]
    )
    result = await strong_client.invoke(
        prompt, output_type=ConceptExtraction, system_prompt=_SYSTEM_PROMPT, temperature=0.0
    )
    extraction: ConceptExtraction = result.output

    if not extraction.materially_relevant:
        return ConceptResolveResult(action="not_created")

    canonical_name = match.canonical_name if match else title_case_name(candidate_name)
    now = now_iso()

    application = list(existing_state.application) if existing_state else []
    if project_name and extraction.application_note and (project_name, extraction.application_note) not in application:
        application.append((project_name, extraction.application_note))

    related_concepts = list(existing_state.related_concepts) if existing_state else []
    for rel in extraction.related_concepts:
        if rel not in related_concepts:
            related_concepts.append(rel)

    sources = list(existing_state.sources) if existing_state else []
    if meeting_source_link not in sources:
        sources.append(meeting_source_link)

    state = ConceptState(
        definition=extraction.definition or (existing_state.definition if existing_state else ""),
        why_it_matters=extraction.why_it_matters or (existing_state.why_it_matters if existing_state else ""),
        application=application,
        related_concepts=related_concepts,
        tensions=list(existing_state.tensions) if existing_state else [],
        sources=sources,
        human_notes=existing_state.human_notes if existing_state else "",
    )

    frontmatter = ConceptFrontmatter(
        id=f"concept:{canonical_name.lower().replace(' ', '-')}",
        title=canonical_name,
        aliases=match.aliases if match else [],
        projects=[project_name] if project_name else [],
        source_pages=sources,
        related_concepts=[name for name, _ in related_concepts],
        created=now,
        updated=now,
    )
    content = render_concept_page(frontmatter, state)
    vault_path = f"{_CONCEPTS_FOLDER}/{canonical_name}.md"

    return ConceptResolveResult(
        action="updated" if match else "created", frontmatter=frontmatter, content=content, vault_path=vault_path
    )


def _parse_concept_body(content: str) -> ConceptState:
    """Best-effort round-trip of our own §21 render format."""
    body = content.split("---", 2)[-1] if content.startswith("---") else content
    definition = _parse_section(body, "Definition")
    if definition.lower() == "not established":
        definition = ""
    why_it_matters = _parse_section(body, "Why It Matters")
    if why_it_matters.lower() == "not established":
        why_it_matters = ""
    human_notes = _parse_section(body, "Human Notes")
    if human_notes == "(none)":
        human_notes = ""

    application = []
    for line in _parse_section(body, "Application").splitlines():
        m = re.match(r"^- \[\[Projects/[^|]+\|([^\]]+)\]\] - (.*)$", line)
        if m:
            application.append((m.group(1), m.group(2)))

    related_concepts = []
    for line in _parse_section(body, "Related Concepts").splitlines():
        m = re.match(r"^- \[\[Wiki/Concepts/[^|]+\|([^\]]+)\]\] - (.*)$", line)
        if m:
            related_concepts.append((m.group(1), m.group(2)))

    tensions = [
        line[2:].strip()
        for line in _parse_section(body, "Tensions or Contradictions").splitlines()
        if line.startswith("- ") and line[2:].strip().lower() != "none identified"
    ]

    sources = []
    for line in _parse_section(body, "Sources").splitlines():
        m = re.match(r"^- \[\[([^\]]+)\]\]$", line)
        if m:
            sources.append(m.group(1))

    return ConceptState(
        definition=definition,
        why_it_matters=why_it_matters,
        application=application,
        related_concepts=related_concepts,
        tensions=tensions,
        sources=sources,
        human_notes=human_notes,
    )
