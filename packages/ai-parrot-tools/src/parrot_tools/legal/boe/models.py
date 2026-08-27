"""Pydantic models for BOE consolidated-legislation records.

Defines the ``ArticleVersion`` shape (spec §2 Data Models,
``sdd/specs/legal-norms-graph-boe.spec.md``) and the ``ParsedNorm``
container returned by ``parse_consolidated``.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ArticleVersion(BaseModel):
    """One dated wording of a single BOE article.

    Args:
        n: 0-based version index within the article's version history,
            ordered by ``valid_from`` ascending.
        text: Full wording of the article as of this version, already
            normalized via ``hashing.normalize_for_hash`` (the stored
            text IS the normalized text — hash what you store, slice
            what you stored). Always ``None`` when ``kind ==
            "supresion"`` (the article carries no content as of this
            version).
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
        content_hash: sha256 hex digest (``hashing.seal_hash``) over the
            normalized ``text``. ``None`` iff ``text is None`` (FEAT-449
            R3/R11).
        hash_norm_version: Normalization contract version used to seal
            ``content_hash`` (``hashing.HASH_NORM_VERSION``). ``None``
            iff ``text is None``.
    """

    n: int
    text: str | None
    valid_from: date
    valid_to: date | None
    modified_by: str | None
    kind: Literal["redaccion", "adicion", "supresion"]
    source: Literal["boe_consolidada"]
    derived: bool
    content_hash: str | None = None
    hash_norm_version: int | None = None

    @model_validator(mode="after")
    def _validate_hash_presence(self) -> ArticleVersion:
        """Enforce ``text is None <=> content_hash is None <=> hash_norm_version is None``.

        Raises:
            ValueError: If ``text``, ``content_hash``, and
                ``hash_norm_version`` are not all ``None`` or all
                non-``None`` together (a "supresion" version carries no
                hash; every other version must carry a sealed hash).
        """
        has_text = self.text is not None
        has_hash = self.content_hash is not None
        has_norm_version = self.hash_norm_version is not None
        if not (has_text == has_hash == has_norm_version):
            raise ValueError(
                "ArticleVersion: text, content_hash, and hash_norm_version "
                "must be all None (supresion) or all set together — got "
                f"text={self.text!r} content_hash={self.content_hash!r} "
                f"hash_norm_version={self.hash_norm_version!r}"
            )
        return self


class ArticleHit(BaseModel):
    """One BM25 lexical-candidate hit from the ``search_articles`` pattern.

    Args:
        articulo_key: The composite articulo key (``{boe_id}:{numero}``).
        norma_ref: BOE id of the parent norma.
        numero: Article designator as it appears in the source.
        version: The in-force ``ArticleVersion`` for the queried ``as_of``.
        score: BM25 relevance score from the ArangoSearch view.
    """

    articulo_key: str
    norma_ref: str
    numero: str
    version: ArticleVersion
    score: float


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
