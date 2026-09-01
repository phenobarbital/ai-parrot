"""Entity resolver — match-before-create (FEAT-481, spec Module 10,
contract §20).

Searches existing entity pages (filenames, then ``title``/``id``/
``aliases`` via the vault toolkit's ``search_notes`` — GraphIndex
retrieval, spec Module 13, is used when the caller supplies richer
candidates, since Module 10 does not depend on Module 13) before ever
proposing a new page (rule #6 — match existing knowledge before creating
new knowledge). Materiality and content are the strong-tier client's
judgment call; the LLM never emits page markdown (§3.1) — only
:mod:`~parrot.flows.wiki_ingest.render.entity` does.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from parrot.clients.base import AbstractClient
from parrot.tools.obsidian import ObsidianToolkit

from ..models import EntityFrontmatter
from ..naming import now_iso, title_case_name
from ..render.entity import EntityState, render_entity_page
from ..render.project import SourcedClaim, _parse_section

logger = logging.getLogger(__name__)

#: §4 — entity type to its vault folder.
_ENTITY_FOLDERS: dict[str, str] = {
    "person": "Wiki/Entities/People",
    "company": "Wiki/Entities/Companies",
    "product": "Wiki/Entities/Products",
}

_SYSTEM_PROMPT = (
    "You are drafting/updating an entity page for a governed knowledge base "
    "(contract §20). Only include roles, characteristics, and relationships "
    "explicitly supported by the meeting. Never infer a personal detail, job "
    "title, ownership, or organizational relationship that the source does not "
    "state (§20). Use 'Unknown'/'Not established'/'Requires review' when "
    "evidence is insufficient (rule #12)."
)


def _normalize(name: str) -> str:
    """Lowercase, alnum-only normalization for name comparison."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


class PageMatch(BaseModel):
    """A matched existing page (entity or concept)."""

    path: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)


async def find_matching_page(
    toolkit: ObsidianToolkit,
    candidate_name: str,
    *,
    folder: str,
) -> PageMatch | None:
    """§20/§21 rule 1-3 — match an existing page before creating one.

    Checks, in order: (1) an exact filename match under ``folder``, then
    (2) a ``search_notes`` hit under ``folder`` whose ``title``/``id``/
    ``aliases`` match the candidate (spelling/abbreviation/former-name
    variants included, via normalized comparison).

    Args:
        toolkit: This subsystem's own :class:`ObsidianToolkit`.
        candidate_name: The name to match.
        folder: The vault folder to search (entity type folder or
            ``"Wiki/Concepts"``).

    Returns:
        The :class:`PageMatch`, or ``None`` if nothing matches.
    """
    normalized_candidate = _normalize(candidate_name)

    try:
        listing = await toolkit.list_notes(folder=folder, recursive=False)
    except FileNotFoundError:
        # The folder does not exist yet on a fresh vault — nothing to match.
        listing = {"notes": []}
    for note in listing.get("notes", []):
        stem = Path(note["path"]).stem
        if _normalize(stem) == normalized_candidate:
            return PageMatch(path=note["path"], canonical_name=stem)

    search_result = await toolkit.search_notes(candidate_name, limit=20)
    for hit in search_result.get("hits", []):
        path = hit.get("path", "")
        if not path.startswith(folder):
            continue
        note = await toolkit.read_note(path)
        frontmatter = note.get("frontmatter", {}) or {}
        title = frontmatter.get("title", Path(path).stem)
        aliases = frontmatter.get("aliases", []) or []
        candidates = {_normalize(title), *[_normalize(a) for a in aliases]}
        if normalized_candidate in candidates:
            return PageMatch(path=path, canonical_name=title, aliases=list(aliases))

    return None


class EntityExtraction(BaseModel):
    """The strong-tier client's typed §20 content proposal.

    Attributes:
        materially_relevant: ``False`` when this entity is not material
            to the source — the caller must not create/update a page.
        summary: What this entity is and why it matters.
        known_roles: Supported facts (source citation added by Python).
        relationship_note: This meeting's project-relationship note, if
            any (``None`` when not applicable).
        related_entities: ``(entity_name, relationship)`` pairs.
        open_questions: Unresolved details.
    """

    materially_relevant: bool
    summary: str
    known_roles: list[str] = Field(default_factory=list)
    relationship_note: str | None = None
    related_entities: list[tuple[str, str]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class EntityResolveResult(BaseModel):
    """Result of resolving one entity candidate.

    Attributes:
        action: ``"created"``, ``"updated"``, or ``"not_created"`` (not
            material to this source).
        frontmatter: Set for ``"created"``/``"updated"``.
        content: The rendered page, for ``"created"``/``"updated"``.
        vault_path: The entity page's vault path.
    """

    action: Literal["created", "updated", "not_created"]
    frontmatter: EntityFrontmatter | None = None
    content: str | None = None
    vault_path: str | None = None


async def run_entity_resolve(
    strong_client: AbstractClient,
    toolkit: ObsidianToolkit,
    candidate_name: str,
    entity_type: Literal["person", "company", "product"],
    *,
    project_name: str | None,
    meeting_source_link: str,
    meeting_summary: str,
) -> EntityResolveResult:
    """Resolve (match/create/update) one entity page (§20).

    Args:
        strong_client: The strong-tier :class:`AbstractClient`.
        toolkit: This subsystem's own :class:`ObsidianToolkit`.
        candidate_name: The candidate entity name.
        entity_type: ``"person"``, ``"company"``, or ``"product"``.
        project_name: The current meeting's primary project, for the
            ``## Project Relationships`` section (``None`` if unresolved).
        meeting_source_link: Wikilink target of the meeting source page.
        meeting_summary: The Fireflies summary text (extraction input).

    Returns:
        The :class:`EntityResolveResult`.
    """
    folder = _ENTITY_FOLDERS[entity_type]
    match = await find_matching_page(toolkit, candidate_name, folder=folder)

    existing_state: EntityState | None = None
    if match is not None:
        existing_note = await toolkit.read_note(match.path)
        existing_state = _parse_entity_body(existing_note["content"])

    prompt = "\n".join(
        [
            f"Entity name: {candidate_name} ({entity_type})",
            f"Meeting: {meeting_source_link}",
            f"Fireflies summary: {meeting_summary}",
            f"Existing summary: {existing_state.summary if existing_state else '(new entity)'}",
        ]
    )
    result = await strong_client.invoke(
        prompt, output_type=EntityExtraction, system_prompt=_SYSTEM_PROMPT, temperature=0.0
    )
    extraction: EntityExtraction = result.output

    if not extraction.materially_relevant:
        return EntityResolveResult(action="not_created")

    canonical_name = match.canonical_name if match else title_case_name(candidate_name)
    now = now_iso()

    known_roles = list(existing_state.known_roles) if existing_state else []
    for role in extraction.known_roles:
        if role not in [c.text for c in known_roles]:
            known_roles.append(SourcedClaim(text=role, source=meeting_source_link))

    project_relationships = list(existing_state.project_relationships) if existing_state else []
    if (
        project_name
        and extraction.relationship_note
        and (project_name, extraction.relationship_note) not in project_relationships
    ):
        project_relationships.append((project_name, extraction.relationship_note))

    related_entities = list(existing_state.related_entities) if existing_state else []
    for rel in extraction.related_entities:
        if rel not in related_entities:
            related_entities.append(rel)

    open_questions = list(existing_state.open_questions) if existing_state else []
    for q in extraction.open_questions:
        if q not in open_questions:
            open_questions.append(q)

    sources = list(existing_state.sources) if existing_state else []
    if meeting_source_link not in sources:
        sources.append(meeting_source_link)

    state = EntityState(
        summary=extraction.summary or (existing_state.summary if existing_state else ""),
        known_roles=known_roles,
        project_relationships=project_relationships,
        related_entities=related_entities,
        open_questions=open_questions,
        sources=sources,
        human_notes=existing_state.human_notes if existing_state else "",
    )

    frontmatter = EntityFrontmatter(
        id=f"{entity_type}:{canonical_name.lower().replace(' ', '-')}",
        type=entity_type,
        title=canonical_name,
        aliases=match.aliases if match else [],
        projects=[project_name] if project_name else [],
        source_pages=sources,
        created=now,
        updated=now,
    )
    content = render_entity_page(frontmatter, state)
    vault_path = f"{folder}/{canonical_name}.md"

    return EntityResolveResult(
        action="updated" if match else "created", frontmatter=frontmatter, content=content, vault_path=vault_path
    )


def _parse_entity_body(content: str) -> EntityState:
    """Best-effort round-trip of our own §20 render format.

    Args:
        content: The full page markdown (frontmatter + body).

    Returns:
        The parsed :class:`EntityState` (empty fields where a section is
        not present or holds only a placeholder).
    """
    body = content.split("---", 2)[-1] if content.startswith("---") else content
    summary = _parse_section(body, "Summary")
    if summary.lower() == "not established":
        summary = ""
    human_notes = _parse_section(body, "Human Notes")
    if human_notes == "(none)":
        human_notes = ""

    known_roles = []
    for line in _parse_section(body, "Known Roles or Characteristics").splitlines():
        m = re.match(r"^- (.*) — \[\[(.*)\]\]$", line)
        if m:
            known_roles.append(SourcedClaim(text=m.group(1), source=m.group(2)))

    project_relationships = []
    for line in _parse_section(body, "Project Relationships").splitlines():
        m = re.match(r"^- \[\[Projects/[^|]+\|([^\]]+)\]\] - (.*)$", line)
        if m:
            project_relationships.append((m.group(1), m.group(2)))

    related_entities = []
    for line in _parse_section(body, "Related Entities").splitlines():
        m = re.match(r"^- \[\[([^\]]+)\]\] - (.*)$", line)
        if m:
            related_entities.append((m.group(1), m.group(2)))

    open_questions = [
        line[2:].strip()
        for line in _parse_section(body, "Open Questions or Ambiguities").splitlines()
        if line.startswith("- ") and line[2:].strip().lower() not in {"none identified", "unknown"}
    ]

    sources = []
    for line in _parse_section(body, "Sources").splitlines():
        m = re.match(r"^- \[\[([^\]]+)\]\]$", line)
        if m:
            sources.append(m.group(1))

    return EntityState(
        summary=summary,
        known_roles=known_roles,
        project_relationships=project_relationships,
        related_entities=related_entities,
        open_questions=open_questions,
        sources=sources,
        human_notes=human_notes,
    )
