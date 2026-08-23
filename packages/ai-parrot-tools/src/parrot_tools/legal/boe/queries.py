"""Typed wrapper around the ``article_in_force`` declarative traversal pattern.

The resolution *logic* — which wording was in force on a given date — lives
entirely in the AQL ``query_template`` declared in ``legal.ontology.yaml``
(TASK-2371). This module is pure ergonomics: binding, calling
``OntologyGraphStore.execute_traversal``, and deserialising the result. It
does not re-implement version selection in Python — that would duplicate
the pattern and violate spec goal G4 (declarative-first temporal
resolution).
"""
from __future__ import annotations

from datetime import date

from parrot.knowledge.ontology.graph_store import OntologyGraphStore
from parrot.knowledge.ontology.schema import TenantContext

from .models import ArticleVersion

_PATTERN_NAME = "article_in_force"


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
