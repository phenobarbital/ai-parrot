"""Pydantic v2 contracts for the ``dev-flow`` topology (FEAT-412).

The dev-flow is the SDD-oriented sibling of the operations-oriented
``parrot.flows.dev_loop``: instead of a log-driven bug triage it starts
from a developer's *natural-language* request (``enhancement`` /
``new_feature``) or from an already-written SDD document (``feature`` —
the existing :class:`~parrot.flows.dev_loop.models.FeatureBrief`).

This module defines only the three new contracts (spec §2 Data Models):

* :class:`DevRequestBrief` — natural-language intake.
* :data:`DevFlowBrief` — the discriminated ``kind`` union that ``dev_intake``
  accepts (``DevRequestBrief | FeatureBrief``).
* :class:`IdeationOutput` — the ``sdd-ideation`` subagent's final JSON
  contract.

Everything else (dev-agent pool specs, judge panels, planner/QA outputs)
is imported from ``dev_loop.models`` — dev-flow reuses those wholesale.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from parrot.flows.dev_loop.models import (
    DevAgentSpec,
    FeatureBrief,
    JudgePanelConfig,
)

__all__ = [
    "DevFlowBrief",
    "DevRequestBrief",
    "DevRequestKind",
    "IdeationOutput",
    "parse_dev_brief",
]


# The two natural-language intents. Chosen explicitly by the user in the
# UI — dev-flow deliberately has NO LLM intent classification (spec §8).
DevRequestKind = Literal["enhancement", "new_feature"]


class DevRequestBrief(BaseModel):
    """Natural-language intake for the dev-flow (enhancement / new feature).

    Unlike :class:`~parrot.flows.dev_loop.models.FeatureBrief`, there is no
    SDD document yet — that is precisely what ``IdeationNode`` produces via
    the ``sdd-ideation`` subagent:

    * ``new_feature`` → a full ``sdd/proposals/<slug>.brainstorm.md``
      (options analysis + recommendation).
    * ``enhancement`` → a light ``sdd/proposals/<slug>.proposal.md``
      (scope, rationale, impact — no options analysis).

    Consequently this model carries NO document validators; ``title`` is the
    slug source and ``description`` is the request itself.
    """

    kind: DevRequestKind = Field(
        ...,
        description=(
            "User-selected intent. 'new_feature' ⇒ brainstorm document, "
            "'enhancement' ⇒ light proposal document. Never inferred by an "
            "LLM (spec §8: the user picks the intent in the UI)."
        ),
    )
    title: str = Field(
        ...,
        min_length=1,
        description=(
            "Short human name for the request. Slug source for the "
            "``sdd/proposals/<slug>.*.md`` document path."
        ),
    )
    description: str = Field(
        ...,
        min_length=1,
        description="The natural-language request driving this run.",
    )
    context: str = Field(
        default="",
        description="Optional extra context, links, or constraints.",
    )
    jira_issue_key: str | None = Field(
        default=None,
        description=(
            "Optional Jira issue key. Like feature-mode, dev-flow never "
            "creates a Jira issue; when set, downstream nodes only link/"
            "transition/comment on the existing ticket."
        ),
    )
    dev_agents: list[DevAgentSpec] | None = Field(
        default=None,
        description=(
            "Optional explicit dev-agent pool, passed through to the "
            "``FeatureBrief`` that ``IdeationNode`` emits. When unset, "
            "``PlannerNode`` derives the pool from the first task wave."
        ),
    )
    judge_panel: JudgePanelConfig | None = Field(
        default=None,
        description=(
            "Optional QA judge-panel override, passed through to the "
            "``FeatureBrief`` that ``IdeationNode`` emits."
        ),
    )


# Discriminated brief union on ``kind`` — mirrors ``dev_loop.models.Brief``.
# Three admissible kinds: "enhancement" / "new_feature" (DevRequestBrief)
# and "feature" (FeatureBrief, the document-based FEAT-378 intake).
DevFlowBrief = Annotated[
    DevRequestBrief | FeatureBrief, Field(discriminator="kind")
]


def parse_dev_brief(data: dict[str, Any]) -> DevRequestBrief | FeatureBrief:
    """Parse a raw brief mapping into a :class:`DevRequestBrief` or ``FeatureBrief``.

    Loader shim around the :data:`DevFlowBrief` discriminated union, mirroring
    ``dev_loop.models.parse_brief``: routes on the ``kind`` field
    (``"feature"`` → :class:`~parrot.flows.dev_loop.models.FeatureBrief`,
    ``"enhancement"``/``"new_feature"`` → :class:`DevRequestBrief`).

    Unlike ``parse_brief``, there is no legacy default kind to preserve: the
    dev-flow requires an explicit intent, so a missing/unknown ``kind`` is a
    validation error rather than a silent fallback.

    Args:
        data: Raw brief mapping, e.g. decoded from a JSON prompt or an
            HTML form payload.

    Returns:
        A validated ``DevRequestBrief`` or ``FeatureBrief`` instance.

    Raises:
        ValueError: If ``kind`` is absent or is not one of the three
            admissible dev-flow kinds.
        pydantic.ValidationError: If the mapping fails validation against
            the resolved model.
    """
    kind = data.get("kind")
    if kind == "feature":
        return FeatureBrief(**data)
    if kind in ("enhancement", "new_feature"):
        return DevRequestBrief(**data)
    raise ValueError(
        "dev-flow brief requires an explicit kind of 'enhancement', "
        f"'new_feature' or 'feature'; got {kind!r}"
    )


class IdeationOutput(BaseModel):
    """Contract for the ``sdd-ideation`` subagent's single final JSON object.

    The subagent writes (or resumes/extends) the intent's SDD document,
    commits it to ``base_branch``, and reports the result here.
    ``IdeationNode`` fails fast when ``committed`` is ``False`` — an
    uncommitted document is invisible to the worktree ``sdd-planner``
    creates later (spec §7 Known Risks).
    """

    document_path: str = Field(
        ...,
        description=(
            "Resolved path of the written document: "
            "``sdd/proposals/<slug>.brainstorm.md`` (new_feature) or "
            "``sdd/proposals/<slug>.proposal.md`` (enhancement)."
        ),
    )
    document_kind: Literal["brainstorm", "proposal"] = Field(
        ...,
        description=(
            "'brainstorm' for the new_feature mode, 'proposal' for the "
            "enhancement mode. Fed straight into "
            "``FeatureBrief.document_kind``."
        ),
    )
    slug: str = Field(..., description="Slug derived from the request title.")
    resumed_existing: bool = Field(
        default=False,
        description=(
            "True when the target document already existed and was "
            "resumed/extended in place (never overwritten, never "
            "``-2``-suffixed — spec §8 existing-document policy)."
        ),
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description=(
            "Unresolved ``[ ]`` Open Questions from this round. Non-empty ⇒ "
            "``IdeationNode`` opens ONE ``open_questions`` gate carrying all "
            "of them."
        ),
    )
    summary: str = Field(
        default="",
        description="Short human summary of what the document proposes.",
    )
    committed: bool = Field(
        default=False,
        description=(
            "Whether the document was committed to ``base_branch``. False ⇒ "
            "``IdeationNode`` fails the run (the planner's worktree would "
            "not see the document)."
        ),
    )
