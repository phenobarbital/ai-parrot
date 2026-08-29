"""Derive parrot-catalog component schemas from the structured config models.

FEAT-473 (G2 — schema parity by construction, brainstorm Option D): the
``Chart``/``DataTable``/``Map`` parrot-catalog schemas are generated at
import time from ``StructuredChartConfig``/``StructuredTableConfig``/
``StructuredMapConfig.model_json_schema(by_alias=True)`` instead of being
hand-maintained, so every config field is representable on the wire, by
construction.

Two adjustments on top of the raw Pydantic schema:

* the INPUT-ONLY row fields (``data``, and ``datasets`` for maps) are
  replaced by the data-model binding descriptor (``{"path": "/pointer"}``);
* Pydantic-generated ``title`` annotations are stripped (noise for the wire
  schema) while ``$defs`` (``MapLayer``, ``MapViewport``, ``MapQuery``,
  ``MapColumn``, ``TableColumn``) are KEPT verbatim — verified valid against
  the vendored ``catalog_definition.json`` (spike 2026-08-29).

A handful of config fields (``StructuredTableConfig.total_rows``/
``truncated``) have no Pydantic ``alias`` set, so ``by_alias=True`` leaves
them in ``snake_case``. Rather than touch the config models (out of scope —
spec §1 Non-Goals), any remaining top-level ``snake_case`` property name is
converted to ``camelCase`` here, matching the wire convention used
everywhere else.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

__all__ = ["derive_schema"]

#: Binding-descriptor replacement for each INPUT-ONLY row/feature field.
_BINDING_DESCRIPTIONS: dict[str, str] = {
    "data": "Data-model binding ({'path': '/pointer'}) to the row set.",
    "datasets": "Data-model binding ({'path': '/pointer'}) to the per-layer payloads.",
}


def _snake_to_camel(name: str) -> str:
    """Convert a ``snake_case`` identifier to ``camelCase``.

    A no-op for names that are already ``camelCase``/single-word (no ``_``).

    Args:
        name: The field/property name to convert.

    Returns:
        The ``camelCase`` form of ``name``.
    """
    if "_" not in name:
        return name
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest if part)


def _strip_title_annotations(node: Any) -> None:
    """Recursively strip Pydantic-generated ``title`` annotations, in place.

    Only the schema-ANNOTATION ``title`` key is removed (e.g. the auto-title
    Pydantic attaches to every property's own schema dict, or to the root
    schema / a ``$defs`` entry). Keys inside a ``properties``/``$defs``
    MAPPING are field/model NAMES, not annotations, and are never touched —
    even if one of them happens to be literally ``"title"`` (e.g. the
    ``Chart.title`` config field).

    Args:
        node: A schema (sub-)dict, or a list of them (``anyOf``/``allOf``).
    """
    if isinstance(node, list):
        for item in node:
            _strip_title_annotations(item)
        return
    if not isinstance(node, dict):
        return
    node.pop("title", None)
    for key, value in node.items():
        if key in ("properties", "$defs"):
            for sub_schema in value.values():
                _strip_title_annotations(sub_schema)
        else:
            _strip_title_annotations(value)


def derive_schema(
    model: type[BaseModel],
    *,
    binding_fields: Sequence[str],
    required: Sequence[str] = (),
) -> dict[str, Any]:
    """Derive a parrot-catalog component ``SCHEMA`` from a config model.

    Args:
        model: The ``StructuredXConfig`` Pydantic model to derive from.
        binding_fields: Top-level field names that are INPUT-ONLY row/feature
            lists (e.g. ``("data",)`` or ``("data", "datasets")``) — replaced
            by the data-model binding descriptor instead of their raw
            (array) schema.
        required: Override for the schema's ``required`` list. When empty
            (default), the model's own computed ``required`` list is kept
            (camelCased, binding fields excluded — they are never required).

    Returns:
        A JSON-Schema dict: Pydantic ``title`` annotations stripped, ``$defs``
        kept verbatim, binding fields replaced, remaining property names
        camelCased.
    """
    schema = model.model_json_schema(by_alias=True)
    _strip_title_annotations(schema)

    properties: dict[str, Any] = schema.get("properties", {})
    new_properties: dict[str, Any] = {}
    for name, prop_schema in properties.items():
        camel_name = _snake_to_camel(name)
        if name in binding_fields:
            new_properties[camel_name] = {
                "description": _BINDING_DESCRIPTIONS.get(name, _BINDING_DESCRIPTIONS["data"]),
            }
        else:
            new_properties[camel_name] = prop_schema
    schema["properties"] = new_properties

    if required:
        schema["required"] = list(required)
    else:
        original_required = schema.get("required", [])
        schema["required"] = [_snake_to_camel(name) for name in original_required if name not in binding_fields]
        if not schema["required"]:
            schema.pop("required", None)

    return schema
