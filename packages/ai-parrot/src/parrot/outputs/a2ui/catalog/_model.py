"""Catalog JSON Schema -> Pydantic model, for ``structured_output`` (FEAT-755).

The emitter advertises a component's schema to the LLM as a Pydantic model rather
than serializing JSON Schema into the prompt. The catalog's schemas are deliberately
loose, and this generator MUST preserve that looseness: a model stricter than its
schema makes a legal config unauthorable, and the failure is invisible.

The opposite direction lives in ``catalog/parrot/_derive.py`` (Pydantic -> schema).
"""
from __future__ import annotations

import keyword
import logging
import re
from typing import Any, Literal, Mapping, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, create_model

logger = logging.getLogger(__name__)

__all__ = ["model_from_schema", "component_model", "clear_model_cache"]

_CACHE: dict[tuple[Optional[str], str], type[BaseModel]] = {}

_MODEL_CONFIG = ConfigDict(extra="allow", populate_by_name=True, protected_namespaces=())

_SCALARS: dict[str, Any] = {
    "string": str,
    "boolean": bool,
    "integer": int,
    # ``number`` keeps an int an int (``float`` alone would coerce 42 -> 42.0).
    "number": Union[int, float],
    "null": type(None),
}


def _camel(name: str) -> str:
    """Return a PascalCase fragment of ``name`` usable in a generated model name."""
    parts = re.split(r"[^0-9A-Za-z]+", name)
    return "".join(p[:1].upper() + p[1:] for p in parts if p) or "Field"


def _single_type(type_name: str, prop: Mapping[str, Any], *, name: str) -> Any:
    """Map ONE JSON-Schema ``type`` keyword value to a Python annotation."""
    if type_name in _SCALARS:
        return _SCALARS[type_name]
    if type_name == "object":
        if isinstance(prop.get("properties"), Mapping) and prop["properties"]:
            return model_from_schema(prop, name=name)
        return dict[str, Any]
    if type_name == "array":
        items = prop.get("items")
        if isinstance(items, Mapping) and items:
            return list[_python_type(items, name=f"{name}Item")]  # type: ignore[misc]
        return list[Any]
    # Unknown type keyword: never tighten.
    return Any


def _python_type(prop: Mapping[str, Any], *, name: str) -> Any:
    """Map ONE JSON-Schema property to a Python annotation.

    Rules (each exists for a real catalog property — do not "simplify"):
      * no ``type`` key        -> ``Any``        (KPICard ``value`` / ``delta``)
      * ``["array","object"]`` -> ``Union[list, dict]``  (KPICard ``series``)
      * ``["boolean","null"]`` -> ``Optional[bool]``     (KPICard ``higherIsBetter``)
      * ``enum``               -> ``Literal[...]``
      * ``object`` / ``array`` -> a nested model built by the same rules

    Args:
        prop: The property's JSON-Schema fragment.
        name: A name used for any nested model generated from it.

    Returns:
        A Python type annotation never stricter than ``prop``.
    """
    if not isinstance(prop, Mapping):
        return Any
    enum = prop.get("enum")
    if isinstance(enum, (list, tuple)) and enum:
        try:
            return Literal[tuple(enum)]  # type: ignore[valid-type]
        except TypeError:  # unhashable enum members (objects/arrays)
            return Any
    type_ = prop.get("type")
    if type_ is None:
        return Any
    if isinstance(type_, str):
        return _single_type(type_, prop, name=name)
    if isinstance(type_, (list, tuple)) and type_:
        members = tuple(_single_type(str(t), prop, name=name) for t in type_)
        if any(m is Any for m in members):
            return Any
        if len(members) == 1:
            return members[0]
        return Union[members]  # type: ignore[valid-type]
    return Any


def _field_name(prop_name: str, index: int) -> str:
    """Return a Python-safe field name for ``prop_name`` (aliased when it differs)."""
    if (
        prop_name.isidentifier()
        and not keyword.iskeyword(prop_name)
        and not prop_name.startswith("_")
        and not hasattr(BaseModel, prop_name)
    ):
        return prop_name
    return f"field_{index}"


def model_from_schema(schema: Mapping[str, Any], *, name: str) -> type[BaseModel]:
    """Build a Pydantic v2 model from a catalog component's JSON Schema.

    Every property is Optional unless listed in ``schema["required"]``; each field
    carries the schema's ``description`` verbatim; ``extra="allow"`` so a binding
    descriptor (``{"path": "/pointer"}``) is accepted in place of any value.

    Returns a NEW type on each call — callers cache (see :func:`component_model`).

    Args:
        schema: The object JSON Schema (``{"type": "object", "properties": ...}``).
        name: The generated model's class name.

    Returns:
        A freshly created Pydantic model class.
    """
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or ())
    fields: dict[str, Any] = {}
    for index, (prop_name, prop) in enumerate(properties.items()):
        prop = prop if isinstance(prop, Mapping) else {}
        annotation = _python_type(prop, name=f"{name}{_camel(prop_name)}")
        field_name = _field_name(prop_name, index)
        kwargs: dict[str, Any] = {}
        if field_name != prop_name:
            kwargs["alias"] = prop_name
        if "description" in prop:
            kwargs["description"] = prop["description"]
        if prop_name in required:
            fields[field_name] = (annotation, Field(..., **kwargs))
        else:
            # Default None + ``exclude_unset`` keeps "omitted" distinct from "null".
            fields[field_name] = (Optional[annotation], Field(None, **kwargs))
    model = create_model(name, __config__=_MODEL_CONFIG, **fields)  # type: ignore[call-overload]
    if schema.get("description"):
        model.__doc__ = str(schema["description"])
    return model


def component_model(component: str, catalog_id: Optional[str] = None) -> type[BaseModel]:
    """The model to advertise as ``structured_output`` for ``component``.

    Returns ``component_cls.SOURCE_MODEL`` verbatim when the component declares one
    (only ``Graph`` does in v1 — round-tripping ``GraphSpec`` through ``GRAPH_SCHEMA``
    would discard its validators), else generates from ``definition.schema_``.

    Args:
        component: The registered component name.
        catalog_id: Optional catalog id for an exact lookup.

    Returns:
        The (cached) Pydantic model class.

    Raises:
        KeyError: If ``component`` is not registered (same contract as ``get_component``).
    """
    from parrot.outputs.a2ui.catalog import get_component  # local: avoids an import cycle

    key = (catalog_id, component)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    registered = get_component(component, catalog_id)
    source = getattr(registered.component_cls, "SOURCE_MODEL", None)
    if source is not None:
        model = source
    else:
        model = model_from_schema(registered.definition.schema_, name=f"{_camel(component)}Model")
        logger.debug("Generated structured_output model for %r (%s)", component, catalog_id)
    _CACHE[key] = model
    return model


def clear_model_cache() -> None:
    """Drop every cached model (test isolation, pairs with ``unregister_component``)."""
    _CACHE.clear()
