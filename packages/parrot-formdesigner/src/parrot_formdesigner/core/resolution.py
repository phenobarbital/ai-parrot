"""Build-time rule-reference resolution (FEAT-393, Module 3).

Rules stay AUTHORED by ``field_id`` (humans, YAML, LLM) but are STORED as
``field_uid`` references — the stable, immutable identity introduced by
Module 2 (``core/schema.py``). This module provides the shared resolution
pass that rewrites authored ``field_id`` references to ``field_uid`` at
every build boundary (extractors, ``CreateFormTool``, blank-form and edit
APIs), plus the canonical UID lookup helpers those and later modules
consume.

Resolution is idempotent by construction: a reference that is already
UID-shaped (and known) validates and passes through unchanged, so re-running
``resolve_rule_references`` on an already-resolved form is a no-op.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from .schema import walk_fields

if TYPE_CHECKING:
    from .constraints import FieldCondition
    from .schema import FormField, FormSchema, FormSection


def resolve_rule_references(form: FormSchema) -> FormSchema:
    """Rewrite authored ``field_id`` rule references to ``field_uid``.

    Walks every field in the form (via ``iter_fields_recursive()``) and
    resolves ``depends_on`` conditions/operations and ``post_depends``
    entries (including their nested ``operation``) in place. Mutates and
    returns the same ``form`` instance.

    Idempotent: a reference that already parses as a UUID is validated
    against the form's known UIDs and passed through unchanged — running
    this twice on the same form produces identical rule references.

    Args:
        form: The ``FormSchema`` whose rules should be resolved.

    Returns:
        The same ``form`` instance, with rule references rewritten.

    Raises:
        ValueError: If a rule references a duplicate ``field_id`` (the form
            itself is ambiguous), or references an unknown/empty
            ``field_id``/``field_uid``. The error names the owning field's
            ``field_id`` and the offending reference.
    """
    by_fid: dict[str, FormField] = {}
    for f in form.iter_fields_recursive():
        if f.field_id in by_fid:
            raise ValueError(
                f"Cannot resolve rules: duplicate field_id {f.field_id!r} "
                f"in form {form.form_id!r}"
            )
        by_fid[f.field_id] = f
    known_uids = {str(f.field_uid) for f in by_fid.values()}

    def _uid_for(ref: str, owner: str, kind: str) -> str:
        if not ref:
            raise ValueError(f"Field {owner!r}: {kind} has an empty field reference")
        try:
            parsed = str(uuid.UUID(ref))  # already a UID (idempotent re-run)
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed not in known_uids:
                raise ValueError(
                    f"Field {owner!r}: {kind} references unknown field_uid {ref!r}"
                )
            return parsed
        if ref not in by_fid:
            raise ValueError(
                f"Field {owner!r}: {kind} references unknown field_id {ref!r}"
            )
        return str(by_fid[ref].field_uid)

    def _resolve_condition(cond: FieldCondition, owner: str) -> None:
        if (cond.source or "field") != "field":
            return  # location_variable / visit_context: key-based, no field ref
        if cond.field_uid is not None:
            return  # already resolved
        cond.field_uid = uuid.UUID(_uid_for(cond.field_id or "", owner, "condition"))

    for f in form.iter_fields_recursive():
        if f.depends_on:
            for c in f.depends_on.conditions:
                _resolve_condition(c, f.field_id)
            for op in f.depends_on.operations or []:
                op.operands = [
                    _uid_for(o, f.field_id, "operation operand") for o in op.operands
                ]
                op.target = _uid_for(op.target, f.field_id, "operation target")
        for post in f.post_depends or []:
            post.target = _uid_for(post.target, f.field_id, "post_depends target")
            for c in post.conditions or []:
                _resolve_condition(c, f.field_id)
            if post.operation:
                post.operation.operands = [
                    _uid_for(o, f.field_id, "post operation operand")
                    for o in post.operation.operands
                ]
                post.operation.target = _uid_for(
                    post.operation.target, f.field_id, "post operation target"
                )
    return form


def find_field_by_uid(
    form: FormSchema, field_uid: uuid.UUID
) -> tuple[FormField, FormSection] | None:
    """Form-wide, subsection- and nesting-aware field lookup by UID.

    The canonical replacement for ``api/operations.py``'s ``_field_index``
    (which skips subsections) and ``tools/edit_toolkit.py``'s
    ``_find_field_and_section`` traversal (FEAT-393).

    Args:
        form: The ``FormSchema`` to search.
        field_uid: The ``field_uid`` to look up.

    Returns:
        A ``(field, section)`` tuple for the first match, or ``None`` if no
        field with this ``field_uid`` exists anywhere in the form.
    """
    for section in form.sections:
        for f in walk_fields(section.fields):
            if f.field_uid == field_uid:
                return f, section
    return None


def resolve_answer(
    form: FormSchema, field_uid: uuid.UUID, answers: dict[str, Any]
) -> Any:
    """Read an answer value for a UID-referenced field from a
    ``field_id``-keyed answers dict.

    Args:
        form: The ``FormSchema`` the UID reference belongs to.
        field_uid: The resolved ``field_uid`` to read an answer for.
        answers: The submission/answers mapping, keyed by ``field_id``
            (unchanged wire shape — FEAT-393 only moves internal rule
            storage to UIDs, not the answers contract).

    Returns:
        The answer value for the field's current ``field_id``, or ``None``
        if the field is not found or has no answer.
    """
    found = find_field_by_uid(form, field_uid)
    return answers.get(found[0].field_id) if found else None
