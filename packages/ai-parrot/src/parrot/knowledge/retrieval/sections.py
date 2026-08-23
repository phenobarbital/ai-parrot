"""`SectionSelector` — derives which wiki sections a query needs (OQ-5).

Spec §6.1. Splitting is a **retrieval-time selection over addressable
sections**, not a generation-time page-splitting heuristic: a `WikiPage`
(TASK-2283) is a structured document, sections are the addressable unit.
This is where §4's `QueryClass` taxonomy pays off a second time — the
classifier supplies a selector, so a hot module never produces an unusable
8k-token page, because nobody ever asks for the whole page.

Note: `SectionKind` is NOT `parrot.knowledge.wiki.models.WikiPageCategory`
(FEAT-260's page-*type* taxonomy — SUMMARY/ENTITY/CONCEPT/COMPARISON/
OVERVIEW/SYNTHESIS/ANSWER/ARCHIVE). The two are different, orthogonal
taxonomies that coexist (spec §14.3) — do not conflate or "unify" them.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.classifier import QueryClass

logger = logging.getLogger(__name__)


class SectionKind(StrEnum):
    """Addressable sections of a `WikiPage` (spec §6.1)."""

    OVERVIEW = "overview"
    CONTRACTS = "contracts"
    RATIONALE = "rationale"
    USAGE = "usage"
    GOTCHAS = "gotchas"
    DEPENDENCIES = "dependencies"


#: `GOTCHAS` is a **filter** over material L0 already produces (RQ-4), not
#: new extraction: `CodeExtractor._DEFAULT_TAGS` (`extractors/code.py:29`)
#: already emits one `RATIONALE` node per tagged comment, carrying
#: `domain_tags["tag"]`. This partition is the single place that decides
#: which tags route to `GOTCHAS` vs `RATIONALE` — TASK-2283 imports it
#: rather than redefining it.
GOTCHA_TAGS: frozenset[str] = frozenset({"HACK", "TODO", "FIXME", "XXX"})
RATIONALE_TAGS: frozenset[str] = frozenset({"NOTE", "WHY"})


class SectionSelector(BaseModel):
    """Which `WikiSection`s a query needs, and how to fill them under budget.

    Attributes:
        include: Section kinds to fetch, in priority order.
        max_tokens_per_section: Per-section token cap.
        fill_order: Order to greedily fill sections in when the overall
            token budget is tight. Defaults to `include`'s order unless a
            `QueryClass` needs otherwise.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    include: tuple[SectionKind, ...]
    max_tokens_per_section: int = 1_200
    fill_order: tuple[SectionKind, ...]


#: Selector per `QueryClass` (spec §6.1's two stated mappings, plus a
#: documented, sensible default for the remaining classes). Kept as a plain
#: dict lookup — this is on the hot path (§4: the classifier must never be
#: the thing that costs latency) and must not grow logic.
_SELECTOR_BY_CLASS: dict[QueryClass, SectionSelector] = {
    # Spec §6.1, stated explicitly: "RATIONALE queries request
    # (RATIONALE, OVERVIEW)".
    QueryClass.RATIONALE: SectionSelector(
        include=(SectionKind.RATIONALE, SectionKind.OVERVIEW),
        fill_order=(SectionKind.RATIONALE, SectionKind.OVERVIEW),
    ),
    # Spec §6.1, stated explicitly: "GLOBAL_SUMMARY requests
    # (OVERVIEW, CONTRACTS, DEPENDENCIES)".
    QueryClass.GLOBAL_SUMMARY: SectionSelector(
        include=(SectionKind.OVERVIEW, SectionKind.CONTRACTS, SectionKind.DEPENDENCIES),
        fill_order=(SectionKind.OVERVIEW, SectionKind.CONTRACTS, SectionKind.DEPENDENCIES),
    ),
    # DIRECT_SYMBOL/LOCAL_FACT are served straight from L0 source (§5.1/§5.2)
    # and don't consume the wiki cache in v1, but a selector must still
    # exist for every class (no KeyError possible) — CONTRACTS is the
    # closest wiki analogue to "show me this symbol's public surface".
    QueryClass.DIRECT_SYMBOL: SectionSelector(
        include=(SectionKind.CONTRACTS,),
        fill_order=(SectionKind.CONTRACTS,),
    ),
    QueryClass.LOCAL_FACT: SectionSelector(
        include=(SectionKind.CONTRACTS, SectionKind.USAGE),
        fill_order=(SectionKind.CONTRACTS, SectionKind.USAGE),
    ),
    # RELATIONAL queries care about how a symbol is used across the graph.
    QueryClass.RELATIONAL: SectionSelector(
        include=(SectionKind.USAGE, SectionKind.CONTRACTS),
        fill_order=(SectionKind.USAGE, SectionKind.CONTRACTS),
    ),
    # COMPARATIVE needs both anchors' public surfaces plus any documented
    # rationale for why they differ.
    QueryClass.COMPARATIVE: SectionSelector(
        include=(SectionKind.CONTRACTS, SectionKind.RATIONALE),
        fill_order=(SectionKind.CONTRACTS, SectionKind.RATIONALE),
    ),
    # UNKNOWN gets the broadest, cheapest-to-fill overview — consistent
    # with §4.4's "VectorSeedPolicy + escalation armed" default.
    QueryClass.UNKNOWN: SectionSelector(
        include=(SectionKind.OVERVIEW,),
        fill_order=(SectionKind.OVERVIEW,),
    ),
}


def selector_for(query_class: QueryClass) -> SectionSelector:
    """Return the `SectionSelector` for `query_class`.

    Plain dict lookup — every `QueryClass` member has an entry, so this
    never raises `KeyError` for a valid `QueryClass`.

    Args:
        query_class: The classified `QueryClass`.

    Returns:
        The `SectionSelector` to drive `AncestrySummaryPolicy`/
        `RationalePolicy` retrieval args.
    """
    return _SELECTOR_BY_CLASS[query_class]
