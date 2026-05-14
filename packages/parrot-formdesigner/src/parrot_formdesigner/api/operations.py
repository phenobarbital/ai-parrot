"""``PATCH /api/v1/forms/{form_id}/operations`` — atomic batched-edit endpoint.

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
from typing import Annotated, Any, Literal, Union

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..core.schema import FormField, FormSchema, FormSection, FormSubsection
from ..services.validators import FormValidator
from ._utils import _bump_version, _deep_merge


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
    """Insert a new field into an existing section."""

    op: Literal["add_field"]
    section_id: str
    field: FormField
    position: int | None = None


class MoveField(_OpBase):
    """Move a field across (or within) sections.

    ``from`` is a Python keyword, so the wire field is aliased to ``from_``.
    Set ``model_config = ConfigDict(populate_by_name=True)`` so both the
    alias and the field name are accepted.
    """

    op: Literal["move_field"]
    from_: dict = Field(alias="from")
    to: dict


class RemoveField(_OpBase):
    """Remove a field from a section."""

    op: Literal["remove_field"]
    section_id: str
    field_id: str


class UpdateField(_OpBase):
    """Apply RFC 7396 merge-patch to a single field."""

    op: Literal["update_field"]
    section_id: str
    field_id: str
    patch: dict[str, Any]


class UpdateSectionMeta(_OpBase):
    """Apply RFC 7396 merge-patch to a section's metadata."""

    op: Literal["update_section_meta"]
    section_id: str
    patch: dict[str, Any]


class UpdateFormMeta(_OpBase):
    """Apply RFC 7396 merge-patch to the form-level meta."""

    op: Literal["update_form_meta"]
    patch: dict[str, Any]


class DuplicateField(_OpBase):
    """Duplicate a field within the same (or another) section."""

    op: Literal["duplicate_field"]
    from_: dict = Field(alias="from")
    as_field_id: str


Operation = Annotated[
    Union[
        AddSection,
        AddField,
        MoveField,
        RemoveField,
        UpdateField,
        UpdateSectionMeta,
        UpdateFormMeta,
        DuplicateField,
    ],
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


def _field_index(section: FormSection, field_id: str) -> int:
    for i, f in enumerate(section.fields):
        if isinstance(f, FormSubsection):
            continue
        if f.field_id == field_id:
            return i
    raise OperationError(-1, "?", f"field '{field_id}' not found")


def _check_unique_field_id(section: FormSection, field_id: str) -> None:
    if any(f.field_id == field_id for f in section.iter_fields()):
        raise OperationError(
            -1,
            "?",
            f"duplicate field_id '{field_id}' in section '{section.section_id}'",
        )


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
    si = _section_index(form, op.section_id)
    section = form.sections[si]
    _check_unique_field_id(section, op.field.field_id)
    if op.position is None:
        section.fields.append(op.field)
    else:
        section.fields.insert(op.position, op.field)
    return form


def _apply_move_field(form: FormSchema, op: MoveField) -> FormSchema:
    src_section_id = op.from_.get("section_id")
    src_field_id = op.from_.get("field_id")
    dst_section_id = op.to.get("section_id")
    dst_position = op.to.get("position")
    if not src_section_id or not src_field_id or not dst_section_id:
        raise OperationError(
            -1,
            "move_field",
            "move_field requires from.section_id, from.field_id, to.section_id",
        )

    src_si = _section_index(form, src_section_id)
    src_section = form.sections[src_si]
    src_fi = _field_index(src_section, src_field_id)
    field = src_section.fields.pop(src_fi)

    dst_si = _section_index(form, dst_section_id)
    dst_section = form.sections[dst_si]

    # When moving within the same section, the destination position refers
    # to the new index AFTER removal — we do not need a special case.
    if any(f.field_id == field.field_id for f in dst_section.iter_fields()):
        # Restore original location before raising.
        src_section.fields.insert(src_fi, field)
        raise OperationError(
            -1,
            "move_field",
            f"duplicate field_id '{field.field_id}' in destination section",
        )

    if dst_position is None:
        dst_section.fields.append(field)
    else:
        dst_section.fields.insert(int(dst_position), field)
    return form


def _apply_remove_field(form: FormSchema, op: RemoveField) -> FormSchema:
    si = _section_index(form, op.section_id)
    section = form.sections[si]
    fi = _field_index(section, op.field_id)
    section.fields.pop(fi)
    return form


def _apply_update_field(form: FormSchema, op: UpdateField) -> FormSchema:
    si = _section_index(form, op.section_id)
    section = form.sections[si]
    fi = _field_index(section, op.field_id)
    existing = section.fields[fi].model_dump()
    merged = _deep_merge(existing, op.patch)
    # Preserve identity — disallow renaming via patch.
    merged["field_id"] = op.field_id
    try:
        section.fields[fi] = FormField.model_validate(merged)
    except ValidationError as exc:
        raise OperationError(-1, "update_field", str(exc)) from exc
    return form


def _apply_update_section_meta(
    form: FormSchema, op: UpdateSectionMeta
) -> FormSchema:
    si = _section_index(form, op.section_id)
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
    src_section_id = op.from_.get("section_id")
    src_field_id = op.from_.get("field_id")
    if not src_section_id or not src_field_id:
        raise OperationError(
            -1,
            "duplicate_field",
            "duplicate_field requires from.section_id and from.field_id",
        )
    si = _section_index(form, src_section_id)
    section = form.sections[si]
    fi = _field_index(section, src_field_id)
    _check_unique_field_id(section, op.as_field_id)
    src = section.fields[fi]
    clone_dict = src.model_dump()
    clone_dict["field_id"] = op.as_field_id
    try:
        clone = FormField.model_validate(clone_dict)
    except ValidationError as exc:
        raise OperationError(-1, "duplicate_field", str(exc)) from exc
    section.fields.insert(fi + 1, clone)
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
    """PATCH /api/v1/forms/{form_id}/operations — atomic batched edits.

    Steps (per spec §2 Internal Behavior):

    1. Parse ``form_id`` from match_info.
    2. Load form from ``request.app['form_registry']``; 404 if missing.
    3. Parse + validate the ``OperationsEnvelope`` body; 422 on shape errors.
    4. Honour ``If-Match`` header (Q1); 412 on mismatch.
    5. Apply ops sequentially on a deep-copy working form. On the first
       ``OperationError``, return 422 with the offending op's index/name.
    6. ``FormValidator.check_schema`` on the working copy; 422 if errors.
    7. Bump the version via ``_bump_version``.
    8. Persist via ``registry.register(working_copy, persist=True, overwrite=True)``.
    9. Return 200 with ``{"form": working_copy.model_dump()}``.
    """
    form_id = request.match_info["form_id"]

    registry = request.app.get("form_registry")
    if registry is None:
        logger.error("operations: app['form_registry'] is unset")
        return web.json_response(
            {"error": "form registry not configured"}, status=500
        )

    form = await registry.get(form_id)
    if form is None:
        logger.warning("operations: form '%s' not found", form_id)
        return web.json_response(
            {"error": f"Form '{form_id}' not found"}, status=404
        )

    # If-Match optimistic concurrency (Q1)
    if_match = request.headers.get("If-Match")
    if if_match is not None:
        candidate = if_match.strip('"').strip("'")
        if candidate != form.version:
            logger.warning(
                "operations: If-Match mismatch for %s (have=%s, sent=%s)",
                form_id,
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
                form_id,
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

    # Post-apply structural validation (circular depends_on, etc.)
    schema_errors = FormValidator().check_schema(working)
    if schema_errors:
        logger.warning(
            "operations: post-apply schema errors for %s: %s",
            form_id,
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
    await registry.register(working, persist=True, overwrite=True)
    logger.info(
        "operations: applied %d ops to form '%s' → version %s",
        len(envelope.operations),
        form_id,
        working.version,
    )
    return web.json_response({"form": working.model_dump(mode="json")})
