"""Pydantic models for BOE consolidated-legislation records.

Defines the ``ArticleVersion`` shape (spec §2 Data Models,
``sdd/specs/legal-norms-graph-boe.spec.md``) and the ``ParsedNorm``
container returned by ``parse_consolidated``.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class ArticleVersion(BaseModel):
    """One dated wording of a single BOE article.

    Args:
        n: 0-based version index within the article's version history,
            ordered by ``valid_from`` ascending.
        text: Full wording of the article as of this version. Always
            ``None`` when ``kind == "supresion"`` (the article carries no
            content as of this version).
        valid_from: Date this version came into force. Inclusive lower
            bound.
        valid_to: Date this version stopped being in force. Exclusive
            upper bound. ``None`` means this version is currently in
            force.
        modified_by: Canonical BOE id of the amending norm that produced
            this version. ``None`` for ``n == 0`` (the original
            enactment).
        kind: The nature of this version relative to the previous one.
        source: Always ``"boe_consolidada"`` for BOE-sourced versions.
        derived: Always ``False`` for BOE-sourced versions; reserved for
            the later CELLAR diff-derived path. Never set ``True`` here.
    """

    n: int
    text: str | None
    valid_from: date
    valid_to: date | None
    modified_by: str | None
    kind: Literal["redaccion", "adicion", "supresion"]
    source: Literal["boe_consolidada"]
    derived: bool


class ParsedNorm(BaseModel):
    """Result of parsing one BOE consolidated-legislation XML document.

    Args:
        norma: Flat, dict-serialisable record for the norma node
            (``boe_id``, ``titulo``, ``rango``, ``fecha_disposicion``,
            ``fecha_publicacion``). Empty when parsing fails before the
            norma metadata can be read.
        articulos: Flat, dict-serialisable records for each articulo
            node, each carrying ``articulo_key``, ``norma_ref``,
            ``numero`` and a fully-built ``versions`` list of
            ``ArticleVersion`` dicts (dates serialised as ISO
            ``YYYY-MM-DD`` strings).
        relations: ``modifica`` / ``deroga`` relation records extracted
            from the norm's analisis metadata and per-article version
            history. Each entry: ``{"type": "modifica"|"deroga",
            "from": <boe_id>, "to": <boe_id or articulo_key>}``.
        errors: Structured parse errors. Non-empty on malformed or
            structurally incomplete input; never silently discarded in
            favour of an empty record.
    """

    norma: dict[str, Any] = Field(default_factory=dict)
    articulos: list[dict[str, Any]] = Field(default_factory=list)
    relations: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
