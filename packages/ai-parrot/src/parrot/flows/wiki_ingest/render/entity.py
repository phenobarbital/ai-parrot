"""Deterministic §20 entity page renderer (FEAT-481, spec Module 10).

Reproduces the contract's §20 template verbatim. Never infers personal
details, job titles, ownership, or organizational relationships not
supported by sources (§20 closing rule).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import EntityFrontmatter
from .project import SourcedClaim


class EntityState(BaseModel):
    """The entity page's typed state (§20 sections).

    Attributes:
        summary: What this entity is and why it matters.
        known_roles: Supported facts, each linked to its source (§10 rule
            #10 — never fabricated, rule #12).
        project_relationships: ``(project_name, role_or_relationship)``.
        related_entities: ``(entity_name, relationship)``.
        open_questions: Unresolved details about this entity.
        sources: Meeting source page links.
        human_notes: Preserved verbatim across updates.
    """

    summary: str = ""
    known_roles: list[SourcedClaim] = Field(default_factory=list)
    project_relationships: list[tuple[str, str]] = Field(default_factory=list)
    related_entities: list[tuple[str, str]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    human_notes: str = ""


def _bullets(items: list[str], *, empty_placeholder: str) -> str:
    if not items:
        return f"- {empty_placeholder}"
    return "\n".join(f"- {item}" for item in items)


def _known_roles(claims: list[SourcedClaim]) -> str:
    if not claims:
        return "- Not established"
    return "\n".join(f"- {c.text} — [[{c.source}]]" for c in claims)


def _project_relationships(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "- None identified"
    return "\n".join(f"- [[Projects/{name}/{name}|{name}]] - {rel}" for name, rel in rows)


def _related_entities(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "- None identified"
    return "\n".join(f"- [[{name}]] - {rel}" for name, rel in rows)


def _sources(sources: list[str]) -> str:
    if not sources:
        return "- None identified"
    return "\n".join(f"- [[{s}]]" for s in sources)


def _frontmatter_block(frontmatter: EntityFrontmatter) -> str:
    import yaml

    data = frontmatter.model_dump(exclude_none=False)
    block = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{block}---"


def render_entity_page(frontmatter: EntityFrontmatter, state: EntityState) -> str:
    """Render the exact §20 entity page.

    Args:
        frontmatter: The validated §10.3 frontmatter.
        state: The entity's typed :class:`EntityState`.

    Returns:
        The full Markdown page (frontmatter + body).
    """
    body = f"""
# {frontmatter.title}

## Summary
{state.summary or "Not established"}

## Known Roles or Characteristics
{_known_roles(state.known_roles)}

## Project Relationships
{_project_relationships(state.project_relationships)}

## Related Entities
{_related_entities(state.related_entities)}

## Open Questions or Ambiguities
{_bullets(state.open_questions, empty_placeholder="None identified")}

## Sources
{_sources(state.sources)}

## Human Notes
{state.human_notes or "(none)"}
""".strip("\n")

    return f"{_frontmatter_block(frontmatter)}\n\n{body}\n"
