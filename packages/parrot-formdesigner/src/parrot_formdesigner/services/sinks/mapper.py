"""Submission mapper — tabular flattening and document nesting.

Turns a :class:`~parrot_formdesigner.services.submissions.FormSubmission`
into what a sink actually stores. Two modes, selected by the sink's data
family (spec section 8, resolved):

- **Tabular** (``postgres_table``, ``csv_file``, ``gsheet``, and the
  ``bigquery`` ``asyncdb`` driver): one flat row per submission. A scalar
  field becomes a column named after its ``field_id``; a ``GROUP`` field
  flattens recursively as ``parent__child``; an ``ARRAY`` field becomes
  exactly ONE column holding a JSON-serialized value; declared
  :class:`~parrot_formdesigner.core.schema.FormMetadataField` keys become
  their own columns; the reserved submission columns are always present.
- **Document** (Mongo / Arango ``asyncdb`` drivers): one document per
  submission, with ``data`` stored nested and unflattened, plus the
  reserved fields — flattening a document store loses structure for no
  benefit.

Pure functions only: no I/O, no sink, no storage code imported here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from parrot_formdesigner.core.schema import (
    FormField,
    FormSchema,
    FormSubsection,
    SectionItem,
)
from parrot_formdesigner.core.types import FieldType
from parrot_formdesigner.services._identifiers import validate_identifier
from parrot_formdesigner.services.submissions import FormSubmission

# Path-flattening separator for GROUP fields. Exactly "__" so the result
# stays a valid Postgres identifier under `_IDENTIFIER_RE`.
_SEP = "__"

# Reserved columns every sink writes, sourced from `FormSubmission`
# attributes (services/submissions.py:50) — never from the form itself.
RESERVED_COLUMNS: frozenset[str] = frozenset(
    {
        "submission_id",
        "form_uid",
        "form_id",
        "form_version",
        "created_at",
        "tenant",
        "user_id",
        "username",
        "org_id",
        "submitted_at",
        "ip",
        "user_agent",
        "locale",
        "root_submission_id",
        "revision",
        "context",
    }
)

# Deterministic emission order for the reserved columns.
_RESERVED_COLUMN_ORDER: tuple[str, ...] = (
    "submission_id",
    "form_uid",
    "form_id",
    "form_version",
    "created_at",
    "tenant",
    "user_id",
    "username",
    "org_id",
    "submitted_at",
    "ip",
    "user_agent",
    "locale",
    "root_submission_id",
    "revision",
    "context",
)


def _reserved_values(submission: FormSubmission) -> dict[str, Any]:
    """Return the reserved-column values sourced from ``submission``.

    Args:
        submission: The submission whose reserved attributes to read.

    Returns:
        A dict with every key in :data:`RESERVED_COLUMNS`.
    """
    return {name: getattr(submission, name) for name in _RESERVED_COLUMN_ORDER}


def _walk_tabular(
    items: list[SectionItem], prefix: str = ""
) -> Iterator[tuple[str, FormField]]:
    """Yield ``(column_name, field)`` pairs for tabular flattening.

    ``GROUP`` fields recurse into their ``children`` with a path prefix
    joined by :data:`_SEP`; every other field type (including ``ARRAY``,
    which is never expanded) yields exactly one ``(name, field)`` pair.
    ``FormSubsection`` items are transparently walked.

    Args:
        items: A section's ``fields`` list (``FormField`` and/or
            ``FormSubsection``).
        prefix: The path prefix accumulated so far.

    Yields:
        ``(column_name, field)`` tuples, one per emitted column.

    Raises:
        ValueError: If a flattened column name exceeds the 63-character
            Postgres identifier cap.
    """
    for item in items:
        if isinstance(item, FormSubsection):
            yield from _walk_tabular(item.fields, prefix)
            continue

        field = item
        name = f"{prefix}{_SEP}{field.field_id}" if prefix else field.field_id

        if field.field_type == FieldType.GROUP and field.children:
            yield from _walk_tabular(field.children, name)
        else:
            validate_identifier(name, kind="flattened column name")
            yield name, field


def _iter_form_fields(form: FormSchema) -> Iterator[tuple[str, FormField]]:
    """Yield ``(column_name, field)`` pairs for every section in ``form``."""
    for section in form.sections:
        yield from _walk_tabular(list(section.fields))


def flatten_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]:
    """Flatten ``submission`` into a single tabular row.

    Args:
        form: The form that produced ``submission`` (used to walk the
            field tree and any declared metadata).
        submission: The submission to flatten.

    Returns:
        A flat dict: reserved columns, then one entry per form field
        (``GROUP`` -> ``parent__child``, ``ARRAY`` -> one JSON-serialized
        column), then one entry per declared metadata key.

    Raises:
        ValueError: If a flattened column name is not a valid identifier
            (e.g. exceeds the 63-character Postgres cap).
    """
    row: dict[str, Any] = _reserved_values(submission)

    data = submission.data
    for column_name, field in _iter_form_fields(form):
        row[column_name] = _extract_value(data, column_name, field)

    if form.metadata:
        for meta_field in form.metadata:
            if meta_field.key in data:
                row[meta_field.key] = data[meta_field.key]

    return row


def _extract_value(
    data: dict[str, Any], column_name: str, field: FormField
) -> Any:
    """Extract the value for ``column_name`` from a submission's ``data``.

    ``ARRAY`` values are JSON-serialized into a single column. Nested
    ``GROUP`` values are looked up by walking the path segments of
    ``column_name`` (split on :data:`_SEP`) against nested dicts in
    ``data``; if the submitted data is not itself nested (e.g. it was
    submitted flat, matching ``column_name`` directly), that flat key is
    used instead.

    Args:
        data: The submission's raw ``data`` dict.
        column_name: The flattened column name (may contain ``__``).
        field: The schema field this column corresponds to.

    Returns:
        The extracted value, JSON-serialized if ``field`` is an ``ARRAY``.
    """
    if column_name in data:
        value = data[column_name]
    else:
        # Fall back to walking nested dicts by path segment.
        segments = column_name.split(_SEP)
        cursor: Any = data
        for segment in segments:
            if isinstance(cursor, dict) and segment in cursor:
                cursor = cursor[segment]
            else:
                cursor = None
                break
        value = cursor

    if field.field_type == FieldType.ARRAY:
        return json.dumps(value)
    return value


def nest_submission(form: FormSchema, submission: FormSubmission) -> dict[str, Any]:
    """Build a document-mode record: reserved fields + nested ``data``.

    Args:
        form: The form that produced ``submission`` (unused for nesting,
            kept for a symmetric signature with :func:`flatten_submission`).
        submission: The submission to nest.

    Returns:
        A dict with every reserved column plus a ``"data"`` key holding
        ``submission.data`` exactly as submitted (a shallow copy, so the
        caller's ``submission.data`` is never mutated).
    """
    del form  # unused — document mode keeps `data` nested regardless of shape
    doc: dict[str, Any] = _reserved_values(submission)
    doc["data"] = dict(submission.data)
    return doc


def column_names_for(form: FormSchema) -> list[str]:
    """Return the ordered, deterministic tabular column set for ``form``.

    Used by ``ensure_target()`` to compute the additive column set: the
    reserved columns first (in a fixed order), then one column per form
    field (in schema order), then one column per declared metadata key.

    Args:
        form: The form whose tabular column set to compute.

    Returns:
        The ordered list of column names.
    """
    names: list[str] = list(_RESERVED_COLUMN_ORDER)
    names.extend(name for name, _field in _iter_form_fields(form))
    if form.metadata:
        names.extend(meta_field.key for meta_field in form.metadata)
    return names
