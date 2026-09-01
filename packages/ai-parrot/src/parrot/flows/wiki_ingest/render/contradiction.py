"""Deterministic §22 contradiction page renderer (FEAT-481, spec Module 11).

Reproduces the contract's §22 template verbatim. Contradictions are
first-class objects — this renderer never resolves anything by recency
(§22 rule 9); ``status`` stays ``"open"`` and ``## Resolution`` stays
unresolved unless the caller explicitly supplies a resolution backed by
evidence (§22 rule 10).
"""

from __future__ import annotations

from pydantic import BaseModel

from ..models import ContradictionFrontmatter


class ContradictionClaim(BaseModel):
    """One side of a contradiction (§22 ``## Claim A``/``## Claim B``).

    Attributes:
        text: The claim text.
        source: Wikilink target of the supporting source page.
        date: ``YYYY-MM-DD`` the claim was made.
    """

    text: str
    source: str
    date: str


class ContradictionState(BaseModel):
    """The contradiction page's typed state (§22 sections).

    Attributes:
        claim_a: The first (typically earlier/existing) claim.
        claim_b: The second (typically new/incoming) claim.
        why_conflict: Clear explanation of the incompatibility.
        impact: What decisions/requirements/tasks/reporting are affected.
        resolution_needed: What evidence or decision is required.
        resolution: Left empty until explicitly resolved (§22 rule 10) —
            never set from recency alone.
    """

    claim_a: ContradictionClaim
    claim_b: ContradictionClaim
    why_conflict: str
    impact: str
    resolution_needed: str
    resolution: str = ""


def _frontmatter_block(frontmatter: ContradictionFrontmatter) -> str:
    import yaml

    data = frontmatter.model_dump(exclude_none=False)
    block = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{block}---"


def render_contradiction_page(frontmatter: ContradictionFrontmatter, state: ContradictionState) -> str:
    """Render the exact §22 contradiction page.

    Args:
        frontmatter: The validated §10.5 frontmatter.
        state: The contradiction's typed :class:`ContradictionState`.

    Returns:
        The full Markdown page (frontmatter + body).
    """
    resolution_body = state.resolution or "Leave unresolved until supported."

    body = f"""
# {frontmatter.title}

## Claim A
- {state.claim_a.text}
- Source: [[{state.claim_a.source}]]
- Date: {state.claim_a.date}

## Claim B
- {state.claim_b.text}
- Source: [[{state.claim_b.source}]]
- Date: {state.claim_b.date}

## Why They Conflict
{state.why_conflict}

## Impact
{state.impact}

## Resolution Needed
{state.resolution_needed}

## Resolution
{resolution_body}
""".strip("\n")

    return f"{_frontmatter_block(frontmatter)}\n\n{body}\n"
