"""Deterministic §21 concept page renderer (FEAT-481, spec Module 10).

Reproduces the contract's §21 template verbatim. Concept pages are
created only for materially discussed, reused, or retrieval-relevant
ideas — never for "every noun" (§21) — the materiality decision itself
lives in ``nodes/concepts.py``, not here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import ConceptFrontmatter


class ConceptState(BaseModel):
    """The concept page's typed state (§21 sections).

    Attributes:
        definition: A source-grounded description.
        why_it_matters: Operational/technical/strategic significance.
        application: ``(project_name, usage_note)`` pairs.
        related_concepts: ``(concept_name, relationship)`` pairs.
        tensions: Unresolved interpretations or contradiction links.
        sources: Meeting source page links.
        human_notes: Preserved verbatim across updates.
    """

    definition: str = ""
    why_it_matters: str = ""
    application: list[tuple[str, str]] = Field(default_factory=list)
    related_concepts: list[tuple[str, str]] = Field(default_factory=list)
    tensions: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    human_notes: str = ""


def _bullets(items: list[str], *, empty_placeholder: str) -> str:
    if not items:
        return f"- {empty_placeholder}"
    return "\n".join(f"- {item}" for item in items)


def _application(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "- None identified"
    return "\n".join(f"- [[Projects/{name}/{name}|{name}]] - {note}" for name, note in rows)


def _related_concepts(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "- None identified"
    return "\n".join(f"- [[Wiki/Concepts/{name}|{name}]] - {rel}" for name, rel in rows)


def _sources(sources: list[str]) -> str:
    if not sources:
        return "- None identified"
    return "\n".join(f"- [[{s}]]" for s in sources)


def _frontmatter_block(frontmatter: ConceptFrontmatter) -> str:
    import yaml

    data = frontmatter.model_dump(exclude_none=False)
    block = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{block}---"


def render_concept_page(frontmatter: ConceptFrontmatter, state: ConceptState) -> str:
    """Render the exact §21 concept page.

    Args:
        frontmatter: The validated §10.4 frontmatter.
        state: The concept's typed :class:`ConceptState`.

    Returns:
        The full Markdown page (frontmatter + body).
    """
    body = f"""
# {frontmatter.title}

## Definition
{state.definition or "Not established"}

## Why It Matters
{state.why_it_matters or "Not established"}

## Application
{_application(state.application)}

## Related Concepts
{_related_concepts(state.related_concepts)}

## Tensions or Contradictions
{_bullets(state.tensions, empty_placeholder="None identified")}

## Sources
{_sources(state.sources)}

## Human Notes
{state.human_notes or "(none)"}
""".strip("\n")

    return f"{_frontmatter_block(frontmatter)}\n\n{body}\n"
