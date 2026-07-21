# packages/ai-parrot/src/parrot/outputs/cards/renderer.py
"""CardSpec → Adaptive Card 1.5 JSON renderer."""
from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel

from .actions import (
    ACAction,
    ActionOpenUrl,
    ActionShowCard,
    ActionSubmit,
    ActionToggleVisibility,
    TargetElement,
)
from .elements import (
    ACElement,
    Column,
    ColumnSet,
    Container,
    Fact,
    FactSet,
    Image,
    Table,
    TableCell,
    TableColumnDefinition,
    TableRow,
    TextBlock,
)
from .inputs import (
    InputChoiceSet,
    InputDate,
    InputNumber,
    InputText,
    InputTime,
    InputToggle,
)
from .sections import (
    CardSection,
    CodeSection,
    DetailSection,
    FormFieldSpec,
    FormSection,
    ImageSection,
    MetricsSection,
    RawElementsSection,
    StatusSection,
    TableSection,
    TextSection,
    ToggleSection,
)
from .spec import CardSpec
from .toggle import AutoCollapsePolicy, ToggleGroup

logger = logging.getLogger(__name__)

_LEVEL_TO_COLOR = {
    "success": "Good",
    "warning": "Warning",
    "error": "Attention",
    "info": "Default",
}

_FIELD_TYPE_TO_INPUT = {
    "text": "Input.Text",
    "text_area": "Input.Text",
    "number": "Input.Number",
    "integer": "Input.Number",
    "boolean": "Input.Toggle",
    "date": "Input.Date",
    "datetime": "Input.Date",
    "time": "Input.Time",
    "select": "Input.ChoiceSet",
    "multi_select": "Input.ChoiceSet",
    "email": "Input.Text",
    "url": "Input.Text",
    "phone": "Input.Text",
    "password": "Input.Text",
    "color": "Input.Text",
    "hidden": "Input.Text",
}

# snake_case → camelCase mapping for AC JSON serialization.
# Only non-trivial mappings listed; the serializer handles
# the generic snake→camel conversion for unlisted keys.
_FIELD_RENAMES: dict[str, str] = {
    "element_type": "type",
    "action_type": "type",
    "alt_text": "altText",
    "font_type": "fontType",
    "is_subtle": "isSubtle",
    "is_visible": "isVisible",
    "is_required": "isRequired",
    "is_multiline": "isMultiline",
    "is_multi_select": "isMultiSelect",
    "horizontal_alignment": "horizontalAlignment",
    "vertical_cell_content_alignment": "verticalCellContentAlignment",
    "horizontal_cell_content_alignment": "horizontalCellContentAlignment",
    "max_lines": "maxLines",
    "max_length": "maxLength",
    "first_row_as_header": "firstRowAsHeader",
    "show_grid_lines": "showGridLines",
    "grid_style": "gridStyle",
    "error_message": "errorMessage",
    "value_on": "valueOn",
    "value_off": "valueOff",
    "associated_inputs": "associatedInputs",
    "target_elements": "targetElements",
    "element_id": "elementId",
    "schema_url": "$schema",
}

# Fields whose value must always be emitted even when it equals the
# model's declared default — either because they carry structural data
# (element_type, text, url, id, ...) or because their "default" value is
# itself the semantically meaningful, expected-to-be-present state for AC
# consumers (e.g. TextBlock.wrap defaults to True and Table.first_row_as_
# header defaults to True, but both must still show up in the rendered
# JSON).
_ALWAYS_EMIT_FIELDS = frozenset({
    "element_type", "text", "url", "id", "title", "facts",
    "columns", "rows", "items", "cells", "choices",
    "wrap", "first_row_as_header",
})


class CardRenderError(Exception):
    """Raised when a CardSpec cannot be rendered within limits."""


# ── Section expanders ─────────────────────────────────────────────────

def _expand_text(section: TextSection) -> tuple[list[ACElement], list[ACAction]]:
    kwargs: dict[str, Any] = {}
    if section.role == "title":
        kwargs.update(size="Large", weight="Bolder")
    elif section.role in ("heading", "subtitle", "label"):
        kwargs["weight"] = "Bolder"
    elif section.role in ("code", "monospace"):
        kwargs["font_type"] = "Monospace"
    if section.color:
        kwargs["color"] = section.color
    if section.is_subtle:
        kwargs["is_subtle"] = True
    return [TextBlock(text=section.text, **kwargs)], []


def _expand_table(section: TableSection) -> tuple[list[ACElement], list[ACAction]]:
    n_cols = len(section.columns)
    col_defs = [TableColumnDefinition(width="1") for _ in section.columns]

    header_cells = [TableCell(items=[TextBlock(text=c, weight="Bolder")])
                    for c in section.columns]
    rows = [TableRow(cells=header_cells)]

    display_rows = section.rows[:section.max_display_rows]
    for row_data in display_rows:
        cells_data = [str(c) for c in row_data[:n_cols]]
        cells_data += [""] * (n_cols - len(cells_data))
        rows.append(TableRow(cells=[
            TableCell(items=[TextBlock(text=cell)]) for cell in cells_data
        ]))

    elements: list[ACElement] = [Table(
        columns=col_defs,
        rows=rows,
        first_row_as_header=section.first_row_as_header,
        show_grid_lines=section.show_grid_lines,
    )]

    total = section.total_rows if section.total_rows is not None else len(section.rows)
    if total > len(display_rows):
        elements.append(TextBlock(
            text=f"Showing {len(display_rows)} of {total}",
            is_subtle=True,
        ))
    return elements, []


def _expand_metrics(section: MetricsSection) -> tuple[list[ACElement], list[ACAction]]:
    facts = []
    for m in section.metrics:
        value = m.value
        if m.delta:
            value = f"{value} ({m.delta})"
        facts.append(Fact(title=m.label, value=value))
    return [FactSet(facts=facts)], []


def _expand_detail(section: DetailSection) -> tuple[list[ACElement], list[ACAction]]:
    facts = [Fact(title=f.label, value=f.value) for f in section.fields]
    return [FactSet(facts=facts)], []


def _expand_image(section: ImageSection) -> tuple[list[ACElement], list[ACAction]]:
    elements = [
        Image(url=img.url, alt_text=img.alt_text, size=img.size,
              horizontal_alignment="Center")
        for img in section.images
    ]
    return elements, []


def _expand_code(section: CodeSection) -> tuple[list[ACElement], list[ACAction]]:
    elements: list[ACElement] = []
    if section.label:
        elements.append(TextBlock(text=section.label, weight="Bolder", spacing="Medium"))
    elements.append(TextBlock(text=section.code, font_type="Monospace", spacing="Small"))
    return elements, []


def _expand_status(section: StatusSection) -> tuple[list[ACElement], list[ACAction]]:
    items: list[ACElement] = [
        TextBlock(
            text=section.message,
            weight="Bolder",
            color=_LEVEL_TO_COLOR.get(section.level, "Default"),
        ),
    ]
    if section.details:
        items.append(TextBlock(text=section.details))
    return [Container(items=items)], []


def _expand_toggle(section: ToggleSection) -> tuple[list[ACElement], list[ACAction]]:
    tg = section.toggle
    group_id = tg.group_id or "tg_0"
    container_id = f"{group_id}_content"

    container = Container(
        id=container_id,
        items=[_serialize_to_element(e) if not isinstance(e, ACElement) else e
               for e in tg.content],
        is_visible=tg.initially_visible,
    )
    action = ActionToggleVisibility(
        title=tg.label_collapsed if not tg.initially_visible else tg.label_expanded,
        target_elements=[TargetElement(element_id=container_id)],
    )
    return [container], [action]


def _expand_form(section: FormSection) -> tuple[list[ACElement], list[ACAction]]:
    elements: list[ACElement] = []
    for field in section.fields:
        elements.extend(_build_form_field(field))
    return elements, []


def _build_form_field(field: FormFieldSpec) -> list[ACElement]:
    elements: list[ACElement] = []
    input_type = _FIELD_TYPE_TO_INPUT.get(field.field_type, "Input.Text")

    if input_type == "Input.Text":
        kwargs: dict[str, Any] = {}
        if field.field_type == "email":
            kwargs["style"] = "Email"
        elif field.field_type == "url":
            kwargs["style"] = "Url"
        elif field.field_type == "password":
            kwargs["style"] = "Password"
        if field.field_type == "text_area":
            kwargs["is_multiline"] = True
        elif field.is_multiline:
            kwargs["is_multiline"] = True
        if field.constraints and field.constraints.get("max_length"):
            kwargs["max_length"] = field.constraints["max_length"]
        if field.constraints and field.constraints.get("pattern"):
            kwargs["regex"] = field.constraints["pattern"]
        elements.append(InputText(
            id=field.field_id,
            label=field.label,
            placeholder=field.placeholder or "",
            value=str(field.default) if field.default is not None else "",
            is_required=field.required,
            **kwargs,
        ))
    elif input_type == "Input.Number":
        kwargs = {}
        if field.constraints:
            if field.constraints.get("min_value") is not None:
                kwargs["min"] = field.constraints["min_value"]
            if field.constraints.get("max_value") is not None:
                kwargs["max"] = field.constraints["max_value"]
        elements.append(InputNumber(
            id=field.field_id,
            label=field.label,
            placeholder=field.placeholder or "",
            value=field.default,
            is_required=field.required,
            **kwargs,
        ))
    elif input_type == "Input.Toggle":
        elements.append(InputToggle(
            id=field.field_id,
            title=field.description or field.label,
            label=field.label,
            value="true" if field.default else "false",
            is_required=field.required,
        ))
    elif input_type == "Input.Date":
        elements.append(InputDate(
            id=field.field_id,
            label=field.label,
            value=str(field.default) if field.default else None,
            is_required=field.required,
        ))
    elif input_type == "Input.Time":
        elements.append(InputTime(
            id=field.field_id,
            label=field.label,
            value=str(field.default) if field.default else None,
            is_required=field.required,
        ))
    elif input_type == "Input.ChoiceSet":
        choices = []
        if field.options:
            from .inputs import InputChoice
            choices = [InputChoice(title=o.title, value=o.value) for o in field.options]
        is_multi = field.field_type == "multi_select"
        elements.append(InputChoiceSet(
            id=field.field_id,
            label=field.label,
            choices=choices,
            value=str(field.default) if field.default else None,
            is_multi_select=is_multi,
            style="expanded" if is_multi else "compact",
            is_required=field.required,
        ))
    return elements


def _expand_raw(section: RawElementsSection) -> tuple[list[ACElement], list[ACAction]]:
    return list(section.elements), []


_SECTION_EXPANDERS: dict[str, Any] = {
    "text": _expand_text,
    "table": _expand_table,
    "metrics": _expand_metrics,
    "detail": _expand_detail,
    "image": _expand_image,
    "code": _expand_code,
    "status": _expand_status,
    "toggle": _expand_toggle,
    "form": _expand_form,
    "raw": _expand_raw,
}


def _serialize_to_element(obj: Any) -> ACElement:
    if isinstance(obj, ACElement):
        return obj
    return TextBlock(text=str(obj))


# ── Serialization ─────────────────────────────────────────────────────

def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _serialize_element(element: ACElement) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name, field_info in type(element).model_fields.items():
        value = getattr(element, field_name)
        if value is None:
            continue
        if (
            field_name not in _ALWAYS_EMIT_FIELDS
            and value == field_info.default
        ):
            continue
        ac_key = _FIELD_RENAMES.get(field_name, _snake_to_camel(field_name))
        if isinstance(value, list):
            serialized_list = []
            for item in value:
                if isinstance(item, ACElement):
                    serialized_list.append(_serialize_element(item))
                elif isinstance(item, BaseModel):
                    serialized_list.append(_serialize_model(item))
                else:
                    serialized_list.append(item)
            if serialized_list or field_name in ("items", "columns", "rows",
                                                  "cells", "facts", "choices"):
                result[ac_key] = serialized_list
        elif isinstance(value, ACElement):
            result[ac_key] = _serialize_element(value)
        elif isinstance(value, BaseModel):
            result[ac_key] = _serialize_model(value)
        else:
            result[ac_key] = value
    return result


def _serialize_model(model: BaseModel) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_name in type(model).model_fields:
        value = getattr(model, field_name)
        if value is None:
            continue
        ac_key = _FIELD_RENAMES.get(field_name, _snake_to_camel(field_name))
        if isinstance(value, list):
            result[ac_key] = [
                _serialize_element(v) if isinstance(v, ACElement)
                else _serialize_model(v) if isinstance(v, BaseModel)
                else v
                for v in value
            ]
        elif isinstance(value, ACElement):
            result[ac_key] = _serialize_element(value)
        elif isinstance(value, BaseModel):
            result[ac_key] = _serialize_model(value)
        else:
            result[ac_key] = value
    return result


def _serialize_action(action: ACAction) -> dict[str, Any]:
    result: dict[str, Any] = {"type": action.action_type, "title": action.title}
    if action.style and action.style != "default":
        result["style"] = action.style
    if isinstance(action, ActionSubmit):
        if action.data:
            result["data"] = action.data
        if action.associated_inputs:
            result["associatedInputs"] = action.associated_inputs
    elif isinstance(action, ActionOpenUrl):
        result["url"] = action.url
    elif isinstance(action, ActionToggleVisibility):
        result["targetElements"] = [
            {"elementId": t.element_id, **({"isVisible": t.is_visible}
                                            if t.is_visible is not None else {})}
            for t in action.target_elements
        ]
    elif isinstance(action, ActionShowCard):
        result["card"] = render(action.card)
    return result


# ── Public API ────────────────────────────────────────────────────────

def render(spec: CardSpec, *, max_card_bytes: int = 28_000) -> dict[str, Any]:
    """Render a :class:`CardSpec` into an Adaptive Card 1.5 JSON payload.

    Args:
        spec: The card specification to render.
        max_card_bytes: Maximum allowed serialized card size in bytes.

    Returns:
        A JSON-serializable dict representing the Adaptive Card.

    Raises:
        CardRenderError: If the serialized card exceeds ``max_card_bytes``.
    """
    body: list[dict[str, Any]] = []
    all_actions: list[ACAction] = list(spec.actions)

    # Title and summary
    if spec.title:
        body.append(_serialize_element(TextBlock(
            text=spec.title, weight="Bolder", size="Large",
        )))
    if spec.summary:
        body.append(_serialize_element(TextBlock(text=spec.summary)))

    # Expand sections
    toggle_counter = 0
    for section in spec.sections:
        expander = _SECTION_EXPANDERS.get(section.section_type)
        if expander is None:
            logger.warning("Unknown section type: %s", section.section_type)
            continue

        if isinstance(section, ToggleSection) and section.toggle.group_id is None:
            section.toggle.group_id = f"tg_{toggle_counter}"
            toggle_counter += 1

        elements, actions = expander(section)
        for element in elements:
            serialized = _serialize_element(element)
            if section.separator and not body:
                pass
            elif section.separator:
                serialized["separator"] = True
            if section.spacing:
                serialized["spacing"] = section.spacing
            body.append(serialized)
        all_actions.extend(actions)

    card: dict[str, Any] = {
        "$schema": spec.schema_url,
        "type": "AdaptiveCard",
        "version": spec.version,
        "body": body,
    }
    if all_actions:
        card["actions"] = [_serialize_action(a) for a in all_actions]

    serialized_size = len(json.dumps(card).encode("utf-8"))
    if serialized_size > max_card_bytes:
        raise CardRenderError(
            f"card size {serialized_size} exceeds max_card_bytes={max_card_bytes}"
        )
    return card


def render_text(spec: CardSpec) -> str:
    """Render a :class:`CardSpec` into a plain-text fallback representation.

    Used by clients that cannot display Adaptive Cards. Never raises —
    falls back to a generic message if rendering fails.

    Args:
        spec: The card specification to render.

    Returns:
        A plain-text summary of the card contents.
    """
    try:
        lines: list[str] = []
        if spec.title:
            lines.append(f"**{spec.title}**")
        if spec.summary:
            lines.append(spec.summary)
        for section in spec.sections:
            if isinstance(section, TextSection):
                lines.append(section.text)
            elif isinstance(section, TableSection):
                if section.columns:
                    lines.append(" | ".join(section.columns))
                    for row in section.rows[:section.max_display_rows]:
                        lines.append(" | ".join(str(c) for c in row))
            elif isinstance(section, MetricsSection):
                for m in section.metrics:
                    text = f"{m.label}: {m.value}"
                    if m.delta:
                        text += f" ({m.delta})"
                    lines.append(text)
            elif isinstance(section, DetailSection):
                for f in section.fields:
                    lines.append(f"{f.label}: {f.value}")
            elif isinstance(section, StatusSection):
                lines.append(f"[{section.level.upper()}] {section.message}")
                if section.details:
                    lines.append(section.details)
            elif isinstance(section, CodeSection):
                if section.label:
                    lines.append(section.label)
                lines.append(f"```{section.language or ''}\n{section.code}\n```")
            elif isinstance(section, ImageSection):
                for img in section.images:
                    lines.append(f"[Image: {img.alt_text or img.url}]")
        return "\n".join(lines)
    except Exception:
        return "Unable to render result."
