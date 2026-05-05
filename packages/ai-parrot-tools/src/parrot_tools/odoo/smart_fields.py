"""Smart field selection heuristic for OdooToolkit.

When an agent omits ``fields`` in ``search_records`` or ``get_record``, Odoo
returns every field on the model — including binary blobs, HTML columns, audit
timestamps, and dozens of technical relational fields that flood the LLM context
with irrelevant noise.

This module provides :func:`select_smart_fields`, a **pure function** (no I/O,
no async) that scores a ``fields_get`` metadata dict and returns the top N most
"agent-useful" field names.

Inspired by the ``tuanle96/mcp-odoo`` project's scoring heuristic.
"""
from __future__ import annotations

from typing import Any

# ── Constants ────────────────────────────────────────────────────────────────

# Fields that are always emitted regardless of score (don't count against cap)
_ALWAYS_INCLUDE: tuple[str, ...] = ("id", "display_name")

# Field types that are never useful to an LLM — skip entirely
SKIP_FIELD_TYPES: frozenset[str] = frozenset({"binary", "html"})

# Technical field names that score low (audit / internal Odoo plumbing)
TECHNICAL_FIELD_NAMES: frozenset[str] = frozenset({
    "create_uid",
    "write_uid",
    "create_date",
    "write_date",
    "__last_update",
})

# Field-name substrings that indicate high-value agent fields
HIGH_VALUE_PATTERNS: tuple[str, ...] = (
    "name",
    "state",
    "status",
    "date",
    "amount",
    "email",
    "phone",
    "partner_id",
    "user_id",
    "reference",
    "description",
    "number",
)

# Base score by field type
_TYPE_SCORES: dict[str, float] = {
    "char": 10.0,
    "selection": 10.0,
    "many2one": 10.0,
    "float": 7.0,
    "integer": 7.0,
    "monetary": 7.0,
    "date": 5.0,
    "datetime": 5.0,
    "one2many": 4.0,
    "many2many": 4.0,
    "text": 3.0,
    "boolean": 3.0,
}

_HIGH_VALUE_BONUS: float = 5.0
_TECHNICAL_PENALTY: float = -8.0
_MESSAGE_PENALTY: float = -10.0


# ── Scoring ──────────────────────────────────────────────────────────────────


def _smart_field_score(field_name: str, field_meta: dict[str, Any]) -> float:
    """Return a heuristic usefulness score for a single Odoo field.

    Args:
        field_name: Technical field name (e.g. ``"partner_id"``).
        field_meta: The field's metadata dict from ``fields_get`` (must contain
            at minimum a ``"type"`` key).

    Returns:
        A float score; higher is more useful to an LLM agent.  Negative scores
        indicate fields that should be excluded when space is tight.
    """
    field_type: str = field_meta.get("type", "")

    # Skip types always return a sentinel so callers can filter
    if field_type in SKIP_FIELD_TYPES:
        return float("-inf")

    # Base score from type
    score: float = _TYPE_SCORES.get(field_type, 1.0)

    # Technical-field penalty
    if field_name in TECHNICAL_FIELD_NAMES:
        score += _TECHNICAL_PENALTY

    # message_* fields are internal Odoo chatter internals
    if field_name.startswith("message_"):
        score += _MESSAGE_PENALTY

    # Bonus for high-value field-name patterns
    lower_name = field_name.lower()
    if any(pattern in lower_name for pattern in HIGH_VALUE_PATTERNS):
        score += _HIGH_VALUE_BONUS

    # Boost required fields slightly (they're important by definition)
    if field_meta.get("required"):
        score += 2.0

    return score


# ── Public API ───────────────────────────────────────────────────────────────


def select_smart_fields(
    fields_metadata: dict[str, Any],
    max_fields: int = 15,
    always_include: list[str] | None = None,
) -> list[str]:
    """Select the most LLM-useful fields from an Odoo ``fields_get`` response.

    Args:
        fields_metadata: Mapping of ``field_name → field_meta_dict`` as returned
            by ``fields_get``.  Each value must contain at minimum a ``"type"``
            key.
        max_fields: Maximum number of *scored* fields to include (excludes
            ``id``, ``display_name``, and any entries in ``always_include``).
            Defaults to 15.
        always_include: Extra field names to always include regardless of score.
            These don't count against ``max_fields``.

    Returns:
        Sorted list of field names.  ``id`` and ``display_name`` come first
        (if they exist in the metadata), followed by the top-scoring fields in
        descending score order.  Binary/HTML fields are never included.

    Example::

        meta = await toolkit.fields_get("res.partner")
        fields = select_smart_fields(meta, max_fields=10)
        # ["id", "display_name", "name", "email", "phone", ...]
    """
    if not fields_metadata:
        return list(_ALWAYS_INCLUDE)

    # Build the set of pinned fields (always include, no cap)
    pinned: set[str] = set(_ALWAYS_INCLUDE)
    if always_include:
        pinned.update(always_include)

    # Score every field that is not pinned
    scored: list[tuple[float, str]] = []
    for fname, fmeta in fields_metadata.items():
        if fname in pinned:
            continue
        s = _smart_field_score(fname, fmeta)
        if s > float("-inf"):  # skip binary/html sentinels
            scored.append((s, fname))

    # Sort descending by score, then alphabetically for stable output
    scored.sort(key=lambda t: (-t[0], t[1]))

    top_fields = [fname for _, fname in scored[:max_fields]]

    # Build result: pinned fields that actually exist in metadata come first
    result_pinned = [f for f in _ALWAYS_INCLUDE if f in fields_metadata or f == "id" or f == "display_name"]
    # Add extra always_include fields (preserving order, deduplicating)
    if always_include:
        for f in always_include:
            if f not in result_pinned:
                result_pinned.append(f)

    return result_pinned + top_fields


__all__ = [
    "select_smart_fields",
    "_smart_field_score",
    "SKIP_FIELD_TYPES",
    "TECHNICAL_FIELD_NAMES",
    "HIGH_VALUE_PATTERNS",
]
