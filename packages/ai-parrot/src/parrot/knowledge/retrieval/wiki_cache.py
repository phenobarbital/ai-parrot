"""`WikiSection`/`WikiPage` — the L1 synthesis cache (spec §6).

Splitting is a **retrieval-time selection over addressable sections**, not
a generation-time page-splitting heuristic (OQ-5): a `WikiPage` is a
structured document, sections are the addressable unit. Because each
section declares its own sources, editing one method invalidates only the
`CONTRACTS` section of its class page — `RATIONALE`/`GOTCHAS` stay
`FRESH`. Mixed freshness within one page is acceptable and must be
surfaced, never prevented (RQ-2) — requiring all-fresh-or-none would
re-impose the whole-page invalidation this design removes.

Note: `WikiPage`/`WikiSection` are NOT `parrot.knowledge.wiki`'s
`WikiPageCategory`/`SourceManifestEntry` (FEAT-260) — a different,
orthogonal taxonomy and a different store. The two coexist (spec §14.3);
this module does not import from `parrot.knowledge.wiki`.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from parrot.knowledge.retrieval.digest import DigestScope
from parrot.knowledge.retrieval.models import NodeRef
from parrot.knowledge.retrieval.sections import SectionKind

logger = logging.getLogger(__name__)


class SourceDigest(BaseModel):
    """One `(node_id, digest)` pair a `WikiSection` declares as a source.

    Attributes:
        node_id: The L0 node this digest is over.
        digest: The derived digest (TASK-2273) at generation time.
        digest_scope: The granularity that digest was computed at.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    node_id: str
    digest: str
    digest_scope: DigestScope


class GeneratorInfo(BaseModel):
    """Attribution for what produced a `WikiSection`'s body.

    Attributes:
        model: Model identifier (e.g. ``"anthropic:claude-3-5-sonnet"``).
            Generation itself is out of scope here (T10/T11) — this is the
            seam those tasks fill in.
        generated_by: Free-form producer tag, default ``"llm"``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    generated_by: str = "llm"


def compute_coherence_group(sources: tuple[SourceDigest, ...]) -> str:
    """Digest a section's `(node_id, digest)` multiset (RQ-2).

    Two sections sharing a `coherence_group` describe the same point-in-
    time state of the code; `ContextBundle.mixed_freshness` is set when
    selected sections do NOT share one (spec §9.1 RQ-2).

    Args:
        sources: The section's declared `SourceDigest`s.

    Returns:
        A stable sha256 hex digest of the sorted ``node_id:digest`` pairs.
    """
    parts = sorted(f"{s.node_id}:{s.digest}" for s in sources)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


class WikiSection(BaseModel):
    """One addressable section of a `WikiPage` (spec §6.1).

    Attributes:
        kind: Which `SectionKind` this is.
        body: Markdown prose.
        sources: `SourceDigest`s this section's body was generated from —
            scoped to THIS section, not the whole page.
        token_estimate: Estimated token count of `body`.
        generated_at: When this section was last (re)generated.
        generator: Attribution for the generation.
        state: ``"FRESH"``, ``"STALE"``, or ``"REGENERATING"``.
        coherence_group: `compute_coherence_group(sources)` — stamped at
            construction so staleness comparisons don't recompute it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SectionKind
    body: str
    sources: tuple[SourceDigest, ...]
    token_estimate: int
    generated_at: datetime
    generator: GeneratorInfo
    state: Literal["FRESH", "STALE", "REGENERATING"]
    coherence_group: str


class WikiPage(BaseModel):
    """A structured L1 document anchored to one L0 subtree (spec §6.1).

    Attributes:
        page_id: Stable identifier — hash of ``(repo, scope_uri)``.
        scope: The `NodeRef` this page summarizes.
        sections: This page's sections, keyed by `SectionKind`. Not every
            `SectionKind` need be present.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    page_id: str
    scope: NodeRef
    sections: Mapping[SectionKind, WikiSection]


def compute_page_id(repo: str, scope_uri: str) -> str:
    """Compute a stable `WikiPage.page_id` from `(repo, scope_uri)`.

    Args:
        repo: Repository name.
        scope_uri: The scope node's `NodeRef.uri`.

    Returns:
        A stable sha256 hex digest.
    """
    return hashlib.sha256(f"{repo}::{scope_uri}".encode()).hexdigest()


def invalidate_section(section: WikiSection, current_digests: Mapping[str, str]) -> WikiSection:
    """Transition `section` FRESH -> STALE if any of its sources moved.

    Never eager-regenerates — this only flips the `state` field. A section
    is regenerated later, only when a request actually selects it and
    ``budget.max_llm_calls > 0`` (spec §6.2).

    Args:
        section: The section to check.
        current_digests: ``node_id -> current digest``, freshly derived
            (TASK-2273) at invalidation time.

    Returns:
        `section` unchanged if it is already non-FRESH or all its sources
        still match; otherwise a copy with ``state="STALE"``.
    """
    if section.state != "FRESH":
        return section
    for source in section.sources:
        current = current_digests.get(source.node_id)
        if current is None or current != source.digest:
            logger.debug(
                "WikiSection %s: source node_id=%r digest changed (%r -> %r) — STALE",
                section.kind,
                source.node_id,
                source.digest,
                current,
            )
            return section.model_copy(update={"state": "STALE"})
    return section


def invalidate_page(page: WikiPage, current_digests: Mapping[str, str]) -> WikiPage:
    """Apply `invalidate_section` to every section of `page` (horizontal scoping).

    Only sections whose declared sources actually moved transition to
    STALE — most edits touch `CONTRACTS`/`USAGE` while `RATIONALE` and
    `GOTCHAS` stay untouched (spec §6.2).

    Args:
        page: The page to check.
        current_digests: ``node_id -> current digest``.

    Returns:
        A copy of `page` with any affected sections marked STALE.
    """
    new_sections = {
        kind: invalidate_section(section, current_digests)
        for kind, section in page.sections.items()
    }
    return page.model_copy(update={"sections": new_sections})


def invalidate_ancestors(
    *,
    changed_node_id: str,
    pages_by_scope_node_id: Mapping[str, WikiPage],
    parent_of: Mapping[str, str | None],
    current_digests: Mapping[str, str],
    max_ancestor_depth: int = 5,
) -> dict[str, WikiPage]:
    """Invalidate `changed_node_id`'s own page, then walk ancestors upward.

    Vertical scoping (spec §6.2): a change to one method invalidates the
    corresponding section of its class page AND every ancestor page — but
    NEVER siblings, since this only ever walks `parent_id` upward. Capped
    at `max_ancestor_depth` (ancestor invalidation is the expensive
    direction) and cycle-safe (a visited set breaks a pathological
    `parent_id` cycle rather than hanging re-index).

    Args:
        changed_node_id: The L0 node whose content changed.
        pages_by_scope_node_id: Every known `WikiPage`, keyed by its
            `scope`'s node_id (not `page_id` — this needs the raw L0 id
            to walk `parent_of`).
        parent_of: ``node_id -> parent node_id`` (or ``None`` at the
            root), for the ancestor walk.
        current_digests: ``node_id -> current digest``.
        max_ancestor_depth: Maximum number of ancestor hops to invalidate.

    Returns:
        ``node_id -> updated WikiPage`` for every page actually visited
        (only pages that exist in `pages_by_scope_node_id`).
    """
    updated: dict[str, WikiPage] = {}
    visited: set[str] = set()
    current_id: str | None = changed_node_id
    depth = 0

    while current_id is not None and current_id not in visited and depth <= max_ancestor_depth:
        visited.add(current_id)
        page = pages_by_scope_node_id.get(current_id)
        if page is not None:
            updated[current_id] = invalidate_page(page, current_digests)
        current_id = parent_of.get(current_id)
        depth += 1

    return updated


def compute_mixed_freshness(selected_sections: Iterable[WikiSection]) -> bool:
    """``True`` iff `selected_sections` do not all share one `coherence_group`.

    RQ-2: mixed freshness within a bundle is acceptable and must be
    surfaced (`ContextBundle.mixed_freshness`), not prevented.

    Args:
        selected_sections: The `WikiSection`s a request actually selected.

    Returns:
        ``True`` if two or more distinct `coherence_group`s are present.
    """
    groups = {section.coherence_group for section in selected_sections}
    return len(groups) > 1


class ServingDecision(StrEnum):
    """Which of §6.3's four serving behaviours applies to one request.

    Attributes:
        SERVE_STALE: Serve the stale body; record in `stale_sources`; the
            caller must surface the marker.
        REGENERATE_THEN_STALE_FALLBACK: Single-flight regenerate; on
            deadline miss, serve stale + marker.
        SKIP_TO_L0: Skip L1 entirely; fall back to L0 source excerpts.
        BLOCK_REGENERATE_THEN_L0_FALLBACK: Block on regeneration up to the
            deadline; then fall back to L0.
    """

    SERVE_STALE = "serve_stale"
    REGENERATE_THEN_STALE_FALLBACK = "regenerate_then_stale_fallback"
    SKIP_TO_L0 = "skip_to_l0"
    BLOCK_REGENERATE_THEN_L0_FALLBACK = "block_regenerate_then_l0_fallback"


def resolve_serving_decision(*, allow_stale: bool, max_llm_calls: int) -> ServingDecision:
    """Resolve which serving behaviour applies (spec §6.3's serving matrix).

    | allow_stale | max_llm_calls | Behaviour |
    |---|---|---|
    | True | 0 | `SERVE_STALE` |
    | True | >0 | `REGENERATE_THEN_STALE_FALLBACK` |
    | False | 0 | `SKIP_TO_L0` |
    | False | >0 | `BLOCK_REGENERATE_THEN_L0_FALLBACK` |

    Args:
        allow_stale: `RetrievalBudget.allow_stale`.
        max_llm_calls: `RetrievalBudget.max_llm_calls`.

    Returns:
        The applicable `ServingDecision`.
    """
    if allow_stale:
        return (
            ServingDecision.REGENERATE_THEN_STALE_FALLBACK
            if max_llm_calls > 0
            else ServingDecision.SERVE_STALE
        )
    return (
        ServingDecision.BLOCK_REGENERATE_THEN_L0_FALLBACK
        if max_llm_calls > 0
        else ServingDecision.SKIP_TO_L0
    )
