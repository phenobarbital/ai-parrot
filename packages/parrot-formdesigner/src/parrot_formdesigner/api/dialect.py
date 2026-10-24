"""Dialect negotiation for the form contract endpoints (FEAT-650, spec §3 M2).

Effective dialect = ``?dialect=`` query > ``Accept: application/a2ui+json`` >
``form.dialect``. ``GET /forms/{uid}`` never consults this module.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from aiohttp import web

from ..core import FormDialect
from ..core.options import FieldOption
from ..core.schema import FormField, FormSchema, FormSection, FormSubsection, RenderedForm
from .render import get_renderer, supported_formats

logger = logging.getLogger(__name__)

A2UI_MEDIA_TYPE = "application/a2ui+json"
DIALECT_QUERY_PARAM = "dialect"
A2UI_LIST_MAX = int(os.environ.get("FORMDESIGNER_A2UI_LIST_MAX", "50"))
_SUPPORTED = [dialect.value for dialect in FormDialect]


class DialectError(Exception):
    """A negotiation failure with an HTTP status and JSON payload."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        """Initialize the negotiation failure.

        Args:
            status: HTTP status code, either 400 or 415.
            payload: JSON response body for the client.
        """
        super().__init__(payload.get("error") or f"dialect error {status}")
        self.status = status
        self.payload = payload


def resolve_dialect(request: web.Request, form: FormSchema) -> FormDialect:
    """Return the effective dialect for ``form`` on this request.

    Args:
        request: Incoming request whose query and Accept header are negotiated.
        form: Form whose stored dialect supplies the fallback.

    Raises:
        DialectError: When the query dialect is unknown or A2UI is unavailable.
    """
    raw = request.query.get(DIALECT_QUERY_PARAM)
    if raw is not None:
        try:
            dialect = FormDialect(raw)
        except ValueError as exc:
            raise DialectError(400, {"error": f"unknown dialect {raw!r}", "supported": _SUPPORTED}) from exc
    elif A2UI_MEDIA_TYPE in request.headers.get("Accept", ""):
        dialect = FormDialect.A2UI
    else:
        dialect = form.dialect

    if dialect is FormDialect.A2UI and get_renderer("a2ui") is None:
        raise DialectError(415, {"supported": supported_formats()})
    return dialect


async def render_a2ui_schema(
    form: FormSchema, *, locale: str = "en", overrides: Mapping[str, Any] | None = None
) -> tuple[list[dict[str, Any]], RenderedForm, list[str]]:
    """Render a form through the registered A2UI renderer.

    Args:
        form: Form schema to render.
        locale: BCP 47 locale passed to the renderer.
        overrides: Optional shallow schema overrides to translate.

    Returns:
        A tuple of A2UI envelopes, the raw renderer result, and warning strings.

    Raises:
        RuntimeError: If an A2UI renderer is not registered.
    """
    renderer = get_renderer("a2ui")
    if renderer is None:
        raise RuntimeError("render_a2ui_schema: no 'a2ui' renderer registered (install parrot-formdesigner[ai-parrot])")

    rendered = await renderer.render(form, locale=locale)
    envelopes: list[dict[str, Any]] = [rendered.content]
    warnings = [warning.reason for warning in rendered.warnings]
    if overrides:
        extra, extra_warnings = overrides_to_envelopes(form, rendered, overrides, locale=locale)
        envelopes.extend(extra)
        warnings.extend(extra_warnings)
    return envelopes, rendered, warnings


def overrides_to_envelopes(
    form: FormSchema,
    rendered: RenderedForm,
    overrides: Mapping[str, Any],
    *,
    locale: str = "en",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Translate shallow schema overrides into A2UI envelopes.

    The translation follows the shallow override table in FEAT-650 spec §7.

    Args:
        form: Source form schema.
        rendered: Existing A2UI render result.
        overrides: Shallow JSON Schema override mapping.
        locale: BCP 47 locale selected for rendering.

    Returns:
        Serialized A2UI update envelopes and warnings for unsupported overrides.
    """
    from . import a2ui_wire
    from ..renderers.a2ui import A2UIFormRenderer, field_pointer

    m = a2ui_wire._a2ui_ns()
    renderer = get_renderer("a2ui")
    surface_id = f"form-{form.form_uid}"
    surface = rendered.content.get("createSurface", {})
    components = surface.get("components")
    if not isinstance(components, list):
        return [], [f"override_not_translatable:{key}" for key in overrides]

    present_ids = {component["id"] for component in components if isinstance(component, dict) and "id" in component}
    fields_by_id = {field.field_id: field for field in form.iter_all_fields()}
    envelopes: list[dict[str, Any]] = []
    warnings: list[str] = []
    property_keys = {
        "title",
        "description",
        "x-placeholder",
        "x-read-only",
        "x-options",
        "enum",
        "default",
    }

    for key, value in overrides.items():
        if key in ("title", "description"):
            component_id = f"root-{key}"
            text = m.Component(
                id=component_id,
                component="Text",
                text=str(value),
                metadata=m.ComponentMetadata(extensions=m.Extensions({"parrot_role": key})),
            )
            if component_id not in present_ids:
                root = next((component for component in components if component.get("id") == "root"), None)
                if root is None:
                    warnings.append(f"override_not_translatable:{key}")
                    continue
                root_component = m.Component.model_validate(root)
                root_component = root_component.model_copy(
                    update={"children": [component_id, *(root_component.children or [])]}
                )
                envelopes.append(m.serialize(m.UpdateComponents(surface_id=surface_id, components=[root_component])))
                present_ids.add(component_id)
            envelopes.append(m.serialize(m.UpdateComponents(surface_id=surface_id, components=[text])))
        elif key == "properties" and isinstance(value, dict):
            for field_id, prop in value.items():
                field = fields_by_id.get(field_id)
                if field is None or f"f-{field_id}" not in present_ids or not isinstance(prop, dict):
                    warnings.append(f"override_unknown_field:{field_id}")
                    continue
                supported = {prop_key: prop_value for prop_key, prop_value in prop.items() if prop_key in property_keys}
                for prop_key in prop:
                    if prop_key not in property_keys:
                        warnings.append(f"override_not_translatable:properties.{field_id}.{prop_key}")
                if not supported:
                    continue
                if "default" in supported:
                    envelopes.append(
                        m.serialize(
                            m.UpdateDataModel(
                                surface_id=surface_id,
                                path=field_pointer(field_id),
                                value=supported["default"],
                            )
                        )
                    )
                if not isinstance(renderer, A2UIFormRenderer):
                    warnings.append(f"override_not_translatable:properties.{field_id}")
                    continue
                relowered = _relower(renderer, form, field_id, _patched_field(field, supported), locale, m)
                if relowered:
                    envelopes.append(m.serialize(m.UpdateComponents(surface_id=surface_id, components=relowered)))
        elif key == "required" and isinstance(value, list):
            required_ids = set(value)
            for field_id in value:
                if field_id not in fields_by_id:
                    warnings.append(f"override_unknown_field:{field_id}")
            if not isinstance(renderer, A2UIFormRenderer):
                warnings.append("override_not_translatable:required")
                continue
            relowered_components: list[Any] = []
            for field_id, field in fields_by_id.items():
                required = field_id in required_ids
                if field.required == required:
                    continue
                if f"f-{field_id}" not in present_ids:
                    warnings.append(f"override_unknown_field:{field_id}")
                    continue
                relowered_components.extend(
                    _relower(renderer, form, field_id, field.model_copy(update={"required": required}), locale, m)
                )
            if relowered_components:
                envelopes.append(
                    m.serialize(m.UpdateComponents(surface_id=surface_id, components=relowered_components))
                )
        else:
            warnings.append(f"override_not_translatable:{key}")
    return envelopes, warnings


def _patched_field(field: FormField, prop: Mapping[str, Any]) -> FormField:
    """Copy ``field`` with JSON-Schema-level overrides applied.

    Args:
        field: The source field to copy.
        prop: Direct property overrides for the field.

    Returns:
        The copied field with supported overrides applied.
    """
    update: dict[str, Any] = {}
    if "title" in prop:
        update["label"] = prop["title"]
    if "description" in prop:
        update["description"] = prop["description"]
    if "x-placeholder" in prop:
        update["placeholder"] = prop["x-placeholder"]
    if "x-read-only" in prop:
        update["read_only"] = bool(prop["x-read-only"])
    if "default" in prop:
        update["default"] = prop["default"]
    if "x-options" in prop:
        update["options"] = [FieldOption.model_validate(option) for option in prop["x-options"]]
    elif "enum" in prop:
        update["options"] = [FieldOption(value=str(option), label=str(option)) for option in prop["enum"]]
    return field.model_copy(update=update)


def _relower(
    renderer: Any,
    form: FormSchema,
    field_id: str,
    patched: FormField,
    locale: str,
    m: Any,
) -> list[Any]:
    """Re-lower one field through the A2UI renderer's field table.

    Args:
        renderer: Registered A2UI renderer.
        form: Form containing the field.
        field_id: Identifier of the field to locate.
        patched: Field copy carrying the override values.
        locale: Locale used by the renderer.
        m: Lazy A2UI model namespace.

    Returns:
        Component models replacing the field's existing components.

    Raises:
        ValueError: If the field has no owning section or subsection.
    """
    for section in form.sections:
        for item in section.fields:
            if isinstance(item, FormSubsection):
                if any(field.field_id == field_id for field in item.fields):
                    subsection = item
                    break
            elif item.field_id == field_id:
                subsection = None
                break
        else:
            continue
        break
    else:
        raise ValueError(f"field {field_id!r} has no owning section")

    renderer._m = m
    try:
        components, _warning = renderer._lower_field(patched, section, subsection, locale, {})
    finally:
        renderer._m = None
    return components
