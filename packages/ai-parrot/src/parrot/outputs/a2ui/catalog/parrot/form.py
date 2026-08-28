"""``build_form()`` — v1.0 form composition helper (Module 5, FEAT-470 TASK-2540).

``Form`` is NOT a registered catalog component in v1.0 (spec G6, retired in
TASK-2539): a form is composed directly from Basic Catalog input primitives
(``TextField``/``CheckBox``/``ChoicePicker``/``DateTimeInput``) plus a
``Button`` whose ``action.event`` carries the submit event name and a
``context`` binding every field's current value. This keeps forms fully
interactive on any v1.0-compliant renderer — no bespoke ``Form`` schema, no
degraded "not available" notice.

``build_form()`` is ``ProducerOrigin.TOOL``-only by construction: it emits a
``Button.action``, which the LLM-origin gate (spec G2/D10b) always rejects.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from parrot.outputs.a2ui.models import (
    Action,
    CheckRule,
    Component,
    EventAction,
    FunctionCall,
)

__all__ = ["FormField", "FormSubmit", "build_form"]

#: The field->primitive mapping this helper supports (spec §2/§5).
FormFieldInput = Literal["text", "number", "select", "checkbox", "date", "textarea"]


class FormField(BaseModel):
    """One field in a composed form.

    Attributes:
        name: The field's data-model key (bound at ``/<id_prefix>/<name>``).
        label: The field's display label.
        input: Which Basic Catalog input primitive to compose.
        required: Whether a ``required`` check is attached.
        options: Required for ``input="select"`` — ``[{"label", "value"}, ...]``.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    label: str
    input: FormFieldInput
    required: bool = False
    options: list[dict[str, str]] | None = None


class FormSubmit(BaseModel):
    """The form's submit action descriptor.

    Attributes:
        label: The submit button's label.
        action: The event name dispatched on submit (``Button.action.event.name``).
    """

    model_config = ConfigDict(populate_by_name=True)

    label: str
    action: str


def _field_value_path(id_prefix: str, field: FormField) -> dict[str, str]:
    return {"path": f"/{id_prefix}/{field.name}"}


def _lower_field(id_prefix: str, field: FormField) -> Component:
    """Compose one :class:`FormField` into its Basic Catalog input primitive."""
    field_id = f"{id_prefix}-{field.name}"
    value_path = _field_value_path(id_prefix, field)
    checks = None
    if field.required:
        checks = [
            CheckRule(
                condition=FunctionCall(call="required", args={"value": value_path}),
                message=f"{field.label} is required.",
            )
        ]

    if field.input in ("text", "textarea", "number"):
        variant = {"text": "shortText", "textarea": "longText", "number": "number"}[field.input]
        return Component(
            id=field_id, component="TextField", label=field.label, value=value_path,
            variant=variant, checks=checks,
        )
    if field.input == "select":
        return Component(
            id=field_id, component="ChoicePicker", label=field.label,
            options=field.options or [], value=value_path, checks=checks,
        )
    if field.input == "checkbox":
        return Component(
            id=field_id, component="CheckBox", label=field.label, value=value_path, checks=checks
        )
    if field.input == "date":
        return Component(
            id=field_id, component="DateTimeInput", label=field.label, value=value_path,
            enableDate=True, checks=checks,
        )
    raise ValueError(f"Unsupported form field input type: {field.input!r}")


def build_form(
    *, id_prefix: str, title: str | None, fields: list[FormField], submit: FormSubmit
) -> list[Component]:
    """Compose a form from Basic Catalog primitives (spec §2 ``build_form``).

    Args:
        id_prefix: Prefix for every generated component id (the returned
            root ``Column`` itself uses ``id_prefix`` verbatim — pass
            ``"root"`` to make the form the surface's own root).
        title: Optional form title (rendered as a ``Text``).
        fields: The form's fields, in display order.
        submit: The submit button's label + dispatched event name.

    Returns:
        A flat list of v1.0 :class:`Component` instances — the root
        ``Column`` FIRST, followed by every field/title/button component (a
        valid v1.0 adjacency-list fragment, ready to splice into
        ``CreateSurface.components``).
    """
    children_ids: list[str] = []
    rest: list[Component] = []

    if title is not None:
        title_id = f"{id_prefix}-title"
        rest.append(Component(id=title_id, component="Text", text=title))
        children_ids.append(title_id)

    for field in fields:
        rest.append(_lower_field(id_prefix, field))
        children_ids.append(f"{id_prefix}-{field.name}")

    label_id = f"{id_prefix}-submit-label"
    rest.append(Component(id=label_id, component="Text", text=submit.label))

    context: dict[str, Any] = {
        field.name: _field_value_path(id_prefix, field) for field in fields
    }
    button_id = f"{id_prefix}-submit"
    rest.append(
        Component(
            id=button_id,
            component="Button",
            child=label_id,
            action=Action(event=EventAction(name=submit.action, context=context)),
        )
    )
    children_ids.append(button_id)

    root = Component(id=id_prefix, component="Column", children=children_ids)
    return [root, *rest]
