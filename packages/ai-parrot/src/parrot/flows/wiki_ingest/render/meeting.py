"""Deterministic §17 canonical meeting source page renderer (FEAT-481,
spec Module 8).

Reproduces the contract's §17 template **verbatim** — exact heading text,
section order, and the Action Items table columns. The LLM (spec Module
8's ``nodes/meeting_page.py``) supplies only field *content* via a
validated Pydantic model; this module places that content into the fixed
structure and never asks an LLM to emit markdown.
"""

from __future__ import annotations

from ..models import ActionItem, MeetingExtraction, MeetingSourceFrontmatter


def _frontmatter_block(frontmatter: MeetingSourceFrontmatter) -> str:
    """Render the YAML frontmatter block from the §10.1 model.

    Args:
        frontmatter: The validated :class:`MeetingSourceFrontmatter`.

    Returns:
        The ``---\\n...\\n---`` frontmatter block.
    """
    import yaml

    data = frontmatter.model_dump(exclude_none=False)
    block = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{block}---"


def _bullet_list(items: list[str], *, empty_placeholder: str) -> str:
    """Render a Markdown bullet list, or a single no-fabrication placeholder line.

    Args:
        items: The bullet texts (already grounded content — the LLM
            never emits an empty-evidence bullet, rule #12).
        empty_placeholder: Rendered as a single ``- <placeholder>`` line
            when ``items`` is empty (never silently omitted, never
            fabricated).

    Returns:
        The rendered bullet list.
    """
    if not items:
        return f"- {empty_placeholder}"
    return "\n".join(f"- {item}" for item in items)


def render_participants(participants: list[tuple[str, str]]) -> str:
    """§17 ``## Participants`` — one wikilink + role per line.

    Args:
        participants: ``(name, role)`` pairs. ``role`` is rendered as
            given — callers pass ``"Unknown"`` (rule #12) when the role
            cannot be established from the listing/transcript.

    Returns:
        The rendered bullet list.
    """
    if not participants:
        return "- Unknown"
    return "\n".join(f"- [[Wiki/Entities/People/{name}|{name}]] - {role}" for name, role in participants)


def render_projects_and_clients(projects: list[str], clients: list[str]) -> str:
    """§17 ``## Projects and Clients``.

    Args:
        projects: Project names (rendered as
            ``[[Projects/<name>/<name>]]``, matching §10.1's
            ``primary_project`` format).
        clients: Client/company names (rendered as
            ``[[Wiki/Entities/Companies/<name>|<name>]]``).

    Returns:
        The rendered bullet list.
    """
    lines = [f"[[Projects/{p}/{p}]]" for p in projects]
    lines += [f"[[Wiki/Entities/Companies/{c}|{c}]]" for c in clients]
    return _bullet_list(lines, empty_placeholder="Unknown")


def render_concepts(concepts: list[str]) -> str:
    """§17 ``## Concepts and Connections``.

    Args:
        concepts: Concept names identified during classification (§15).

    Returns:
        The rendered bullet list.
    """
    lines = [f"[[Wiki/Concepts/{c}|{c}]] - discussed in this meeting." for c in concepts]
    return _bullet_list(lines, empty_placeholder="None identified")


def render_contradictions(contradictions: list[str]) -> str:
    """§17 ``## Contradictions`` (Module 11 links appended later, if any).

    Args:
        contradictions: Contradiction page titles already linked to this
            meeting (empty until Module 11 runs).

    Returns:
        The rendered bullet list.
    """
    lines = [f"[[Wiki/Contradictions/{c}|{c}]] - unresolved conflict." for c in contradictions]
    return _bullet_list(lines, empty_placeholder="None identified")


def render_action_items_table(action_items: list[ActionItem]) -> str:
    """§17 ``## Action Items`` table — columns verbatim.

    Args:
        action_items: :class:`~..models.ActionItem` instances.

    Returns:
        The rendered Markdown table (header + rows).
    """
    header = "| Action | Owner | Due date | Status | Source confidence |\n| --- | --- | --- | --- | --- |"
    if not action_items:
        return f"{header}\n| None identified | Unknown | Unknown | Open | Low |"
    rows = [f"| {a.action} | {a.owner} | {a.due_date} | {a.status} | {a.source_confidence} |" for a in action_items]
    return "\n".join([header, *rows])


def render_meeting_page(
    frontmatter: MeetingSourceFrontmatter,
    extraction: MeetingExtraction,
    *,
    executive_summary: str,
    purpose: str,
    participants: list[tuple[str, str]],
    projects: list[str],
    clients: list[str],
    concepts: list[str],
    contradictions: list[str] | None = None,
    verified_quotes: list[str] | None = None,
) -> str:
    """Render the exact §17 canonical meeting source page.

    ``## Verified Quotes`` is included only when ``verified_quotes`` is
    non-``None`` — i.e., only when the transcript was actually read
    (``frontmatter.processing_mode == "summary-and-transcript"``); never
    include a direct quote unless the transcript was read and verified.

    Args:
        frontmatter: The validated §10.1 frontmatter.
        extraction: The structured :class:`MeetingExtraction`
            (decisions/requirements/action_items/risks/open_questions).
        executive_summary: A concise synthesis of the meeting (LLM-supplied
            content, Python-placed).
        purpose: Why the meeting occurred (LLM-supplied content).
        participants: ``(name, role)`` pairs.
        projects: Project names for ``## Projects and Clients``.
        clients: Client/company names for ``## Projects and Clients``.
        concepts: Concept names for ``## Concepts and Connections``.
        contradictions: Contradiction titles linked to this meeting
            (Module 11 — empty/``None`` before contradiction detection
            has run).
        verified_quotes: Verbatim quotes, present ONLY when the
            transcript was read. ``None`` omits the section's content
            (still renders the heading — §17 always has the section, its
            body notes the transcript was not read).

    Returns:
        The full Markdown page (frontmatter + body).
    """
    contradictions = contradictions or []

    if verified_quotes is not None:
        quotes_body = _bullet_list(verified_quotes, empty_placeholder="No quotes selected.")
    else:
        quotes_body = "Not applicable — transcript was not read for this meeting."

    body = f"""
# {frontmatter.title}

## Executive Summary
{executive_summary}

## Purpose
{purpose}

## Participants
{render_participants(participants)}

## Projects and Clients
{render_projects_and_clients(projects, clients)}

## Key Discussion
{_bullet_list(extraction.decisions + extraction.requirements, empty_placeholder="Not established")}

## Decisions
{_bullet_list(extraction.decisions, empty_placeholder="None identified")}

## Requirements
{_bullet_list(extraction.requirements, empty_placeholder="None identified")}

## Action Items
{render_action_items_table(extraction.action_items)}

## Risks and Blockers
{_bullet_list(extraction.risks, empty_placeholder="None identified")}

## Open Questions
{_bullet_list(extraction.open_questions, empty_placeholder="None identified")}

## Concepts and Connections
{render_concepts(concepts)}

## Contradictions
{render_contradictions(contradictions)}

## Verified Quotes
{quotes_body}

## Source Provenance
- Raw summary: `{frontmatter.raw_summary}`
- Raw transcript: `{frontmatter.raw_transcript}`
- Processing mode: {frontmatter.processing_mode}
- Classification confidence: {frontmatter.classification_confidence}
""".strip("\n")

    return f"{_frontmatter_block(frontmatter)}\n\n{body}\n"
