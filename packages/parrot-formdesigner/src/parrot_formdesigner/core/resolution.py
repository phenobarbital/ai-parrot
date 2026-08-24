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
    from .constraints import FieldCondition, DependencyRule
    from .schema import FormField, FormSchema, FormSection


def resolve_rule_references(form: FormSchema) -> FormSchema:
    """Rewrite authored ``field_id`` rule references to ``field_uid``.

    Walks every field in the form (via ``iter_fields_recursive()``) and
    resolves ``depends_on`` conditions/operations and ``post_depends``
    entries (including their nested ``operation``) in place, then does the
    same for each ``FormSection.depends_on``. Mutates and returns the same
    ``form`` instance.

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
            ``field_id`` — or the owning section's ``section_id`` — and the
            offending reference.
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

    _check_embed_inverse_fields(form)

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
            # Already UID-shaped (idempotent re-run, or client-supplied) —
            # still must be validated against this form's known UIDs, same
            # as every other reference kind below. A pre-set field_uid is a
            # normal writable Pydantic field, so an unvalidated short-circuit
            # here would let a dangling/foreign reference smuggle straight
            # past resolution (code review finding, FEAT-393).
            if str(cond.field_uid) not in known_uids:
                raise ValueError(
                    f"Field {owner!r}: condition references unknown field_uid "
                    f"{cond.field_uid!r}"
                )
            return
        cond.field_uid = uuid.UUID(_uid_for(cond.field_id or "", owner, "condition"))

    def _resolve_rule(rule: DependencyRule, owner: str) -> None:
        """Resolve a rule's conditions, flat list AND nested groups.

        A condition inside ``groups`` is a condition like any other: left
        unresolved it keeps ``field_uid=None``, and ``_eval_condition``
        reads the answer through that uid, so the whole group silently
        never matches.
        """
        for c in rule.conditions:
            _resolve_condition(c, owner)
        for g in rule.groups or []:
            for c in g.conditions:
                _resolve_condition(c, owner)

    for f in form.iter_fields_recursive():
        if f.depends_on:
            _resolve_rule(f.depends_on, f.field_id)
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

    # Section rules need resolving too. They were skipped here for as long as
    # nothing evaluated them; now that RuleEvaluator gates a section's fields
    # on `FormSection.depends_on`, an unresolved section condition reads as
    # "never satisfied" and would hide the section forever.
    for section in form.sections:
        if not section.depends_on:
            continue
        _resolve_rule(section.depends_on, section.section_id)
        for op in section.depends_on.operations or []:
            op.operands = [
                _uid_for(o, section.section_id, "operation operand")
                for o in op.operands
            ]
            op.target = _uid_for(op.target, section.section_id, "operation target")

    return form


def _check_embed_inverse_fields(form: FormSchema) -> None:
    """Verify embed-mode relations' ``inverse_field`` exists (FEAT-456).

    Per-field Pydantic validators cannot see the whole form, so this check
    — that an embed-mode field's ``relation.inverse_field`` actually names
    a field inside its own ``item_template`` tree — happens here, at the
    same resolution boundary ``resolve_rule_references`` uses for rule
    references (spec §7 "inverse_field check placement").

    Args:
        form: The ``FormSchema`` to check.

    Raises:
        ValueError: If an embed-mode field's ``inverse_field`` does not
            name any field in its ``item_template`` tree. Names the owning
            ``field_id`` and the missing ``inverse_field``.
    """
    for f in form.iter_fields_recursive():
        relation = f.relation
        if relation is None or relation.mode != "embed":
            continue
        template_field_ids = (
            {t.field_id for t in walk_fields([f.item_template])}
            if f.item_template is not None
            else set()
        )
        if relation.inverse_field not in template_field_ids:
            raise ValueError(
                f"Field {f.field_id!r}: relation.inverse_field "
                f"{relation.inverse_field!r} does not name any field in "
                "this field's item_template"
            )


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
