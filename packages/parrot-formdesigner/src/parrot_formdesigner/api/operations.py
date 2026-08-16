"""``PATCH /api/v1/forms/{form_uid}/operations`` — atomic batched-edit endpoint.

Per FEAT-152 §2 Internal Behavior:

1. Parse the ``OperationsEnvelope`` from the body (Pydantic discriminated
   union over ``op``).
2. Optionally honour ``If-Match: <version>`` (Q1: optimistic concurrency).
3. Apply ops sequentially on a Pydantic-deep-copied working form.
4. On any per-op failure → 422 with the offending op's ``index`` + name.
5. Run ``FormValidator.check_schema`` on the working copy → 422 if errors.
6. Bump the form version via ``_bump_version``.
7. Persist via ``registry.register(working_copy, persist=True, overwrite=True)``.
8. Return 200 with ``{"form": working_copy.model_dump()}``.

Per Q2 (resolved): the existing PUT (``update_form``) and RFC-7396 PATCH
(``patch_form``) endpoints stay alongside this — full-replace and
merge-patch use cases differ from granular UI edits.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated, Any, Literal

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.resolution import resolve_rule_references
from ..core.schema import (
    FormField,
    FormSchema,
    FormSection,
    FormSubsection,
    walk_fields,
)
from ..services.validators import FormValidator
from ._utils import _bump_version, _deep_merge, _get_request_tenant
from .handlers import extract_form_uid

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic discriminated-union envelope
# ---------------------------------------------------------------------------


class _OpBase(BaseModel):
    """Base type for all edit operations.

    Subclasses set ``op`` to a string literal — Pydantic uses ``op`` as the
    discriminator field on the union ``Operation``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AddSection(_OpBase):
    """Insert a new section. Optional ``position`` indexes the section list."""

    op: Literal["add_section"]
    section: FormSection
    position: int | None = None


class AddField(_OpBase):
    """Insert a new field into an existing section.

    ``field`` may carry a client-supplied ``field_uid`` (upsert origin);
    when omitted, ``FormField``'s ``default_factory`` mints a fresh one.
    Rejected if it (or ``field.field_id``) already exists anywhere in the
    form (FEAT-393 — per-FORM uniqueness, not per-section).

    Example (wire body)::

        {"op": "add_field", "section_uid": "3c3b0847-56fb-493f-bb84-2554b502a31e",
         "field": {"field_id": "phone", "field_type": "text", "label": "Phone"}}
    """

    op: Literal["add_field"]
    section_uid: uuid.UUID
    field: FormField
    position: int | None = None


class MoveField(_OpBase):
    """Move a field across (or within) sections.

    ``from`` is a Python keyword, so the wire field is aliased to ``from_``.
    Set ``model_config = ConfigDict(populate_by_name=True)`` so both the
    alias and the field name are accepted.

    Example (wire body)::

        {"op": "move_field",
         "from": {"section_uid": "...", "field_uid": "..."},
         "to": {"section_uid": "...", "position": 0}}
    """

    op: Literal["move_field"]
    from_: dict = Field(alias="from")
    to: dict


class RemoveField(_OpBase):
    """Remove a field from a section (or subsection).

    Example (wire body)::

        {"op": "remove_field", "section_uid": "...", "field_uid": "..."}
    """

    op: Literal["remove_field"]
    section_uid: uuid.UUID
    field_uid: uuid.UUID


class UpdateField(_OpBase):
    """Apply RFC 7396 merge-patch to a single field, addressed by UID.

    ``patch`` may rename ``field_id`` (subject to per-form uniqueness);
    a patch touching ``field_uid`` is rejected — the identity is immutable.

    Example (wire body)::

        {"op": "update_field", "section_uid": "...", "field_uid": "...",
         "patch": {"label": "New Label"}}
    """

    op: Literal["update_field"]
    section_uid: uuid.UUID
    field_uid: uuid.UUID
    patch: dict[str, Any]


class UpdateSectionMeta(_OpBase):
    """Apply RFC 7396 merge-patch to a section's metadata.

    Example (wire body)::

        {"op": "update_section_meta", "section_uid": "...", "patch": {"collapsed": true}}
    """

    op: Literal["update_section_meta"]
    section_uid: uuid.UUID
    patch: dict[str, Any]


class UpdateFormMeta(_OpBase):
    """Apply RFC 7396 merge-patch to the form-level meta."""

    op: Literal["update_form_meta"]
    patch: dict[str, Any]


class DuplicateField(_OpBase):
    """Duplicate a field within the same (or another) section.

    The clone always gets a fresh, server-minted ``field_uid`` — never the
    source's. ``as_field_id`` becomes the clone's new editable key.

    Example (wire body)::

        {"op": "duplicate_field",
         "from": {"section_uid": "...", "field_uid": "..."},
         "as_field_id": "phone_2"}
    """

    op: Literal["duplicate_field"]
    from_: dict = Field(alias="from")
    as_field_id: str


Operation = Annotated[
    AddSection | AddField | MoveField | RemoveField | UpdateField | UpdateSectionMeta | UpdateFormMeta | DuplicateField,
    Field(discriminator="op"),
]


class OperationsEnvelope(BaseModel):
    """Top-level body shape for ``PATCH .../operations``."""

    model_config = ConfigDict(extra="forbid")

    operations: list[Operation]


# ---------------------------------------------------------------------------
# OperationError — raised by per-op apply functions on validation failure.
# ---------------------------------------------------------------------------


class OperationError(Exception):
    """Per-op apply failure carried back to the HTTP layer.

    Attributes:
        index: 0-based index of the failing op within the envelope.
        op_name: Discriminator value (e.g., ``"add_field"``).
        message: Human-readable reason.
    """

    def __init__(self, index: int, op_name: str, message: str) -> None:
        self.index = index
        self.op_name = op_name
        self.message = message
        super().__init__(f"op[{index}] ({op_name}): {message}")


# ---------------------------------------------------------------------------
# Per-op apply functions (pure — operate on a Pydantic deep copy)
# ---------------------------------------------------------------------------


def _section_index(form: FormSchema, section_id: str) -> int:
    for i, sec in enumerate(form.sections):
        if sec.section_id == section_id:
            return i
    raise OperationError(-1, "?", f"section '{section_id}' not found")


def _section_index_by_uid(form: FormSchema, section_uid: uuid.UUID) -> int:
    """Locate a section's index by its immutable ``section_uid`` (FEAT-393).

    Args:
        form: The form to search.
        section_uid: The section's UID.

    Returns:
        0-based index of the section within ``form.sections``.

    Raises:
        OperationError: If no section with this ``section_uid`` exists.
    """
    for i, sec in enumerate(form.sections):
        if sec.section_uid == section_uid:
            return i
    raise OperationError(-1, "?", f"section '{section_uid}' not found")


def _locate_field(
    section: FormSection, field_uid: uuid.UUID
) -> tuple[list, int]:
    """Locate a field by ``field_uid`` within a section (FEAT-393).

    Searches the section's own top-level ``FormField`` items, every
    subsection's fields, and recursively through GROUP ``children`` at
    any nesting depth — replaces ``_field_index``, which silently
    skipped subsection items. (Code review follow-up: the ``children``
    recursion closes a gap where a field nested in a GROUP was
    unreachable by any batched edit operation — remove_field/
    update_field/move_field/duplicate_field — even though EditToolkit's
    equivalent tools already reached it via ``find_field_by_uid``.)

    NOT extended to ARRAY ``item_template``: it is a single field (not a
    list member it could be spliced out of), so remove/move/duplicate
    semantics don't apply to it the way they do to a list item — only
    read paths (``find_field_by_uid``) address it.

    Args:
        section: The section to search.
        field_uid: The field's UID.

    Returns:
        A ``(containing_list, index)`` tuple — the list the field lives in
        (``section.fields``, a subsection's ``fields``, or some field's
        ``children``, at any depth) and its index within that list.

    Raises:
        OperationError: If no field with this ``field_uid`` exists anywhere
            in the section (including subsections and nested children).
    """

    def _search(items: list) -> tuple[list, int] | None:
        for i, item in enumerate(items):
            if isinstance(item, FormSubsection):
                found = _search(item.fields)
                if found is not None:
                    return found
                continue
            if item.field_uid == field_uid:
                return items, i
            if item.children:
                found = _search(item.children)
                if found is not None:
                    return found
        return None

    found = _search(section.fields)
    if found is not None:
        return found
    raise OperationError(-1, "?", f"field '{field_uid}' not found")


def _check_unique_in_form(form: FormSchema, field: FormField) -> None:
    """Reject a field whose ``field_uid`` or ``field_id`` already exists
    anywhere in the form (FEAT-393 — replaces the per-SECTION
    ``_check_unique_field_id``; uniqueness is now enforced per-FORM, over
    the full nested tree via ``iter_fields_recursive()``).

    Args:
        form: The form to check against.
        field: The candidate field (about to be added or renamed).

    Raises:
        OperationError: If a duplicate ``field_uid`` or ``field_id`` is
            found.
    """
    for f in form.iter_fields_recursive():
        if f.field_uid == field.field_uid:
            raise OperationError(-1, "?", f"duplicate field_uid '{field.field_uid}'")
        if f.field_id == field.field_id:
            raise OperationError(-1, "?", f"duplicate field_id '{field.field_id}'")


def _check_unique_section_id(form: FormSchema, section_id: str) -> None:
    if any(s.section_id == section_id for s in form.sections):
        raise OperationError(
            -1,
            "?",
            f"duplicate section_id '{section_id}'",
        )


def _apply_add_section(form: FormSchema, op: AddSection) -> FormSchema:
    _check_unique_section_id(form, op.section.section_id)
    if op.position is None:
        form.sections.append(op.section)
    else:
        form.sections.insert(op.position, op.section)
    return form


def _apply_add_field(form: FormSchema, op: AddField) -> FormSchema:
    si = _section_index_by_uid(form, op.section_uid)
    section = form.sections[si]
    _check_unique_in_form(form, op.field)
    if op.position is None:
        section.fields.append(op.field)
    else:
        section.fields.insert(op.position, op.field)
    return form


def _apply_move_field(form: FormSchema, op: MoveField) -> FormSchema:
    src_section_uid = op.from_.get("section_uid")
    src_field_uid = op.from_.get("field_uid")
    dst_section_uid = op.to.get("section_uid")
    dst_position = op.to.get("position")
    if not src_section_uid or not src_field_uid or not dst_section_uid:
        raise OperationError(
            -1,
            "move_field",
            "move_field requires from.section_uid, from.field_uid, to.section_uid",
        )
    try:
        src_section_uid = uuid.UUID(str(src_section_uid))
        src_field_uid = uuid.UUID(str(src_field_uid))
        dst_section_uid = uuid.UUID(str(dst_section_uid))
    except (ValueError, AttributeError, TypeError) as exc:
        raise OperationError(
            -1, "move_field", f"section_uid/field_uid must be valid UUID strings: {exc}"
        ) from exc

    src_si = _section_index_by_uid(form, src_section_uid)
    src_section = form.sections[src_si]
    src_list, src_fi = _locate_field(src_section, src_field_uid)
    field = src_list.pop(src_fi)

    dst_si = _section_index_by_uid(form, dst_section_uid)
    dst_section = form.sections[dst_si]

    # When moving within the same section, the destination position refers
    # to the new index AFTER removal — we do not need a special case.
    # walk_fields (not iter_fields(), which only flattens subsections) so
    # a duplicate UID nested in a GROUP/ARRAY in the destination section is
    # also caught (code review follow-up).
    if any(f.field_uid == field.field_uid for f in walk_fields(dst_section.fields)):
        # Restore original location before raising.
        src_list.insert(src_fi, field)
        raise OperationError(
            -1,
            "move_field",
            f"duplicate field_uid '{field.field_uid}' in destination section",
        )

    if dst_position is None:
        dst_section.fields.append(field)
    else:
        dst_section.fields.insert(int(dst_position), field)
    return form


def _apply_remove_field(form: FormSchema, op: RemoveField) -> FormSchema:
    si = _section_index_by_uid(form, op.section_uid)
    section = form.sections[si]
    field_list, fi = _locate_field(section, op.field_uid)
    field_list.pop(fi)
    return form


def _apply_update_field(form: FormSchema, op: UpdateField) -> FormSchema:
    """Apply an RFC 7396 merge-patch to a field addressed by UID.

    ``field_id`` renames are allowed (subject to per-form uniqueness);
    a patch touching ``field_uid`` is rejected outright — the identity
    pin moves from ``field_id`` (pre-FEAT-393) to ``field_uid``.
    """
    si = _section_index_by_uid(form, op.section_uid)
    container, fi = _locate_field(form.sections[si], op.field_uid)
    if "field_uid" in op.patch:
        try:
            patch_uid_matches = uuid.UUID(str(op.patch["field_uid"])) == op.field_uid
        except (ValueError, AttributeError, TypeError):
            patch_uid_matches = False
        if not patch_uid_matches:
            raise OperationError(-1, "update_field", "field_uid is immutable")
    existing = container[fi].model_dump()
    merged = _deep_merge(existing, op.patch)
    merged["field_uid"] = str(op.field_uid)  # identity pin moves to the UID
    new_field_id = merged.get("field_id")
    # Rename → per-form uniqueness check.
    if new_field_id != existing["field_id"] and any(
        f.field_id == new_field_id
        for f in form.iter_fields_recursive()
        if f.field_uid != op.field_uid
    ):
        raise OperationError(-1, "update_field", f"duplicate field_id '{new_field_id}'")
    try:
        container[fi] = FormField.model_validate(merged)
    except ValidationError as exc:
        raise OperationError(-1, "update_field", str(exc)) from exc
    return form


def _apply_update_section_meta(
    form: FormSchema, op: UpdateSectionMeta
) -> FormSchema:
    si = _section_index_by_uid(form, op.section_uid)
    section = form.sections[si]
    existing_meta = section.meta or {}
    merged_meta = _deep_merge(existing_meta, op.patch)
    section_dict = section.model_dump()
    section_dict["meta"] = merged_meta or None
    try:
        form.sections[si] = FormSection.model_validate(section_dict)
    except ValidationError as exc:
        raise OperationError(-1, "update_section_meta", str(exc)) from exc
    return form


def _apply_update_form_meta(
    form: FormSchema, op: UpdateFormMeta
) -> FormSchema:
    existing = form.meta or {}
    merged = _deep_merge(existing, op.patch)
    form_dict = form.model_dump()
    form_dict["meta"] = merged or None
    try:
        return FormSchema.model_validate(form_dict)
    except ValidationError as exc:
        raise OperationError(-1, "update_form_meta", str(exc)) from exc


def _apply_duplicate_field(
    form: FormSchema, op: DuplicateField
) -> FormSchema:
    src_section_uid = op.from_.get("section_uid")
    src_field_uid = op.from_.get("field_uid")
    if not src_section_uid or not src_field_uid:
        raise OperationError(
            -1,
            "duplicate_field",
            "duplicate_field requires from.section_uid and from.field_uid",
        )
    try:
        src_section_uid = uuid.UUID(str(src_section_uid))
        src_field_uid = uuid.UUID(str(src_field_uid))
    except (ValueError, AttributeError, TypeError) as exc:
        raise OperationError(
            -1,
            "duplicate_field",
            f"section_uid/field_uid must be valid UUID strings: {exc}",
        ) from exc
    si = _section_index_by_uid(form, src_section_uid)
    section = form.sections[si]
    field_list, fi = _locate_field(section, src_field_uid)
    src = field_list[fi]
    if any(f.field_id == op.as_field_id for f in form.iter_fields_recursive()):
        raise OperationError(-1, "duplicate_field", f"duplicate field_id '{op.as_field_id}'")
    clone_dict = src.model_dump()
    clone_dict["field_id"] = op.as_field_id
    clone_dict.pop("field_uid", None)  # fresh identity minted by default_factory
    try:
        clone = FormField.model_validate(clone_dict)
    except ValidationError as exc:
        raise OperationError(-1, "duplicate_field", str(exc)) from exc
    field_list.insert(fi + 1, clone)
    return form


_DISPATCH: dict[str, Any] = {
    "add_section": _apply_add_section,
    "add_field": _apply_add_field,
    "move_field": _apply_move_field,
    "remove_field": _apply_remove_field,
    "update_field": _apply_update_field,
    "update_section_meta": _apply_update_section_meta,
    "update_form_meta": _apply_update_form_meta,
    "duplicate_field": _apply_duplicate_field,
}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------


async def handle_operations(request: web.Request) -> web.Response:
    """PATCH /api/v1/forms/{form_uid}/operations — atomic batched edits.

    Steps (per spec §2 Internal Behavior):

    1. Parse and validate ``form_uid`` from match_info (FEAT-389).
    2. Load form from ``request.app['form_registry']``; 404 if missing.
    3. Parse + validate the ``OperationsEnvelope`` body; 422 on shape errors.
    4. Honour ``If-Match`` header (Q1); 412 on mismatch.
    5. Apply ops sequentially on a deep-copy working form (address
       fields/sections by ``field_uid``/``section_uid``, FEAT-393). On the
       first ``OperationError``, return 422 with the offending op's
       index/name.
    6. Re-resolve rule references (``core.resolution.
       resolve_rule_references``, FEAT-393) — rewrites any authored
       ``field_id`` rule references introduced by an ``update_field``
       patch; 422 on an unknown/ambiguous/empty reference.
    7. ``FormValidator.check_schema`` on the working copy; 422 if errors.
    8. Bump the version via ``_bump_version``.
    9. Persist via ``registry.register(working_copy, persist=True, overwrite=True)``.
    10. Return 200 with ``{"form": working_copy.model_dump()}``.
    """
    form_uid = extract_form_uid(request)

    registry = request.app.get("form_registry")
    if registry is None:
        logger.error("operations: app['form_registry'] is unset")
        return web.json_response(
            {"error": "form registry not configured"}, status=500
        )

    tenant = _get_request_tenant(request)
    form = await registry.get(form_uid, tenant=tenant)
    if form is None:
        logger.warning("operations: form '%s' not found", form_uid)
        return web.json_response(
            {"error": f"Form '{form_uid}' not found"}, status=404
        )

    # If-Match optimistic concurrency (Q1)
    if_match = request.headers.get("If-Match")
    if if_match is not None:
        candidate = if_match.strip('"').strip("'")
        if candidate != form.version:
            logger.warning(
                "operations: If-Match mismatch for %s (have=%s, sent=%s)",
                form_uid,
                form.version,
                candidate,
            )
            return web.json_response(
                {"detail": "version mismatch", "current": form.version},
                status=412,
            )

    try:
        body = await request.json()
    except (json.JSONDecodeError, ValueError):
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    try:
        envelope = OperationsEnvelope.model_validate(body)
    except ValidationError as exc:
        return web.json_response(
            {"errors": exc.errors()}, status=422
        )

    working = form.model_copy(deep=True)
    for i, op in enumerate(envelope.operations):
        applier = _DISPATCH[op.op]
        try:
            working = applier(working, op)
        except OperationError as e:
            logger.warning(
                "operations: op[%d] (%s) failed for %s — %s",
                i,
                op.op,
                form_uid,
                e.message,
            )
            return web.json_response(
                {"errors": [{
                    "index": i,
                    "op": op.op,
                    "message": e.message,
                }]},
                status=422,
            )

    # Re-resolve rule references (FEAT-393): renames/adds/duplicates may
    # have changed field_id/field_uid pairings; authored field_id
    # references introduced by an update_field patch must be rewritten to
    # field_uid before structural validation runs.
    try:
        working = resolve_rule_references(working)
    except ValueError as exc:
        logger.warning(
            "operations: rule resolution failed for %s — %s", form_uid, exc
        )
        return web.json_response(
            {"errors": [{"index": None, "op": None, "message": str(exc)}]},
            status=422,
        )

    # Post-apply structural validation (circular depends_on, etc.)
    schema_errors = FormValidator().check_schema(working)
    if schema_errors:
        logger.warning(
            "operations: post-apply schema errors for %s: %s",
            form_uid,
            schema_errors,
        )
        return web.json_response(
            {
                "errors": [
                    {"index": None, "op": None, "message": err}
                    for err in schema_errors
                ]
            },
            status=422,
        )

    working.version = _bump_version(form.version)
    await registry.register(working, persist=True, overwrite=True, tenant=tenant)
    logger.info(
        "operations: applied %d ops to form '%s' → version %s",
        len(envelope.operations),
        form_uid,
        working.version,
    )
    return web.json_response({"form": working.model_dump(mode="json")})
