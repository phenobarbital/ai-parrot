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
from typing import Optional

from .carding import slugify
from .models import REL_WEIGHTS, BookCard, BookRelation

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


def _same_era(
    a: BookCard, b: BookCard, era_window_years: int
) -> Optional[str]:
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
                    a, b, "same_author", REL_WEIGHTS["same_author"], now,
                    rationale=f"author={sorted(shared_authors)[0]}",
                )
            )

        jaccard = _jaccard(_slugs(a.topics), _slugs(b.topics))
        if jaccard >= topic_jaccard_min:
            out.append(
                _relation(
                    a, b, "shares_topic", jaccard, now,
                    rationale=f"jaccard={jaccard:.2f}",
                )
            )

        shared_traditions = _slugs(a.traditions) & _slugs(b.traditions)
        if shared_traditions:
            out.append(
                _relation(
                    a, b, "same_tradition", REL_WEIGHTS["same_tradition"], now,
                    rationale=f"tradition={sorted(shared_traditions)[0]}",
                )
            )

        if a.genre != "other" and a.genre == b.genre:
            out.append(
                _relation(
                    a, b, "same_genre", REL_WEIGHTS["same_genre"], now,
                    rationale=f"genre={a.genre}",
                )
            )

        era_rationale = _same_era(a, b, era_window_years)
        if era_rationale is not None:
            out.append(
                _relation(
                    a, b, "same_era", REL_WEIGHTS["same_era"], now,
                    rationale=era_rationale,
                )
            )

        if a.language and b.language and a.language == b.language:
            out.append(
                _relation(
                    a, b, "same_language", REL_WEIGHTS["same_language"], now,
                    rationale=f"language={a.language}",
                )
            )
    return out
