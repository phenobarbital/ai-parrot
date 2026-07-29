"""A2UI v1.0 wire message models.

This module ships the complete `A2UI v1.0 <https://a2ui.org/specification/v1.0-a2ui/>`_
message set as Pydantic v2 models exposed through a discriminated union.

Design invariants (spec FEAT-273):

* **Greenfield / one-way import rule (G8)** — nothing in this module imports from
  ``parrot.bots``, ``parrot.clients``, agents, or DatasetManager. Only Pydantic v2
  and the standard library are used.
* **``version`` is NOT owned here (G3)** — no model in this module declares,
  defaults, or validates the protocol ``version`` field. That field is the sole
  responsibility of :mod:`parrot.outputs.a2ui.serialization`. This keeps a future
  A2UI protocol fork absorbable in exactly one place.
* **Bindings are validated for *syntax* only** — data-model bindings embedded in
  component properties are checked with a light regex for JSON-Pointer shape.
  Full JSON Pointer *resolution* is deferred to the bake pass (Module 6) in the
  ``ai-parrot-visualizations`` satellite, which owns the ``jsonpointer`` dependency.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "A2UIMessage",
    "A2UIMessageBase",
    "Action",
    "ActionResponse",
    "BINDING_KEY",
    "CallFunction",
    "Component",
    "CreateSurface",
    "UpdateComponents",
    "UpdateDataModel",
    "is_binding_expression",
    "is_valid_pointer",
]

# ---------------------------------------------------------------------------
# Binding syntax
# ---------------------------------------------------------------------------

#: Marker key used inside a component property value to declare a data-model
#: binding, e.g. ``{"$bind": "/charts/blk-000/series"}``. The value MUST be a
#: JSON-Pointer-shaped string. Resolution happens in the bake pass, not here.
BINDING_KEY = "$bind"

#: RFC 6901 JSON Pointer *shape* (light syntax check only). A pointer is either
#: the empty string (whole document) or a sequence of ``/``-prefixed reference
#: tokens. Escaped characters ``~0``/``~1`` are permitted; raw whitespace and a
#: bare ``~`` are not.
_JSON_POINTER_RE = re.compile(r"^(?:/(?:[^/~\s]|~[01])*)*$")


def is_valid_pointer(pointer: str) -> bool:
    """Return whether ``pointer`` is a syntactically well-formed JSON Pointer.

    This is a *shape* check only (RFC 6901 grammar). It does NOT verify that the
    pointer resolves against any document — resolution is the bake pass's job.

    Args:
        pointer: The candidate JSON Pointer string.

    Returns:
        ``True`` if ``pointer`` matches the JSON Pointer grammar, else ``False``.
    """
    if not isinstance(pointer, str):
        return False
    # A non-empty pointer must start with "/"; the empty string is the whole doc.
    if pointer and not pointer.startswith("/"):
        return False
    return _JSON_POINTER_RE.match(pointer) is not None


def is_binding_expression(value: Any) -> bool:
    """Return whether ``value`` is a data-model binding expression.

    A binding is a mapping of the form ``{"$bind": "<json-pointer>"}``.

    Args:
        value: Any property value.

    Returns:
        ``True`` if ``value`` is a binding expression mapping, else ``False``.
    """
    return isinstance(value, dict) and BINDING_KEY in value


def _validate_bindings(value: Any) -> None:
    """Recursively validate every binding expression found in ``value``.

    Args:
        value: A component property (possibly nested dict/list) to scan.

    Raises:
        ValueError: If a binding expression carries a malformed JSON Pointer.
    """
    if is_binding_expression(value):
        pointer = value[BINDING_KEY]
        if not isinstance(pointer, str) or not is_valid_pointer(pointer):
            raise ValueError(
                f"Malformed data-model binding {BINDING_KEY!r}={pointer!r}: "
                "expected a JSON-Pointer-shaped string (e.g. '/charts/blk-000')."
            )
        return
    if isinstance(value, dict):
        for item in value.values():
            _validate_bindings(item)
    elif isinstance(value, list):
        for item in value:
            _validate_bindings(item)


# ---------------------------------------------------------------------------
# Component adjacency model
# ---------------------------------------------------------------------------


class Component(BaseModel):
    """A single node in an A2UI component adjacency list.

    Components form a flat adjacency list: ``children`` holds the *ids* of other
    components in the same message (component-id links), not nested objects.

    Attributes:
        id: Stable, deterministic component id (e.g. ``"blk-000"``).
        component: The catalog component type name (e.g. ``"Column"``, ``"Chart"``).
        properties: Declarative component properties; may contain binding
            expressions (``{"$bind": "/pointer"}``) whose syntax is validated here.
        children: Component-id references to child components.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str
    component: str
    properties: dict[str, Any] = Field(default_factory=dict)
    children: list[str] = Field(default_factory=list)

    @field_validator("properties")
    @classmethod
    def _check_binding_syntax(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Validate the syntax of any data-model bindings in ``properties``."""
        _validate_bindings(value)
        return value


# ---------------------------------------------------------------------------
# Message set (discriminated union on ``message_type`` / wire ``messageType``)
# ---------------------------------------------------------------------------


class A2UIMessageBase(BaseModel):
    """Base for every A2UI v1.0 wire message.

    Deliberately declares no ``version`` field — the protocol version is owned
    exclusively by :mod:`parrot.outputs.a2ui.serialization`.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class CreateSurface(A2UIMessageBase):
    """``createSurface`` — create a UI surface, optionally with inline content.

    v1.0 allows a one-shot, SSR-friendly surface by carrying inline ``components``
    and an initial ``data_model`` in the same message.
    """

    message_type: Literal["createSurface"] = Field(
        default="createSurface", alias="messageType"
    )
    surface_id: str = Field(alias="surfaceId")
    catalog_id: str = Field(alias="catalogId")
    components: list[Component] = Field(default_factory=list)
    data_model: dict[str, Any] = Field(default_factory=dict, alias="dataModel")


class UpdateComponents(A2UIMessageBase):
    """``updateComponents`` — replace/extend a surface's component adjacency list.

    Schema ships in FEAT-273; incremental dispatch is FEAT-B territory.
    """

    message_type: Literal["updateComponents"] = Field(
        default="updateComponents", alias="messageType"
    )
    surface_id: str = Field(alias="surfaceId")
    components: list[Component] = Field(default_factory=list)


class UpdateDataModel(A2UIMessageBase):
    """``updateDataModel`` — patch a surface's data model.

    ``contents`` maps JSON-Pointer paths to values (e.g. ``{"/charts/blk-000": ...}``).
    """

    message_type: Literal["updateDataModel"] = Field(
        default="updateDataModel", alias="messageType"
    )
    surface_id: str = Field(alias="surfaceId")
    contents: dict[str, Any] = Field(default_factory=dict)

    @field_validator("contents")
    @classmethod
    def _check_pointer_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Ensure every data-model key is a JSON-Pointer-shaped path."""
        for key in value:
            if not is_valid_pointer(key):
                raise ValueError(
                    f"Malformed data-model path {key!r}: expected a JSON Pointer."
                )
        return value


class Action(A2UIMessageBase):
    """``action`` — a user-originated action from a component (schema only in v1)."""

    message_type: Literal["action"] = Field(default="action", alias="messageType")
    surface_id: str = Field(alias="surfaceId")
    component_id: str = Field(alias="componentId")
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class ActionResponse(A2UIMessageBase):
    """``actionResponse`` — an agent's response to a prior ``action`` (schema only)."""

    message_type: Literal["actionResponse"] = Field(
        default="actionResponse", alias="messageType"
    )
    surface_id: str = Field(alias="surfaceId")
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class CallFunction(A2UIMessageBase):
    """``callFunction`` — an agent invokes a named client-side function (schema only)."""

    message_type: Literal["callFunction"] = Field(
        default="callFunction", alias="messageType"
    )
    function_name: str = Field(alias="functionName")
    arguments: dict[str, Any] = Field(default_factory=dict)


#: Discriminated union over the complete A2UI v1.0 message set. Parse wire data
#: with a ``TypeAdapter(A2UIMessage)`` (see :mod:`parrot.outputs.a2ui.serialization`).
A2UIMessage = Annotated[
    Union[
        CreateSurface,
        UpdateComponents,
        UpdateDataModel,
        Action,
        ActionResponse,
        CallFunction,
    ],
    Field(discriminator="message_type"),
]
