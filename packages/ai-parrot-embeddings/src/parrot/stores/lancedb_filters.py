"""Typed predicate compiler for declared LanceDB metadata fields.

Pure string construction over a validated projection. Never interpolates an
unchecked identifier and never accepts a caller-supplied ``where`` expression.
"""
from __future__ import annotations

import math
from typing import Any

from parrot.stores.lancedb_models import (  # new in TASK-3059
    STANDARD_BOOL_FIELDS,
    STANDARD_STRING_FIELDS,
    LanceDBConfig,
)

PARENT_DOCUMENT_TYPES = ("parent", "parent_chunk")

_TYPE_NAMES = ("str", "bool", "int", "float")


class FilterCompilationError(ValueError):
    """Raised for unknown fields, bad operators, mixed lists or unsafe literals."""


def _declared_field_type(field: str, config: LanceDBConfig) -> str:
    """Resolve the declared type of a metadata field, or raise.

    Only fields the schema actually projects — the standard reserved
    fields, or explicitly declared ``config.metadata_fields`` — are valid
    filter targets. Everything else is "unknown" by construction, which is
    what makes an attacker-chosen field name harmless: it never reaches
    identifier compilation.
    """
    if field in STANDARD_STRING_FIELDS:
        return "str"
    if field in STANDARD_BOOL_FIELDS:
        return "bool"
    if field in config.metadata_fields:
        return config.metadata_fields[field]
    raise FilterCompilationError(f"Unknown or undeclared metadata field: {field!r}")


def _validate_scalar(field: str, field_type: str, value: Any) -> None:
    """Reject any value whose Python type does not match the declared type.

    ``bool`` is a subclass of ``int`` in Python — it is checked BEFORE the
    int/float cases so a boolean is never accepted where an integer is
    declared (spec: "booleans do not count as integers").
    """
    if isinstance(value, dict):
        raise FilterCompilationError(f"Nested filter objects are not supported for field {field!r}")
    if field_type == "bool":
        if not isinstance(value, bool):
            raise FilterCompilationError(f"Field {field!r} expects bool, got {type(value).__name__}")
        return
    if field_type == "str":
        if not isinstance(value, str):
            raise FilterCompilationError(f"Field {field!r} expects str, got {type(value).__name__}")
        return
    if field_type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise FilterCompilationError(f"Field {field!r} expects int, got {type(value).__name__}")
        return
    if field_type == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FilterCompilationError(f"Field {field!r} expects float, got {type(value).__name__}")
        if isinstance(value, float) and not math.isfinite(value):
            raise FilterCompilationError(f"Field {field!r} value must be finite")
        return
    raise FilterCompilationError(f"Unsupported declared field type {field_type!r} for {field!r}")  # pragma: no cover


def _quote_literal(value: Any) -> str:
    """Escape a scalar for inclusion in a predicate.

    Rejects NUL bytes and non-finite numbers rather than stringifying them
    — those must fail compilation, never silently become a matching (or
    non-matching) predicate.
    """
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FilterCompilationError("Non-finite numeric literal is not allowed")
        return repr(value)
    if isinstance(value, str):
        if "\x00" in value:
            raise FilterCompilationError("NUL byte is not allowed in a string literal")
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    raise FilterCompilationError(f"Unsupported literal type: {type(value).__name__}")


def _compile_field_clause(field: str, value: Any, config: LanceDBConfig) -> str:
    field_type = _declared_field_type(field, config)
    column = f"meta_{field}"

    if isinstance(value, list):
        if len(value) == 0:
            # Empty membership list matches nothing — NOT the same as an
            # unrestricted filter.
            return "(1 = 0)"
        if any(item is None for item in value):
            raise FilterCompilationError(f"Field {field!r}: membership list may not contain null")
        types_seen = {type(item) for item in value}
        # bool/int are distinct Python types but bool is an int subclass;
        # `type(item)` (not isinstance) keeps them from collapsing into one
        # "homogeneous" bucket, which is what "booleans do not count as
        # integers" requires here too.
        if len(types_seen) > 1:
            raise FilterCompilationError(f"Field {field!r}: membership list must be homogeneous")
        for item in value:
            _validate_scalar(field, field_type, item)
        literals = ", ".join(_quote_literal(item) for item in value)
        return f"{column} IN ({literals})"

    if value is None:
        return f"{column} IS NULL"

    _validate_scalar(field, field_type, value)
    return f"{column} = {_quote_literal(value)}"


def compile_metadata_filter(
    filters: dict[str, Any] | None,
    config: LanceDBConfig,
) -> str | None:
    """Compile a conjunctive predicate, or return None for no metadata restriction.

    Raises:
        FilterCompilationError: unknown field, undeclared operator, raw SQL,
            mixed-type list, list containing null, or a non-finite value.
    """
    if not filters:
        return None
    clauses = [_compile_field_clause(field, value, config) for field, value in filters.items()]
    return combine(*clauses)


def parent_exclusion_clause() -> str:
    """Predicate excluding parents unless ``include_parents=True``.

    A row is excluded when ``is_full_document`` is explicitly true, OR
    ``document_type`` is explicitly one of ``PARENT_DOCUMENT_TYPES``. Rows
    with MISSING (NULL) markers stay visible. An ``is_chunk=True`` marker
    is never consulted here, so it cannot override an explicit parent
    marker — this follows the base-class documentation
    (`packages/ai-parrot/src/parrot/stores/abstract.py:258`), not
    PostgreSQL's stricter marker implementation.
    """
    parent_types = ", ".join(_quote_literal(t) for t in PARENT_DOCUMENT_TYPES)
    return (
        "(meta_is_full_document IS NULL OR meta_is_full_document = FALSE) "
        f"AND (meta_document_type IS NULL OR meta_document_type NOT IN ({parent_types}))"
    )


def combine(*clauses: str | None) -> str | None:
    """AND-join the non-empty clauses, or return None when all are empty."""
    non_empty = [c for c in clauses if c]
    if not non_empty:
        return None
    return " AND ".join(f"({c})" for c in non_empty)
