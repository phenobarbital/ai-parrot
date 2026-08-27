"""Librarian answer-layer contracts (FEAT-449 §2 Data Models, R1-R5, R12).

Two families of models:

- **Final contracts** (``SpanRef``, ``ConflictNote``, ``ReadingNote``,
  ``LegalAnswer``, ``SuppressionRecord``, ``PayloadEntry``) — the sealed,
  verified shapes that leave the ``SpanVerifier`` (``verifier.py``).
- **Draft contracts** (``DraftSpan``, ``DraftReadingNote``,
  ``DraftConflictNote``, ``DraftAnswer``) — what
  ``LegalLibrarianAgent.ask(structured_output=DraftAnswer)`` actually
  emits.

The load-bearing asymmetry: **the LLM never emits offsets**. It emits a
``payload_key`` (from the enumerated dossier) and a verbatim ``quote``; the
``SpanVerifier`` locates the quote deterministically via ``str.find`` and
derives ``start``/``end`` itself. Offsets from a stochastic source would
defeat the existence gate (R2) — any design that has the LLM produce
``start``/``end`` integers directly is implementing the spec wrong.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_DISCLAIMER = (
    "Esta respuesta se basa exclusivamente en los fragmentos citados del "
    "corpus BOE indexado; no constituye asesoramiento legal ni sustituye "
    "la consulta de un profesional."
)
"""Constant default disclaimer text for ``LegalAnswer.disclaimer``."""


class SpanRef(BaseModel):
    """One verified, span-anchored citation into the primary payload.

    Args:
        kind: The kind of source document this span indexes into
            (``"sentencia"`` joins in Sprint 3 — out of scope here).
        id: BOE id (``kind="norma"``) or ``articulo_key`` (``kind="articulo"``).
        version_n: The articulo version the span indexes into. ``None``
            for ``kind="norma"`` spans (norm-level citations have no
            version).
        start: Half-open lower char offset into the stored, normalized
            payload of ``(id, version_n)``.
        end: Half-open upper char offset (exclusive).
        quote: Verbatim text; MUST equal ``payload[start:end]`` exactly.
        content_hash: sha256 of the stored normalized payload this span
            was verified against.
        hash_norm_version: Normalization contract version used to seal
            ``content_hash``.
        title: Human-readable title (e.g. ``"{norma_ref} art. {numero}"``).
        url: boe.es permalink for the source.
        as_of: Date used to resolve ``version_n``. ``None`` for
            traversal-derived spans not tied to a specific date.
        basis: Whether this span came from lexical retrieval or graph
            traversal.
    """

    kind: Literal["norma", "articulo"]
    id: str
    version_n: int | None
    start: int
    end: int
    quote: str
    content_hash: str
    hash_norm_version: int
    title: str
    url: str
    as_of: date | None
    basis: Literal["retrieval", "traversal"]


def span_key(ref: SpanRef) -> str:
    """Compute the deduplication/anchor key for a ``SpanRef``.

    Args:
        ref: The span reference.

    Returns:
        ``"{id}:{version_n}:{start}-{end}"``.
    """
    return f"{ref.id}:{ref.version_n}:{ref.start}-{ref.end}"


class ConflictNote(BaseModel):
    """A flagged (never resolved) conflict between two surviving spans (R5).

    Args:
        span_a: ``span_key`` of the first conflicting span.
        span_b: ``span_key`` of the second conflicting span.
        note: Free-text description of the conflict. The librarian may
            flag conflicts but must NEVER resolve them.
    """

    span_a: str
    span_b: str
    note: str


class ReadingNote(BaseModel):
    """One sentence of the reading guide, anchored to ≥1 surviving span.

    Args:
        text: Exactly one sentence.
        spans: ``span_key`` anchors from the dossier. Must be non-empty —
            an unanchorable sentence is removed by the verifier, not
            represented here with an empty list.
        basis: Whether this note was assembled deterministically (e.g.
            traversal-derived context) or produced by the LLM.
    """

    text: str
    spans: list[str] = Field(min_length=1)
    basis: Literal["deterministic", "llm"]


class LegalAnswer(BaseModel):
    """The final, span-verified answer (R2, R4, R12).

    Args:
        as_of: The date used to resolve retrieval, always stated back.
        materias: Materias searched.
        dossier: PRIMARY payload — precedence-ordered, deduplicated,
            verified ``SpanRef``s.
        reading_order: ``span_key`` values suggesting which spans to
            read first.
        conflicts: Flagged (unresolved) conflicts between surviving spans.
        reading_guide: SECONDARY — anchored reading notes, or absent.
        not_found: Corpus-scoped absence statements (never ontological —
            "no encontré en el corpus", never "no existe tal ley").
        suppressed_count: Number of fail-closed prunes performed (R4).
        disclaimer: Standing disclaimer text.
    """

    as_of: date
    materias: list[str] = Field(default_factory=list)
    dossier: list[SpanRef] = Field(default_factory=list)
    reading_order: list[str] = Field(default_factory=list)
    conflicts: list[ConflictNote] = Field(default_factory=list)
    reading_guide: list[ReadingNote] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
    suppressed_count: int = 0
    disclaimer: str = DEFAULT_DISCLAIMER


class SuppressionRecord(BaseModel):
    """Append-only record of a fail-closed prune (R2, R4).

    Persisted into the ``span_suppressions`` collection (FEAT-449 M3/M4)
    via ``SuppressionLog.append`` — never updated, never deleted.

    Args:
        execution_id: The librarian flow execution this record belongs to.
        suppressed_text: The sentence/note text that was suppressed.
        claimed_anchors: The payload/span keys the suppressed text
            claimed as anchors.
        reason: Why the span/sentence was suppressed.
        user_id: User attributed to the execution, when known.
        created_at: When the suppression was recorded.
    """

    execution_id: str
    suppressed_text: str
    claimed_anchors: list[str] = Field(default_factory=list)
    reason: Literal[
        "span_not_found", "hash_mismatch", "quote_mismatch", "anchor_lost", "atom_contradicted"
    ]
    user_id: str | None = None
    created_at: datetime


class PayloadEntry(BaseModel):
    """One retrievable payload the librarian may cite from (dossier_build).

    Args:
        payload_key: ``"{articulo_key}:{version_n}"``.
        payload: Stored, NORMALIZED version text (the exact text the
            hash was sealed over — hash what you store, slice what you
            stored).
        content_hash: Carried from the stored record; the verifier
            recomputes and compares — this field is NOT recomputed here.
        title: ``"{norma_ref} art. {numero}"``.
        url: ``https://www.boe.es/buscar/act.php?id={norma_ref}``.
        as_of: Date used to resolve this entry's in-force version.
        version_n: The articulo version this entry represents.
        articulo_key: The composite articulo key.
        basis: Whether this entry came from lexical retrieval or graph
            traversal.
    """

    payload_key: str
    payload: str
    content_hash: str
    title: str
    url: str
    as_of: date
    version_n: int
    articulo_key: str
    basis: Literal["retrieval", "traversal"]


class DraftSpan(BaseModel):
    """LLM-facing span citation — payload key + verbatim quote ONLY.

    The verifier locates the quote deterministically (``str.find``) and
    derives ``start``/``end`` itself. The LLM NEVER emits offsets.

    Args:
        payload_key: ``"{id}:{version_n}"`` from the enumerated dossier.
        quote: Verbatim text the librarian cites.
    """

    payload_key: str
    quote: str


class DraftReadingNote(BaseModel):
    """LLM-facing draft of one reading-guide sentence.

    Args:
        text: Exactly one sentence.
        spans: Draft span citations anchoring this sentence.
        basis: Whether this note is deterministic or LLM-produced.
    """

    text: str
    spans: list[DraftSpan] = Field(min_length=1)
    basis: Literal["deterministic", "llm"]


class DraftConflictNote(BaseModel):
    """LLM-facing draft of a flagged conflict between two draft spans.

    Args:
        span_a: First conflicting draft span.
        span_b: Second conflicting draft span.
        note: Free-text description of the conflict.
    """

    span_a: DraftSpan
    span_b: DraftSpan
    note: str


class DraftAnswer(BaseModel):
    """The structured output the librarian LLM call emits.

    ``LegalLibrarianAgent.ask(structured_output=DraftAnswer)`` — the
    ``SpanVerifier`` turns this into the final, sealed ``LegalAnswer``.

    Args:
        reading_order: Payload keys, librarian's suggested reading order.
        conflicts: Draft conflict notes.
        reading_guide: Draft reading-guide sentences.
        not_found: Corpus-scoped absence statements.
    """

    reading_order: list[str] = Field(default_factory=list)
    conflicts: list[DraftConflictNote] = Field(default_factory=list)
    reading_guide: list[DraftReadingNote] = Field(default_factory=list)
    not_found: list[str] = Field(default_factory=list)
