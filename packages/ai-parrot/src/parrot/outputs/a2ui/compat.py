"""Read-only compatibility layer: legacy (pre-v1.0) dialect → A2UI v1.0.

Per spec FEAT-470 G5, this module is **read-only**: it normalizes an
incoming legacy-dialect payload (``messageType`` + nested ``properties`` +
``{"$bind": ...}`` bindings) into the equivalent A2UI v1.0 envelope-by-key
shape. No emitter in this codebase uses it — it exists purely so
:func:`parrot.outputs.a2ui.serialization.deserialize` can keep accepting
data produced by pre-FEAT-470 callers while every new payload is emitted
strictly as v1.0.

Supported legacy ``messageType`` values: ``createSurface``,
``updateComponents``, ``updateDataModel``, ``callFunction``. Any other
legacy message type raises a clear ``ValueError`` — this module never
guesses at an unsupported shape (spec §7 Known Risks).

One-way import rule (G8): this module MUST NEVER import from
``parrot.bots``, ``parrot.clients``, agents, or DatasetManager.
"""

from __future__ import annotations

import uuid
from typing import Any

from parrot.outputs.a2ui.models import BINDING_KEY

__all__ = [
    "is_legacy_envelope",
    "normalize_legacy",
    "normalize_legacy_component",
]

#: The v1.0 wire version string every normalized envelope is stamped with,
#: overwriting whatever legacy ``version`` (if any, e.g. ``"1.0"``) was present.
_V1_VERSION = "v1.0"

#: Legacy ``messageType`` values this module knows how to normalize.
_SUPPORTED_LEGACY_TYPES = frozenset({"createSurface", "updateComponents", "updateDataModel", "callFunction"})


def is_legacy_envelope(data: dict[str, Any]) -> bool:
    """Return whether ``data`` looks like a pre-v1.0 dialect envelope.

    The legacy dialect always carries a ``messageType`` key; the v1.0 wire
    never does (it uses envelope-by-key: ``{"version", "<messageKey>"}``).

    Args:
        data: A candidate wire payload.

    Returns:
        ``True`` if ``data`` is a legacy-dialect envelope.
    """
    return isinstance(data, dict) and "messageType" in data


def _normalize_binding_value(value: Any) -> tuple[Any, list[str]]:
    """Recursively normalize legacy ``{"$bind": ...}`` bindings in ``value``.

    ``{"$bind": "/ptr"}`` becomes ``{"path": "/ptr"}``. A companion
    ``"optional": true`` marker is stripped from the binding object and its
    pointer is instead collected so the caller can hoist it into
    ``metadata.extensions.parrot_optional`` (spec §2/§7).

    Args:
        value: Any legacy property value (possibly nested dict/list).

    Returns:
        A ``(normalized_value, optional_pointers)`` pair.
    """
    if isinstance(value, dict) and BINDING_KEY in value:
        pointer = value[BINDING_KEY]
        is_optional = bool(value.get("optional"))
        return {"path": pointer}, ([pointer] if is_optional else [])

    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        optional_paths: list[str] = []
        for key, item in value.items():
            normalized[key], item_paths = _normalize_binding_value(item)
            optional_paths.extend(item_paths)
        return normalized, optional_paths

    if isinstance(value, list):
        normalized_items: list[Any] = []
        optional_paths = []
        for item in value:
            normalized_item, item_paths = _normalize_binding_value(item)
            normalized_items.append(normalized_item)
            optional_paths.extend(item_paths)
        return normalized_items, optional_paths

    return value, []


def normalize_legacy_component(comp: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single legacy (or already-v1.0) component dict.

    Heuristic (spec §7 Known Risks): a component carrying a ``properties``
    key is legacy-dialect; one without it is assumed already v1.0-shaped and
    is passed through unchanged (a genuine v1.0 ``Card`` with ``child`` is
    NEVER renamed — only a legacy ``Card`` that carried ``properties`` is).

    Args:
        comp: A single component dict from a legacy (or v1.0) envelope.

    Returns:
        The equivalent v1.0 component dict (top-level props, ``Card`` ->
        ``InfoCard``, ``$bind``/``optional`` -> ``path``/
        ``metadata.extensions.parrot_optional``).
    """
    if "properties" not in comp:
        return dict(comp)

    component_name = comp["component"]
    if component_name == "Card":
        component_name = "InfoCard"

    new_comp: dict[str, Any] = {"id": comp["id"], "component": component_name}

    optional_paths: list[str] = []
    for key, value in (comp.get("properties") or {}).items():
        new_comp[key], value_paths = _normalize_binding_value(value)
        optional_paths.extend(value_paths)

    children = comp.get("children")
    if children:
        new_comp["children"] = children

    if optional_paths:
        new_comp["metadata"] = {"extensions": {"parrot_optional": optional_paths}}

    return new_comp


def _normalize_create_surface(data: dict[str, Any]) -> dict[str, Any]:
    inner: dict[str, Any] = {
        "surfaceId": data["surfaceId"],
        "components": [normalize_legacy_component(c) for c in data.get("components", [])],
        "dataModel": data.get("dataModel", {}),
    }
    if data.get("catalogId"):
        inner["catalogId"] = data["catalogId"]
    return {"version": _V1_VERSION, "createSurface": inner}


def _normalize_update_components(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": _V1_VERSION,
        "updateComponents": {
            "surfaceId": data["surfaceId"],
            "components": [normalize_legacy_component(c) for c in data.get("components", [])],
        },
    }


def _normalize_update_data_model(data: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    surface_id = data["surfaceId"]
    contents = data.get("contents") or {}
    items = list(contents.items())

    def _envelope(path: str, value: Any) -> dict[str, Any]:
        return {
            "version": _V1_VERSION,
            "updateDataModel": {"surfaceId": surface_id, "path": path, "value": value},
        }

    if len(items) == 1:
        path, value = items[0]
        return _envelope(path, value)
    return [_envelope(path, value) for path, value in items]


def _normalize_call_function(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": _V1_VERSION,
        "callRendererFunction": {
            "functionCallId": data.get("functionCallId") or f"legacy-{uuid.uuid4().hex}",
            "callFunction": {
                "call": data["functionName"],
                "args": data.get("arguments", {}),
            },
        },
    }


def normalize_legacy(data: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    """Normalize a legacy-dialect envelope to its A2UI v1.0 equivalent.

    Args:
        data: A legacy-dialect envelope (``"messageType" in data``).

    Returns:
        The v1.0 envelope dict, OR (only for a legacy ``updateDataModel``
        whose ``contents`` has more than one key) a list of v1.0 envelope
        dicts — one per ``contents`` entry, in insertion order.

    Raises:
        ValueError: If ``messageType`` is missing or not a supported legacy
            message type. This module never guesses at an unsupported shape.
    """
    message_type = data.get("messageType")
    if message_type not in _SUPPORTED_LEGACY_TYPES:
        raise ValueError(
            f"compat.normalize_legacy: unsupported legacy messageType {message_type!r}. "
            f"Supported: {sorted(_SUPPORTED_LEGACY_TYPES)}."
        )

    if message_type == "createSurface":
        return _normalize_create_surface(data)
    if message_type == "updateComponents":
        return _normalize_update_components(data)
    if message_type == "updateDataModel":
        return _normalize_update_data_model(data)
    return _normalize_call_function(data)
