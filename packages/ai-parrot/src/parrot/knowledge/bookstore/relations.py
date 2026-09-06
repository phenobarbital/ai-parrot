"""Deterministic (LLM-free) relation computation for the book graph.

Stage 1 of the FEAT-533 conceptual-relations pipeline (spec §2 Overview
step 3, goals G2/G7): six relation kinds computed purely from fields
already on :class:`~parrot.knowledge.bookstore.models.BookCard` — no
LLM, no I/O. Every function here is pure and testable in isolation;
:class:`~parrot.knowledge.bookstore.library.Bookstore` owns persistence
and cross-scope routing (see ``Bookstore._write_deterministic``).
"""

from __future__ import annotations

import itertools
import logging
from typing import Any, Optional

from parrot.knowledge.graphindex.assemble import GraphAssembler
from parrot.knowledge.graphindex.communities import (
    Community,
    CommunitiesResult,
    derive_community_label,
    detect_communities,
)
from parrot.knowledge.graphindex.inter_community import (
    InterCommunityGraph,
    compute_inter_community_graph,
)
from parrot.knowledge.graphindex.schema import (
    EdgeKind,
    NodeKind,
    Provenance,
    UniversalEdge,
    UniversalNode,
)

from .carding import slugify
from .models import (
    REL_WEIGHTS,
    BookCard,
    BookCommunity,
    BookRelation,
    CommunityLabelDraft,
    RelationDraft,
)

logger = logging.getLogger(__name__)

#: ``slugify`` collapses non-Latin titles/names with no ASCII
#: decomposition to this fallback (carding.py — ``slugify`` docstring).
#: Treating two such authors as equal would produce false-positive
#: ``same_author`` edges between unrelated books (spec §7 gotcha).
_AUTHOR_FALLBACK_SLUG = "book"

#: Author slugs shorter than this are too weak a signal to trust
#: (single-initial names, OCR noise) — skipped, same rationale as the
#: fallback slug above.
_MIN_AUTHOR_SLUG_LEN = 3


def _author_key(name: str) -> Optional[str]:
    """Slugify one author name; ``None`` when it can't be trusted.

    Args:
        name: Raw author name from ``BookCard.authors``.

    Returns:
        The slug, or ``None`` when it collapsed to the ``slugify``
        fallback (``"book"``) or is shorter than 3 characters.
    """
    slug = slugify(name)
    if slug == _AUTHOR_FALLBACK_SLUG or len(slug) < _MIN_AUTHOR_SLUG_LEN:
        return None
    return slug


def _author_keys(card: BookCard) -> set[str]:
    """Trustworthy author slugs for one card (see :func:`_author_key`)."""
    keys: set[str] = set()
    for name in card.authors:
        key = _author_key(name)
        if key is not None:
            keys.add(key)
    return keys


def _slugs(values: list[str]) -> set[str]:
    """Slugify a list of free-text values, dropping empties."""
    return {slugify(v) for v in values if v}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two sets; ``0.0`` when either is empty."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _canonical_pair(a: BookCard, b: BookCard) -> tuple[str, str]:
    """Sort two book ids for a symmetric relation's ``(src, dst)``."""
    return (a.book_id, b.book_id) if a.book_id < b.book_id else (b.book_id, a.book_id)


def _relation(
    a: BookCard,
    b: BookCard,
    rel: str,
    weight: float,
    now: str,
    *,
    rationale: str = "",
) -> BookRelation:
    """Build one canonically-ordered ``origin="deterministic"`` edge."""
    src, dst = _canonical_pair(a, b)
    return BookRelation(
        src_book_id=src,
        dst_book_id=dst,
        rel=rel,  # type: ignore[arg-type]
        weight=weight,
        origin="deterministic",
        rationale=rationale,
        computed_at=now,
    )


def _same_era(a: BookCard, b: BookCard, era_window_years: int) -> Optional[str]:
    """Rationale string when ``a``/``b`` share an era, else ``None``.

    Matches on a ``year`` window (``|year_a - year_b| <= window``) OR
    an equal, non-empty ``period`` slug — either is sufficient.
    """
    if a.year is not None and b.year is not None:
        if abs(a.year - b.year) <= era_window_years:
            return f"year_window<={era_window_years}"
    period_a = slugify(a.period) if a.period else ""
    period_b = slugify(b.period) if b.period else ""
    if period_a and period_a == period_b:
        return f"period={period_a}"
    return None


def deterministic_relations(
    cards: list[BookCard],
    *,
    now: str,
    topic_jaccard_min: float = 0.2,
    era_window_years: int = 50,
) -> list[BookRelation]:
    """Compute every Stage 1 edge over ``cards`` (O(n^2), no I/O).

    Six relation kinds, each independent (a pair may gain several):

    - ``same_author``: any trustworthy author slug in common
      (:func:`_author_key`).
    - ``shares_topic``: Jaccard over slugified topics >=
      ``topic_jaccard_min``; edge weight *is* the Jaccard score
      (overrides :data:`~parrot.knowledge.bookstore.models.REL_WEIGHTS`).
    - ``same_tradition``: any slugified tradition in common.
    - ``same_genre``: equal, non-default (``!= "other"``) genre — the
      default is a "not yet classified" catch-all, matching on it would
      flood an LLM-less library with meaningless edges.
    - ``same_era``: see :func:`_same_era`.
    - ``same_language``: both set and equal.

    Args:
        cards: The book universe to compute pairs over (typically
            ``Bookstore.list_books()``, already scope-merged).
        now: ISO-8601 timestamp stamped on every produced edge.
        topic_jaccard_min: Minimum Jaccard to emit a ``shares_topic``
            edge.
        era_window_years: Year window for ``same_era`` (see
            :func:`_same_era`).

    Returns:
        Deterministic edges, canonically ordered (``src < dst``).
        Callers wanting an idempotent re-run should replace the prior
        deterministic edges for every touched book first — see
        ``Bookstore._write_deterministic``.
    """
    out: list[BookRelation] = []
    ordered = sorted(cards, key=lambda c: c.book_id)
    for a, b in itertools.combinations(ordered, 2):
        shared_authors = _author_keys(a) & _author_keys(b)
        if shared_authors:
            out.append(
                _relation(
                    a,
                    b,
                    "same_author",
                    REL_WEIGHTS["same_author"],
                    now,
                    rationale=f"author={sorted(shared_authors)[0]}",
                )
            )

        jaccard = _jaccard(_slugs(a.topics), _slugs(b.topics))
        if jaccard >= topic_jaccard_min:
            out.append(
                _relation(
                    a,
                    b,
                    "shares_topic",
                    jaccard,
                    now,
                    rationale=f"jaccard={jaccard:.2f}",
                )
            )

        shared_traditions = _slugs(a.traditions) & _slugs(b.traditions)
        if shared_traditions:
            out.append(
                _relation(
                    a,
                    b,
                    "same_tradition",
                    REL_WEIGHTS["same_tradition"],
                    now,
                    rationale=f"tradition={sorted(shared_traditions)[0]}",
                )
            )

        if a.genre != "other" and a.genre == b.genre:
            out.append(
                _relation(
                    a,
                    b,
                    "same_genre",
                    REL_WEIGHTS["same_genre"],
                    now,
                    rationale=f"genre={a.genre}",
                )
            )

        era_rationale = _same_era(a, b, era_window_years)
        if era_rationale is not None:
            out.append(
                _relation(
                    a,
                    b,
                    "same_era",
                    REL_WEIGHTS["same_era"],
                    now,
                    rationale=era_rationale,
                )
            )

        if a.language and b.language and a.language == b.language:
            out.append(
                _relation(
                    a,
                    b,
                    "same_language",
                    REL_WEIGHTS["same_language"],
                    now,
                    rationale=f"language={a.language}",
                )
            )
    return out


# ---------------------------------------------------------------------------
# Stage 2 — LLM conceptual relations (spec §2 Overview step 3, goal G3)
# ---------------------------------------------------------------------------

_RELATION_PROMPT = """You are a librarian mapping conceptual relations between books in a
personal library. Given the SOURCE book below and a list of CANDIDATE
books, judge whether the source book relates to each candidate through
one of these conceptual relations:

- `influenced_by`: the source book was influenced by the candidate.
  Directed FROM the source book TO the candidate.
- `responds_to`: the source book responds to, critiques, or engages
  with the candidate. Directed FROM the source book TO the candidate.
- `parallels`: the two books explore similar ideas/themes
  independently (symmetric — direction does not matter).
- `contrasts_with`: the two books present opposing views on a related
  subject (symmetric — direction does not matter).
- `none`: no meaningful conceptual relation between the two books.

SOURCE book:
{source_brief}

CANDIDATE books — judge EVERY one below, using its `book_id` verbatim
in your answer:
{candidate_briefs}

Rules:
- Return exactly one judgement per candidate listed above.
- `influenced_by`/`responds_to` are directed FROM the source book.
- `confidence`: 0.0-1.0, how sure you are of the judgement.
- `rationale`: one sentence explaining the judgement.
- When unsure or the relation is weak, use `rel="none"` rather than
  guessing.
"""


def candidate_pairs(
    card: BookCard,
    cards: list[BookCard],
    det_relations: list[BookRelation],
    fts_hits: list[BookCard],
    judged: set[str],
    cap: int = 8,
) -> list[BookCard]:
    """Pre-filter Stage 2 candidates for one source book.

    Union of Stage 1 (deterministic) neighbours and FTS search hits,
    minus ``card`` itself and anything already in ``judged`` — stable
    order (deterministic neighbours first, by edge weight descending,
    then FTS hits in their given order), capped at ``cap``.

    Args:
        card: The source book Stage 2 will judge candidates for.
        cards: The full visible card universe (to resolve neighbour
            ids from ``det_relations`` back into ``BookCard``s).
        det_relations: Stage 1 edges (typically the full
            ``deterministic_relations()`` output) — only those
            touching ``card`` contribute neighbours.
        fts_hits: ``Bookstore.catalog_search(...)`` results for
            ``card``'s summary/topics.
        judged: Book ids already judged as a candidate for ``card``
            (``CatalogStore.judged_pairs(card.book_id)``); skipped
            unless the caller passes an empty set (``--force``).
        cap: Maximum candidates returned.

    Returns:
        Up to ``cap`` candidate cards, never including ``card`` itself.
    """
    cards_by_id = {c.book_id: c for c in cards}

    det_neighbors: list[tuple[float, str]] = []
    for relation in det_relations:
        if relation.src_book_id == card.book_id:
            det_neighbors.append((relation.weight, relation.dst_book_id))
        elif relation.dst_book_id == card.book_id:
            det_neighbors.append((relation.weight, relation.src_book_id))
    det_neighbors.sort(key=lambda item: -item[0])

    ordered_ids: list[str] = []
    seen: set[str] = set()
    for _weight, other_id in det_neighbors:
        if other_id not in seen:
            seen.add(other_id)
            ordered_ids.append(other_id)
    for hit in fts_hits:
        if hit.book_id not in seen:
            seen.add(hit.book_id)
            ordered_ids.append(hit.book_id)

    result: list[BookCard] = []
    for other_id in ordered_ids:
        if other_id == card.book_id or other_id in judged:
            continue
        other_card = cards_by_id.get(other_id)
        if other_card is None:
            continue
        result.append(other_card)
        if len(result) >= cap:
            break
    return result


def _brief_line(card: BookCard) -> str:
    """One candidate/source line for the Stage 2 prompt."""
    return (
        f"- book_id={card.book_id} | title={card.title} | "
        f"authors={', '.join(card.authors) or '(unknown)'} | "
        f"topics={', '.join(card.topics) or '(none)'} | "
        f"summary={card.summary or '(none)'}"
    )


async def judge_relations(
    adapter: Any,
    card: BookCard,
    candidates: list[BookCard],
    *,
    model_name: str = "",
) -> RelationDraft:
    """One structured LLM call judging every candidate for ``card``.

    Exactly one ``ask_structured`` call per source book — never one
    call per candidate pair (bounded LLM cost, goal G3).

    Args:
        adapter: Any object exposing
            ``async ask_structured(prompt, schema) -> RelationDraft | dict``
            (e.g. :class:`~parrot.knowledge.pageindex.llm_adapter.PageIndexLLMAdapter`).
        card: The source book.
        candidates: Pre-filtered candidates (:func:`candidate_pairs`).
        model_name: Model identifier, logged only (the caller records
            it against ``relation_judgements`` separately).

    Returns:
        A :class:`RelationDraft` containing only judgements whose
        ``dst_book_id`` matches a candidate — any hallucinated id the
        model returns is silently dropped.
    """
    logger.debug(
        "Stage 2: judging %d candidate(s) for %r (model=%s)",
        len(candidates),
        card.book_id,
        model_name or "?",
    )
    prompt = _RELATION_PROMPT.format(
        source_brief=_brief_line(card),
        candidate_briefs="\n".join(_brief_line(c) for c in candidates) or "(none)",
    )
    draft = await adapter.ask_structured(prompt, RelationDraft)
    if not isinstance(draft, RelationDraft):
        draft = RelationDraft.model_validate(draft)
    valid_ids = {c.book_id for c in candidates}
    judgements = [j for j in draft.judgements if j.dst_book_id in valid_ids]
    return RelationDraft(judgements=judgements)


def llm_relations_from_draft(
    card: BookCard,
    draft: RelationDraft,
    *,
    now: str,
    floor: float = 0.5,
) -> list[BookRelation]:
    """Turn a judged :class:`RelationDraft` into persistable edges.

    Every judgement is expected to already be logged via
    ``CatalogStore.record_judgements`` by the caller, regardless of
    outcome — this function only decides which judgements *also*
    become a ``book_relations`` row: ``rel != "none"`` and
    ``confidence >= floor``.

    Args:
        card: The source book the judgements were requested for.
        draft: Judgements to convert (already filtered to known
            candidate ids by :func:`judge_relations`).
        now: ISO-8601 timestamp stamped on every produced edge.
        floor: Minimum confidence to produce an edge.

    Returns:
        ``origin="llm"`` edges directed from ``card`` to each judged
        candidate (symmetric relations are canonicalised on write by
        ``CatalogStore.upsert_relations``, not here).
    """
    out: list[BookRelation] = []
    for judgement in draft.judgements:
        if judgement.rel == "none" or judgement.confidence < floor:
            continue
        if judgement.dst_book_id == card.book_id:
            continue  # defensive — BookRelation rejects self-pairs
        out.append(
            BookRelation(
                src_book_id=card.book_id,
                dst_book_id=judgement.dst_book_id,
                rel=judgement.rel,  # type: ignore[arg-type]
                weight=REL_WEIGHTS[judgement.rel],
                origin="llm",
                confidence=judgement.confidence,
                rationale=judgement.rationale,
                computed_at=now,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Stage 3 — communities via graphindex (spec §2 Overview step 3, goal G4)
# ---------------------------------------------------------------------------


def build_book_graph(
    cards: list[BookCard], relations: list[BookRelation]
) -> tuple[GraphAssembler, list[UniversalNode]]:
    """Adapt the book catalog + graph into graphindex's node/edge schema.

    One :class:`UniversalNode` per card (``node_id=book_id``,
    ``kind=DOCUMENT``); one :class:`UniversalEdge` per relation except
    ``same_community`` (which is *derived from* clustering, not an
    input to it). LLM edges get ``provenance=INFERRED`` + their
    confidence; every other origin gets ``EXTRACTED`` with no
    confidence (``UniversalEdge``'s validator requires exactly that).
    Every edge carries ``domain_tags["weight"]`` so FEAT-533 Module 0's
    payload-weight contract shapes the partition.

    Args:
        cards: The book universe to build nodes for (typically the
            full merged, visible card list).
        relations: Edges to adapt (typically
            ``merged_relations(...)`` minus ``same_community``).

    Returns:
        The populated :class:`GraphAssembler` plus its node list (the
        node list is what :func:`~parrot.knowledge.graphindex.communities.detect_communities`
        needs alongside the assembler's ``.graph``).
    """
    nodes = [
        UniversalNode(
            node_id=card.book_id,
            kind=NodeKind.DOCUMENT,
            title=card.title,
            source_uri=card.source_path,
            summary=card.summary or None,
            domain_tags={
                "genre": card.genre,
                "traditions": card.traditions,
                "scope": card.scope,
                "book_id": card.book_id,
            },
        )
        for card in cards
    ]
    edges: list[UniversalEdge] = []
    for relation in relations:
        if relation.rel == "same_community":
            continue
        inferred = relation.origin == "llm"
        edges.append(
            UniversalEdge(
                source_id=relation.src_book_id,
                target_id=relation.dst_book_id,
                kind=EdgeKind.REFERENCES,
                provenance=Provenance.INFERRED if inferred else Provenance.EXTRACTED,
                confidence=relation.confidence if inferred else None,
                domain_tags={
                    "rel": relation.rel,
                    "origin": relation.origin,
                    "weight": relation.weight,
                },
            )
        )
    assembler = GraphAssembler(tenant_id="bookstore")
    assembler.add_nodes(nodes)
    assembler.add_edges(edges)
    return assembler, nodes


def detect_book_communities(
    cards: list[BookCard],
    relations: list[BookRelation],
    *,
    resolution: float = 1.0,
    seed: int = 42,
    algorithm: str = "leiden",
) -> tuple[CommunitiesResult, InterCommunityGraph, GraphAssembler]:
    """Build the book graph and detect communities over it.

    Args:
        cards: See :func:`build_book_graph`.
        relations: See :func:`build_book_graph`.
        resolution: Forwarded to
            :func:`~parrot.knowledge.graphindex.communities.detect_communities`.
        seed: Forwarded, for deterministic partitions across runs.
        algorithm: ``"leiden"`` (default, Louvain fallback when
            ``leidenalg``/``python-igraph`` aren't importable) or
            ``"louvain"``.

    Returns:
        ``(result, inter_community_graph, assembler)`` — the assembler
        is returned too since callers (labelling) need the raw graph
        alongside the partition.
    """
    assembler, nodes = build_book_graph(cards, relations)
    result = detect_communities(
        assembler.graph,
        nodes,
        resolution=resolution,
        seed=seed,
        algorithm=algorithm,
        write_back_to_nodes=False,
    )
    inter = compute_inter_community_graph(assembler.graph, result)
    return result, inter, assembler


_LABEL_PROMPT = """You are a librarian labelling a cluster of related books in a personal
library. Given the member books below, produce a short label and a
one-sentence description of what unites them.

Member books:
{member_briefs}

Rules:
- `label`: 6 words or fewer, evocative of the shared theme/tradition.
- `description`: one sentence explaining what unites these books.
"""


async def label_community(
    adapter: Any,
    community: Community,
    cards_by_id: dict[str, BookCard],
) -> CommunityLabelDraft:
    """One structured LLM call producing a label for one community.

    Args:
        adapter: Any object exposing
            ``async ask_structured(prompt, schema) -> CommunityLabelDraft | dict``.
        community: The community to label.
        cards_by_id: Every visible card, keyed by ``book_id``.

    Returns:
        The LLM-filled :class:`CommunityLabelDraft`.
    """
    members = [cards_by_id[node_id] for node_id in community.member_node_ids[:10] if node_id in cards_by_id]
    lines = [
        f"- title={card.title} | authors={', '.join(card.authors) or '(unknown)'} | "
        f"traditions={', '.join(card.traditions) or '(none)'} | "
        f"topics={', '.join(card.topics) or '(none)'}"
        for card in members
    ]
    prompt = _LABEL_PROMPT.format(member_briefs="\n".join(lines) or "(no members)")
    draft = await adapter.ask_structured(prompt, CommunityLabelDraft)
    if not isinstance(draft, CommunityLabelDraft):
        draft = CommunityLabelDraft.model_validate(draft)
    return draft


def fallback_label(community: Community, cards_by_id: dict[str, BookCard]) -> tuple[str, str]:
    """Deterministic label when no LLM is available or labelling failed.

    Args:
        community: The community to label.
        cards_by_id: Every visible card, keyed by ``book_id``.

    Returns:
        ``(label, label_origin)`` — ``derive_community_label(top_titles)``
        when it finds something salient (``"derived"``); otherwise (no
        salient keyword, or a singleton community) the centroid
        member's title (``"title"``).
    """
    if community.size == 1:
        card = cards_by_id.get(community.centroid_node_id)
        title = card.title if card is not None else community.centroid_node_id
        return title, "title"
    label = derive_community_label(community.top_titles)
    if label:
        return label, "derived"
    card = cards_by_id.get(community.centroid_node_id)
    title = card.title if card is not None else community.centroid_node_id
    return title, "title"


def communities_from_result(
    result: CommunitiesResult,
    inter: InterCommunityGraph,
    labels: dict[str, tuple[str, str, str]],
    cards_by_id: dict[str, BookCard],
    *,
    now: str,
) -> list[BookCommunity]:
    """Turn a partition + inter-community graph into persistable rows.

    Args:
        result: The detected partition.
        inter: The inter-community meta-graph (for ``inter_relations``).
        labels: ``community_id -> (label, description, label_origin)``,
            typically built from :func:`label_community`/
            :func:`fallback_label` results.
        cards_by_id: Unused directly here (kept for a stable, symmetric
            signature with the other Stage 3 functions and to let
            future callers derive labels lazily); present per the
            Codebase Contract.
        now: ISO-8601 timestamp stamped on every produced row.

    Returns:
        One :class:`BookCommunity` per community in ``result``.
    """
    del cards_by_id  # see docstring — not needed once `labels` is built
    inter_by_community: dict[str, list[dict]] = {}
    for relation in inter.relations:
        row = relation.model_dump()
        inter_by_community.setdefault(relation.source_community_id, []).append(row)
        inter_by_community.setdefault(relation.target_community_id, []).append(row)

    out: list[BookCommunity] = []
    for community in result.communities:
        label, description, label_origin = labels.get(
            community.community_id, (community.label or community.centroid_node_id, "", "derived")
        )
        out.append(
            BookCommunity(
                community_id=community.community_id,
                label=label,
                label_origin=label_origin,  # type: ignore[arg-type]
                description=description,
                algorithm=result.algorithm,  # type: ignore[arg-type]
                size=community.size,
                cohesion=community.cohesion,
                centroid_book_id=community.centroid_node_id,
                member_book_ids=community.member_node_ids,
                inter_relations=inter_by_community.get(community.community_id, []),
                computed_at=now,
            )
        )
    return out
