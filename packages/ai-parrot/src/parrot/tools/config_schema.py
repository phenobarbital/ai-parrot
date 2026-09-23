"""Toolkit configuration JSON Schema (FEAT-593): one Draft 2020-12 envelope per toolkit."""

from __future__ import annotations

import inspect
import logging
import types
import typing
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
SECRET_NAME_HINTS: frozenset[str] = frozenset(
    {"token", "password", "api_key", "secret", "dsn", "credentials", "access_token", "private_key"}
)


class ConfigOption(BaseModel):
    """One dynamic choice returned by ``AbstractToolkit.config_options``."""

    value: str
    label: str


class ToolkitSchemaEnvelope(BaseModel):
    """``GET /astudio/toolkits/{slug}/schema`` response."""

    model_config = ConfigDict(populate_by_name=True)
    slug: str
    class_name: str
    source: Literal["model", "introspection"]
    schema_: dict[str, Any] = Field(alias="schema")


def is_secret_name(name: str, curated: frozenset[str] = frozenset()) -> bool:
    """True when ``name`` is curated or contains any hint (case-insensitive substring)."""
    lowered = name.lower()
    return name in curated or any(hint in lowered for hint in SECRET_NAME_HINTS)


def _json_safe(value: Any) -> Any:
    """Coerce a constructor default into a JSON-serialisable value."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return str(value)


def _json_type(annotation: Any) -> dict[str, Any] | None:
    """Map an annotation to a JSON Schema fragment; ``None`` means server-managed."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}
    if isinstance(annotation, str):
        # Forward-ref string annotations ("Foo") cannot be resolved safely here.
        return None
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is getattr(types, "UnionType", None):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _json_type(args[0])
        if not args:
            return None
        fragments = [_json_type(a) for a in args]
        if any(fragment is None for fragment in fragments):
            return None
        return {"anyOf": fragments}
    if origin is Literal:
        return {"enum": list(typing.get_args(annotation))}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is str:
        return {"type": "string"}
    if origin in (list, tuple) or annotation in (list, tuple):
        return {"type": "array"}
    if origin is dict or annotation is dict:
        return {"type": "object"}
    if inspect.isclass(annotation):
        return None
    return None


def introspect_config_schema(cls: type, *, server_managed: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Lift ``cls.__init__`` into a Draft 2020-12 object schema (see module notes)."""
    curated = frozenset(getattr(cls, "secret_params", frozenset()))
    overridable = frozenset(getattr(cls, "default_user_overridable", frozenset()))
    options = frozenset(getattr(cls, "options_params", frozenset()))
    properties: dict[str, Any] = {}
    required: list[str] = []
    for pname, param in inspect.signature(cls.__init__).parameters.items():
        if pname == "self" or param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        fragment = _json_type(param.annotation)
        if fragment is None or pname in server_managed:
            properties[pname] = {"x-server-managed": True}
            continue
        prop: dict[str, Any] = dict(fragment)
        has_default = param.default is not inspect.Parameter.empty
        if has_default:
            prop["default"] = _json_safe(param.default)
        else:
            required.append(pname)
        if is_secret_name(pname, curated):
            prop["x-secret"] = True
        if pname in overridable:
            prop["x-user-overridable"] = True
        if pname in options:
            prop["x-options"] = True
        properties[pname] = prop
    return {"$schema": DRAFT_2020_12, "type": "object", "properties": properties, "required": required}


def model_config_schema(cls: type) -> dict[str, Any]:
    """``cls.config_model.model_json_schema()`` plus the ``x-*`` extensions."""
    schema = cls.config_model.model_json_schema()
    curated = frozenset(getattr(cls, "secret_params", frozenset()))
    overridable = frozenset(getattr(cls, "default_user_overridable", frozenset()))
    options = frozenset(getattr(cls, "options_params", frozenset()))

    for prop_name, prop_schema in schema.get("properties", {}).items():
        if "x-secret" not in prop_schema and is_secret_name(prop_name, curated):
            prop_schema["x-secret"] = True
        if prop_name in overridable:
            prop_schema["x-user-overridable"] = True
        if prop_name in options:
            prop_schema["x-options"] = True

    for def_schema in schema.get("$defs", {}).values():
        for prop_name, prop_schema in def_schema.get("properties", {}).items():
            if "x-secret" not in prop_schema and is_secret_name(prop_name):
                prop_schema["x-secret"] = True

    schema["$schema"] = DRAFT_2020_12
    return schema


def build_schema_envelope(
    slug: str, cls: type, *, server_managed: frozenset[str] = frozenset()
) -> ToolkitSchemaEnvelope:
    """``source='model'`` when ``cls.config_model`` is set, else ``'introspection'``."""
    if getattr(cls, "config_model", None) is not None:
        return ToolkitSchemaEnvelope(
            slug=slug, class_name=cls.__name__, source="model", schema=model_config_schema(cls)
        )
    return ToolkitSchemaEnvelope(
        slug=slug,
        class_name=cls.__name__,
        source="introspection",
        schema=introspect_config_schema(cls, server_managed=server_managed),
    )


def secret_paths(schema: dict[str, Any], params: dict[str, Any]) -> list[str]:
    """Dotted paths of every value in ``params`` the schema marks ``x-secret``."""
    defs = schema.get("$defs", {})

    def resolve(node: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in node:
            ref_name = node["$ref"].rsplit("/", 1)[-1]
            return defs.get(ref_name, {})
        return node

    def pick_branch(node: dict[str, Any], value: Any) -> dict[str, Any] | None:
        discriminator = node.get("discriminator") or {}
        prop_name = discriminator.get("propertyName")
        branches = [resolve(branch) for branch in node.get("oneOf", [])]
        if not branches:
            return None
        if prop_name is None or not isinstance(value, dict) or prop_name not in value:
            return branches[0]
        disc_value = value[prop_name]
        mapping = discriminator.get("mapping") or {}
        ref = mapping.get(disc_value)
        if ref:
            ref_name = ref.rsplit("/", 1)[-1]
            if ref_name in defs:
                return defs[ref_name]
        for branch in branches:
            prop_schema = branch.get("properties", {}).get(prop_name, {})
            if prop_schema.get("const") == disc_value or disc_value in prop_schema.get("enum", []):
                return branch
        return None

    def walk_object(node: dict[str, Any], value: Any, path: str, results: list[str]) -> None:
        node = resolve(node)
        if not isinstance(value, dict):
            return
        properties = node.get("properties", {})
        for key, item_value in value.items():
            prop_schema = properties.get(key)
            if prop_schema is None:
                continue
            new_path = f"{path}.{key}" if path else key
            walk_value(prop_schema, item_value, new_path, results)

    def walk_value(node: dict[str, Any], value: Any, path: str, results: list[str]) -> None:
        node = resolve(node)
        if node.get("x-secret") is True:
            results.append(path)
            return
        if "oneOf" in node:
            branch = pick_branch(node, value)
            if branch is not None:
                walk_object(branch, value, path, results)
            return
        if node.get("type") == "array" and isinstance(value, list):
            items_schema = node.get("items", {})
            for index, item in enumerate(value):
                walk_value(items_schema, item, f"{path}.{index}" if path else str(index), results)
            return
        if node.get("type") == "object" or "properties" in node:
            walk_object(node, value, path, results)

    results: list[str] = []
    walk_object(schema, params, "", results)
    return results
