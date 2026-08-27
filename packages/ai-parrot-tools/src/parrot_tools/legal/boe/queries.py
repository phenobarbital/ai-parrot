"""Typed wrappers around the declarative traversal patterns (``article_in_force``,
``search_articles``).

The resolution *logic* — which wording was in force on a given date, and
the lexical-candidate BM25 search — lives entirely in the AQL
``query_template``s declared in ``legal.ontology.yaml`` (TASK-2371,
TASK-2494). This module is pure ergonomics: binding, calling
``OntologyGraphStore.execute_traversal``, and deserialising the result. It
does not re-implement version selection in Python — that would duplicate
the pattern and violate spec goal G4 (declarative-first temporal
resolution). ``search_articles`` additionally applies a Python-side
token-containment guard (FEAT-449 §3 M5) — NOT a re-selection of versions,
only a check that the query is actually about the in-force wording the AQL
already selected.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import TenantContext

from .models import ArticleHit, ArticleVersion

_PATTERN_NAME = "article_in_force"
_SEARCH_PATTERN_NAME = "search_articles"


async def article_in_force(
    store: OntologyGraphStore,
    ctx: TenantContext,
    articulo_key: str,
    as_of: date,
) -> ArticleVersion | None:
    """Resolve the wording of an article in force on a given date.

    Reads the ``article_in_force`` AQL template from
    ``ctx.ontology.traversal_patterns`` (never inlined here), binds
    ``articulo_key``, ``as_of`` and the ``@articulo`` collection, and
    deserialises the single matching version.

    Args:
        store: The OntologyGraphStore to execute the traversal against.
        ctx: Tenant context carrying the merged ontology and its
            traversal patterns.
        articulo_key: The composite articulo key (``{boe_id}:{numero}``)
            to resolve.
        as_of: The date to resolve the wording for.

    Returns:
        The ArticleVersion in force on ``as_of``, or ``None`` when no
        version was in force on that date (e.g. ``as_of`` precedes the
        article's earliest version) — a legitimate "no law applied on
        that date" answer, not an error.

    Raises:
        KeyError: If the ``article_in_force`` traversal pattern is not
            declared in ``ctx.ontology`` — a configuration bug worth
            failing loudly on.
    """
    try:
        pattern = ctx.ontology.traversal_patterns[_PATTERN_NAME]
    except KeyError as exc:
        raise KeyError(
            f"Traversal pattern '{_PATTERN_NAME}' is not declared in the "
            "merged ontology — is legal.ontology.yaml loaded for this tenant?"
        ) from exc

    rows = await store.execute_traversal(
        ctx,
        pattern.query_template,
        bind_vars={"articulo_key": articulo_key, "as_of": as_of.isoformat()},
        collection_binds={"@articulo": "articulo"},
    )
    if not rows:
        return None
    return ArticleVersion(**rows[0])


def _fold(s: str) -> str:
    """Fold text for accent/case-insensitive token containment checks.

    Args:
        s: Text to fold.

    Returns:
        NFKD-normalized, ASCII-only, lowercased text.
    """
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _query_tokens(query: str) -> list[str]:
    """Extract the query tokens the token-containment guard checks.

    Args:
        query: The raw user query.

    Returns:
        Folded tokens of length >= 4 from the query.
    """
    return re.findall(r"\w{4,}", _fold(query))


def passes_token_guard(query: str, text: str | None) -> bool:
    """The load-bearing temporal check applied AFTER the AQL (spec §3 M5).

    ``SEARCH`` matches at DOCUMENT level (any version's text can match);
    this guard drops a candidate whose lexical match lives only in a
    superseded wording by checking that at least one query token is a
    substring of the FOLDED in-force version's text. If the query yields
    zero tokens of length >= 4 (short/stopword-only query), the guard is
    skipped (every candidate passes).

    Args:
        query: The raw user query.
        text: The in-force version's text to check against (may be
            ``None`` for a ``supresion`` version).

    Returns:
        ``True`` when the candidate should be kept.
    """
    tokens = _query_tokens(query)
    if not tokens:
        return True  # short/stopword-only query: skip the guard
    folded = _fold(text or "")
    return any(t in folded for t in tokens)


async def search_articles(
    store: OntologyGraphStore,
    ctx: TenantContext,
    query: str,
    as_of: date,
    limit: int = 20,
) -> list[ArticleHit]:
    """Lexical candidate search over article wordings + in-force resolution.

    Reads the ``search_articles`` AQL template from
    ``ctx.ontology.traversal_patterns`` (never inlined here), executes it
    via ``store.execute_traversal`` (no ``collection_binds`` — the view
    name is a literal in the template, never a bind var), then applies
    the token-containment guard in Python to drop any hit whose lexical
    match lives only in a superseded wording (the AQL's temporal FILTER
    already selects the in-force version; the guard only checks that the
    query is actually about THAT wording, not a repealed one that
    happened to match at the SEARCH stage).

    Args:
        store: The OntologyGraphStore to execute the traversal against.
        ctx: Tenant context carrying the merged ontology and its
            traversal patterns.
        query: The user's lexical query.
        as_of: The date to resolve in-force versions for.
        limit: Maximum number of BM25 candidates to fetch.

    Returns:
        Hits in the AQL's BM25 order (never re-sorted in Python),
        filtered by the token-containment guard.

    Raises:
        KeyError: If the ``search_articles`` traversal pattern is not
            declared in ``ctx.ontology`` — a configuration bug worth
            failing loudly on.
    """
    try:
        pattern = ctx.ontology.traversal_patterns[_SEARCH_PATTERN_NAME]
    except KeyError as exc:
        raise KeyError(
            f"Traversal pattern '{_SEARCH_PATTERN_NAME}' is not declared in the "
            "merged ontology — is legal.ontology.yaml loaded for this tenant?"
        ) from exc

    rows = await store.execute_traversal(
        ctx,
        pattern.query_template,
        bind_vars={"query": query, "as_of": as_of.isoformat(), "limit": limit},
    )

    hits: list[ArticleHit] = []
    for row in rows:
        version = row["version"]
        text = version.get("text") if isinstance(version, dict) else version.text
        if not passes_token_guard(query, text):
            continue
        hits.append(ArticleHit(**row))
    return hits
