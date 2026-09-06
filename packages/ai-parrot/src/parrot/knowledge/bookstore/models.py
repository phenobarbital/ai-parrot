"""Pydantic models for the Bookstore catalog (the "ficha hemeroteca").

:class:`BookCard` is the durable catalog card persisted per book in
``library.db``; :class:`CardDraft` is the structured-output target the
LLM fills during carding (:mod:`parrot.knowledge.bookstore.carding`).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

#: Closed classification taxonomy filled by the carding LLM call
#: alongside title/authors/topics (FEAT-533). ``"other"`` is the
#: default for un-classified/legacy cards.
Genre = Literal[
    "novel",
    "short_stories",
    "essay",
    "treatise",
    "poetry",
    "drama",
    "dialogue",
    "biography",
    "history",
    "letters",
    "reference",
    "manual",
    "other",
]

#: Every edge type the book graph can carry (FEAT-533 spec §2).
#: - deterministic (``origin="deterministic"``): computed from fields
#:   already on ``BookCard``, no LLM.
#: - conceptual (``origin="llm"``): pairwise LLM judgement; only
#:   ``influenced_by``/``responds_to`` are directed, the rest symmetric.
#: - derived (``origin="community"``): written from a community partition.
RelationKind = Literal[
    "same_author",
    "shares_topic",
    "same_tradition",
    "same_genre",
    "same_era",
    "same_language",
    "influenced_by",
    "responds_to",
    "parallels",
    "contrasts_with",
    "same_community",
]

#: Relation kinds stored undirected — canonicalised ``src < dst`` on
#: write so ``(a, b)`` and ``(b, a)`` collapse to one row. Everything in
#: :data:`RelationKind` except the two directed conceptual relations.
SYMMETRIC_RELS: frozenset[str] = frozenset(
    {
        "same_author",
        "shares_topic",
        "same_tradition",
        "same_genre",
        "same_era",
        "same_language",
        "parallels",
        "contrasts_with",
        "same_community",
    }
)

#: Default clustering weight per relation kind, used by the Stage 3
#: graphindex adapter (spec §2 Overview step 3) to shape community
#: detection via the FEAT-533 Module 0 payload-weight contract.
#: ``shares_topic``'s value here is only the fallback: Stage 1
#: (``bookstore/relations.py``) normally overrides it per-edge with the
#: actual Jaccard score on the ``BookRelation.weight`` field.
#: ``responds_to``/``contrasts_with``/``same_community`` are not given
#: explicit values in the spec text (marked "e.g." — see spec §8 Open
#: Questions, "REL_WEIGHTS values ... adjust after the first real run");
#: this implementation mirrors their nearest sibling (``influenced_by``
#: and ``parallels`` respectively) and excludes ``same_community`` from
#: clustering input (Stage 3 builds edges from every relation *except*
#: ``same_community`` — spec §2 step 3) with a nominal weight.
REL_WEIGHTS: dict[str, float] = {
    "influenced_by": 1.0,
    "responds_to": 1.0,
    "same_author": 0.9,
    "parallels": 0.8,
    "contrasts_with": 0.8,
    "same_tradition": 0.7,
    "shares_topic": 0.5,
    "same_genre": 0.3,
    "same_era": 0.3,
    "same_language": 0.1,
    "same_community": 0.0,
}


class TocEntry(BaseModel):
    """One table-of-contents row derived from a PageIndex tree node.

    Args:
        node_id: PageIndex node id (``"0003"``) — the key for
            ``bookstore_read_section``.
        title: Section/chapter title.
        depth: 1-based depth in the tree (1 = top-level chapter).
        start_page: Physical start page (PDF trees only).
        end_page: Physical end page (PDF trees only).
    """

    node_id: str
    title: str
    depth: int = 1
    start_page: Optional[int] = None
    end_page: Optional[int] = None


class CardDraft(BaseModel):
    """LLM structured-output draft of the descriptive card fields.

    Produced by ``carding.generate_card_fields`` (or its no-LLM
    fallback) and merged into a :class:`BookCard` by the ingestion flow.
    """

    title: str = Field(..., description="Full book title.")
    authors: list[str] = Field(default_factory=list, description="Author names, best effort.")
    year: Optional[int] = Field(default=None, description="Publication year when identifiable.")
    language: Optional[str] = Field(default=None, description="Primary language, ISO 639-1 (e.g. 'en', 'es').")
    topics: list[str] = Field(
        default_factory=list,
        description="5-10 research topics/keywords this book is useful for.",
    )
    summary: str = Field(
        default="",
        description=(
            "One-paragraph librarian summary: what the book covers and " "what kind of questions it can answer."
        ),
    )
    genre: Genre = Field(default="other", description="Closed literary genre classification.")
    traditions: list[str] = Field(
        default_factory=list,
        description=(
            "Philosophical/literary traditions or schools this book "
            "belongs to (e.g. 'stoicism', 'spanish golden age')."
        ),
    )
    period: Optional[str] = Field(
        default=None,
        description=("Historical period or era (e.g. 'siglo de oro', 'han dynasty')."),
    )


class BookCard(BaseModel):
    """The catalog card ("ficha hemeroteca") for one indexed book.

    ``book_id`` doubles as the PageIndex ``tree_name`` — one slug, one
    tree, one card.
    """

    book_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    language: Optional[str] = None
    topics: list[str] = Field(default_factory=list)
    summary: str = ""
    toc_digest: str = ""
    toc: list[TocEntry] = Field(default_factory=list)
    tree_name: str
    scope: Literal["project", "global"] = "project"
    source_path: str
    source_sha256: str
    source_format: Literal["pdf", "md", "txt", "epub", "mobi", "docx"]
    page_count: Optional[int] = None
    chapter_count: int = 0
    added_at: str
    card_origin: Literal["llm", "fallback", "manual"] = "llm"
    genre: Genre = "other"
    traditions: list[str] = Field(default_factory=list)
    period: Optional[str] = None
    community_id: Optional[str] = None
    community_label: Optional[str] = None

    def brief(self) -> dict:
        """Compact dict for catalog listings (small tool outputs).

        Returns:
            The fields an agent needs to pick a book, without the full
            ToC payload.
        """
        first_line = self.summary.split("\n", 1)[0] if self.summary else ""
        return {
            "book_id": self.book_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "language": self.language,
            "topics": self.topics,
            "summary": first_line,
            "chapter_count": self.chapter_count,
            "page_count": self.page_count,
            "scope": self.scope,
            "genre": self.genre,
            "traditions": self.traditions,
            "period": self.period,
            "community_id": self.community_id,
            "community_label": self.community_label,
        }


class BookRelation(BaseModel):
    """One typed, provenance-bearing edge in the book graph.

    Symmetric relations (everything in :data:`RelationKind` except
    ``influenced_by``/``responds_to`` — see :data:`SYMMETRIC_RELS`) are
    canonicalised ``src_book_id < dst_book_id`` before persistence so
    ``(a, b)`` and ``(b, a)`` collapse to a single row.

    Args:
        src_book_id: Source book id (or the lexicographically smaller
            id of a symmetric pair, once canonicalised).
        dst_book_id: Target book id.
        rel: The relation kind.
        weight: Clustering weight fed to graphindex (FEAT-533 Module 0
            edge payload); defaults to 1.0, but deterministic relations
            such as ``shares_topic`` typically carry their own computed
            weight (e.g. the Jaccard score) instead.
        origin: Where this edge came from — ``"deterministic"``
            (computed from card fields, no LLM), ``"llm"`` (pairwise
            conceptual judgement), or ``"community"`` (derived from a
            community partition).
        confidence: LLM judgement confidence in ``[0, 1]``; ``None`` for
            deterministic/community edges.
        rationale: Free-form explanation (LLM edges) or a short
            deterministic reason (e.g. "same author slug").
        computed_at: ISO-8601 timestamp of when this edge was computed.
    """

    src_book_id: str
    dst_book_id: str
    rel: RelationKind
    weight: float = 1.0
    origin: Literal["deterministic", "llm", "community"]
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    rationale: str = ""
    computed_at: str

    @model_validator(mode="after")
    def _reject_self_pair(self) -> "BookRelation":
        """Backstop for the DB's ``CHECK (src_book_id <> dst_book_id)``."""
        if self.src_book_id == self.dst_book_id:
            raise ValueError("BookRelation cannot relate a book to itself " f"({self.src_book_id!r})")
        return self


class RelationJudgement(BaseModel):
    """One LLM verdict on one candidate pair, logged regardless of outcome.

    Every candidate considered by Stage 2 (conceptual relations) is
    logged here — including ``rel="none"`` verdicts and below-floor
    confidences — so :meth:`CatalogStore.judged_pairs` can skip
    already-asked pairs on the next ``bookstore relate`` run.

    Args:
        dst_book_id: The candidate book judged (from the perspective of
            the source book the judgement was requested for).
        rel: The judged relation, or ``"none"`` when the model found no
            relation between the pair.
        confidence: Model confidence in ``[0, 1]``.
        rationale: Free-form explanation from the model.
    """

    dst_book_id: str
    rel: Literal["influenced_by", "responds_to", "parallels", "contrasts_with", "none"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


class RelationDraft(BaseModel):
    """Structured LLM output: every judged candidate for one source book.

    Returned by one ``ask_structured`` call per source book in Stage 2
    (spec §2 step 3); ``judgements`` may be empty when the model found
    no candidates worth judging.
    """

    judgements: list[RelationJudgement] = Field(default_factory=list)


class CommunityLabelDraft(BaseModel):
    """Structured LLM output: a label for one community.

    Args:
        label: Short label, ideally 6 words or fewer.
        description: One-sentence description of what unites the
            community's member books.
    """

    label: str = Field(..., description="Community label, 6 words or fewer.")
    description: str = Field(default="", description="One-sentence description of the community.")


class BookCommunity(BaseModel):
    """One persisted community partition entry.

    Args:
        community_id: Stable membership hash from
            ``graphindex.communities.Community.community_id``.
        label: Display label — LLM-generated, ``derive_community_label``
            fallback, or the sole member's title for singletons.
        label_origin: Provenance of ``label``.
        description: One-sentence description (LLM label only).
        algorithm: Which algorithm produced the partition this
            community belongs to.
        size: Number of member books.
        cohesion: internal_edges / (internal_edges + boundary_edges).
        centroid_book_id: Member with the highest in-community degree.
        member_book_ids: All member book ids, centroid first.
        inter_relations: ``InterCommunityRelation.model_dump()`` rows
            touching this community (edges to other communities).
        computed_at: ISO-8601 timestamp of the detection run.
    """

    community_id: str
    label: str
    label_origin: Literal["llm", "derived", "title"]
    description: str = ""
    algorithm: Literal["leiden", "louvain"]
    size: int
    cohesion: float
    centroid_book_id: str
    member_book_ids: list[str] = Field(default_factory=list)
    inter_relations: list[dict] = Field(default_factory=list)
    computed_at: str


class RelateSummary(BaseModel):
    """Outcome of one :meth:`Bookstore.relate_books` batch run.

    Note:
        TASK-2913 first defined this model but the spec (§3 Module 2)
        only describes it in prose ("``RelateSummary`` with
        ``related``/``failed``/``skipped`` per book") without a field
        list in §2's Data Models block, so that first pass used
        placeholder field names and explicitly flagged them for
        re-verification by the actual consumer. TASK-2916 (the
        ``relate_books`` orchestrator) is that consumer and specifies
        the field list below in its own Codebase Contract — this shape
        supersedes the TASK-2913 placeholder.

    Args:
        targets: Book ids this run computed relations for (explicit
            ids, or every visible book when ``relate_books`` was
            called with ``book_ids=None``).
        deterministic_edges: Stage 1 edges written touching a target.
        llm_prompts: Number of Stage 2 ``ask_structured`` calls made
            (at most one per target book).
        llm_edges: Stage 2 edges written (``rel != "none"`` and
            ``confidence >= floor``).
        skipped_llm_reason: Why Stage 2 did not run at all this call
            (e.g. "no LLM configured", ``--no-llm``); ``None`` when it
            ran (even if it judged zero candidates for every target).
        failed: ``{book_id: error message}`` for targets whose Stage 2
            judgement raised — their Stage 1 edges are still written.
        communities: Number of communities computed this run, or
            ``None`` when Stage 3 did not run (``communities=False``
            or not yet implemented — see ``_relate_stage3``).
        notes: Free-form status notes for degraded/partial runs.
    """

    targets: list[str] = Field(default_factory=list)
    deterministic_edges: int = 0
    llm_prompts: int = 0
    llm_edges: int = 0
    skipped_llm_reason: Optional[str] = None
    failed: dict[str, str] = Field(default_factory=dict)
    communities: Optional[int] = None
    notes: list[str] = Field(default_factory=list)
